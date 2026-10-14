"""Reporting orchestration. Preview and apply share the same calculation path."""

from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from . import settings
from .ai import summarize
from .diagnostics import Problem, event, stage, error_details, reference
from .mail import DeliverySession, deliver
from .reports import (
    CLASS_DATE,
    HOURS,
    NAME,
    TAUGHT,
    header,
    load_roster,
    number,
    select_reports,
    valid_email,
    week_of,
)
from .storage import Journal, Sheets, read_csv


def validate_response_headers(headers):
    expected = ["Timestamp", NAME, TAUGHT, HOURS, CLASS_DATE]
    if not all(header(h) in {header(x) for x in headers} for h in expected):
        raise Problem("response_schema_changed")


def representatives(rows):
    result = []
    for item in rows:
        values = item["values"]

        def get(aliases):
            found = [str(v).strip() for k, v in values.items() if header(k) in {header(a) for a in aliases}]
            if len(found) != 1 or not found[0]:
                raise Problem("representative_schema_invalid")
            return found[0]

        name = get(["Name", "Representative Name", "Rep Name"])
        school = get(["School", "Tutor School", "College", "Institution", "Representative School"])
        email = get(["Email", "Representative Email", "Email Address", "Rep Email"]).lower()
        if not valid_email(email):
            raise Problem("representative_email_invalid")
        result.append({"name": name, "school": school, "email": email})
    if not result:
        raise Problem("empty_representatives")
    return result


def check_baseline(payload, tutors):
    try:
        start = date.fromisoformat(payload["start_week"])
        if start != week_of(start):
            raise Problem("baseline_week_must_be_monday")
        hours = {key: number(value) for key, value in payload["hours"].items()}
    except (KeyError, TypeError, ValueError):
        raise Problem("baseline_invalid") from None
    if not {t.id for t in tutors.values()}.issubset(hours):
        raise Problem("baseline_tutor_missing")
    return start, hours


def calculate_totals(latest, tutors, baseline):
    start, opening = check_baseline(baseline, tutors)
    totals = {t.id: opening[t.id] for t in tutors.values()}
    for (tutor_id, week), report in latest.items():
        if week < start:
            if report.revision in baseline.get("covered_revisions", []):
                continue
            raise Problem("report_predates_opening_balance_review_required")
        totals[tutor_id] += report.hours
    return totals


def extend_opening_balance(baseline, journal, tutors):
    """New tutors start at zero; existing unrecognized history requires reconciliation."""
    extended = {**baseline, "hours": dict(baseline["hours"])}
    additions = journal.latest("opening_addition")
    for tutor_id, payload in additions.items():
        extended["hours"][tutor_id] = payload["hours"]
    pending = []
    for tutor in tutors.values():
        if tutor.id not in extended["hours"]:
            if tutor.total_hours or tutor.checkpoint:
                raise Problem("new_identity_has_history_review_required")
            extended["hours"][tutor.id] = "0"
            pending.append(("opening_addition", tutor.id, {"hours": "0"}))
    return extended, pending


def prepare(tutors, items, journal, zone, today):
    historical = list(journal.latest("response").values())
    all_items = historical + items
    with stage("validate_and_select_reports", input_rows=len(all_items)):
        revisions, latest, issues = select_reports(
            all_items, tutors, zone, settings.PLACEHOLDER_POLICY, today
        )
    return revisions, latest, issues


def render(tutors, revisions, latest, report_week, totals, journal, ai_enabled=False, zone="UTC"):
    schools = {}
    ai_errors = 0
    end = report_week + timedelta(days=6)
    for tutor in tutors.values():
        selected = latest.get((tutor.id, report_week))
        summaries = []
        # Include delayed reports in the appropriate school's follow-up without adding their hours to this week.
        relevant = [selected] if selected else []
        relevant += [
            r
            for (tid, week), r in latest.items()
            if tid == tutor.id
            and week < report_week
            and report_week <= r.submitted.astimezone(ZoneInfo(zone)).date() <= end
        ]
        for report in relevant:
            if report is not selected:
                summaries.append(
                    f"Late report for {report.week}–{report.week + timedelta(days=6)}: {report.hours} hours."
                )
            versions = [r for r in revisions if r.tutor_id == tutor.id and r.week == report.week]
            if ai_enabled:
                try:
                    text = summarize(report, versions, journal)
                except Exception as exc:
                    from .diagnostics import error_details

                    event(
                        "summary_unavailable",
                        "ERROR",
                        tutor_ref=tutor.id,
                        week=str(report.week),
                        **error_details(exc),
                    )
                    ai_errors += 1
                    text = "AI summary unavailable. Review the original report in the response history."
                summaries.append(text)
            else:
                summaries.append("Preview: AI summary not requested.")
        submissions = sum(r.tutor_id == tutor.id for r in revisions)
        lessons = sum(r.tutor_id == tutor.id and r.taught for r in latest.values())
        total_hours = totals[tutor.id] if totals is not None else tutor.total_hours
        line = (
            f"{tutor.name} (Weekly Hours: {selected.hours if selected else 0}, "
            f"Submissions: {submissions}, Lessons: {lessons}, Total Hours: {total_hours}): "
            + (" ".join(summaries) if summaries else "No response this week")
        )
        schools.setdefault(tutor.school, []).append(line)
    school_text = {school: "\n\n".join(lines) for school, lines in sorted(schools.items())}
    current = [r for (tid, week), r in latest.items() if week == report_week]
    management = (
        "Weekly Tutor Report Summary\n\n"
        "Overall Statistics:\n"
        f"Total Tutors: {len(tutors)}\n"
        f"Total Submissions This Week: {len(current)}\n"
        f"Total Tutors Who Taught This Week: {sum(r.taught for r in current)}\n"
        f"Total Hours This Week: {sum((r.hours for r in current), Decimal(0))}\n"
        f"Total Hours All Time: {sum(totals.values(), Decimal(0)) if totals is not None else sum((t.total_hours for t in tutors.values()), Decimal(0))}\n\n"
    )
    for school, text in school_text.items():
        management += f"\n=== {school} ===\n{text}\n"
    return school_text, management, ai_errors


def report_job(
    report_week,
    apply=False,
    roster_csv=None,
    response_csv=(),
    baseline_file=None,
    today=None,
    zone=settings.REPORT_TIMEZONE,
    sheets=None,
    output=None,
    include_archives=False,
):
    today = today or date.today()
    sheets = sheets or Sheets()
    local = roster_csv is not None
    if apply and local:
        raise Problem("local_csv_apply_not_supported")
    with stage("load_roster"):
        _, roster_rows = read_csv(roster_csv) if local else sheets.read(settings.TUTOR_INFO_CSV_URL)
        tutors = load_roster(roster_rows)
    items = []
    with stage("load_responses"):
        if local:
            for path in response_csv:
                headers, rows = read_csv(path)
                validate_response_headers(headers)
                items.extend(rows)
            journal = Journal()
        else:
            headers, items = sheets.read(settings.RESPONSE_CSV_URL, settings.RESPONSE_TAB)
            validate_response_headers(headers)
            if include_archives:
                with stage("load_archives"):
                    for worksheet in sheets.book(settings.RESPONSE_CSV_URL).worksheets():
                        if worksheet.title.startswith("Archive_"):
                            archive_headers, archive_rows = sheets.read(
                                settings.RESPONSE_CSV_URL, worksheet.title
                            )
                            validate_response_headers(archive_headers)
                            items.extend(archive_rows)
            zone = sheets.response_timezone()
            journal = sheets.journal(writable=False)
    baseline = journal.latest("baseline").get("opening")
    if baseline_file:
        supplied = json.loads(Path(baseline_file).read_text(encoding="utf-8"))
        check_baseline(supplied, tutors)
        if baseline and supplied != baseline:
            raise Problem("opening_balance_already_initialized")
        baseline = supplied
    revisions, latest, issues = prepare(tutors, items, journal, zone, today)
    extended_baseline, additions = (
        extend_opening_balance(baseline, journal, tutors) if baseline else (None, [])
    )
    totals = calculate_totals(latest, tutors, extended_baseline) if baseline else None
    event(
        "report_preview",
        tutors=len(tutors),
        valid_revisions=len(revisions),
        weekly_reports=len(latest),
        rejected_rows=len(issues),
        week=str(report_week),
        baseline_available=baseline is not None,
    )
    if not apply:
        if output:
            # Deliberate separate private output; never included in diagnostics artifacts.
            school_text, management, _ = render(
                tutors, revisions, latest, report_week, totals, journal, zone=zone
            )
            if issues:
                management = (
                    f"INCOMPLETE PREVIEW: {len(issues)} invalid response(s); results must not be applied.\n\n"
                    + management
                )
            Path(output).write_text(management, encoding="utf-8")
        return {
            "tutors": len(tutors),
            "revisions": len(revisions),
            "weeks": len(latest),
            "issues": issues,
            "baseline_available": baseline is not None,
        }
    if issues:
        raise Problem("invalid_responses_block_apply")
    if baseline is None:
        raise Problem("reviewed_opening_balance_required")
    with stage("validate_recipients"):
        _, rep_rows = sheets.read(settings.REPRESENTATIVE_CSV_URL)
        reps = representatives(rep_rows)
        schools = {t.school for t in tutors.values()}
        missing = schools - {r["school"] for r in reps}
        if missing:
            event("schools_without_representative", "WARNING", count=len(missing))
        # Missing school reps never become invented test recipients; management still receives all schools.
        if not settings.MANAGEMENT_EMAILS or not all(valid_email(x) for x in settings.MANAGEMENT_EMAILS):
            raise Problem("management_recipients_invalid")
        if not valid_email(settings.SENDER_EMAIL):
            raise Problem("sender_email_invalid")
        if not settings.OPENAI_API_KEY:
            raise Problem("openai_api_key_missing")
    journal = sheets.journal(writable=True)
    # Recalculate from the reread journal. CLI/Actions serialize participating writers.
    stored_baseline = journal.latest("baseline").get("opening")
    if stored_baseline and stored_baseline != baseline:
        raise Problem("opening_balance_changed_during_run")
    revisions, latest, issues = prepare(tutors, items, journal, zone, today)
    if issues:
        raise Problem("invalid_responses_block_apply")
    extended_baseline, additions = extend_opening_balance(baseline, journal, tutors)
    totals = calculate_totals(latest, tutors, extended_baseline)
    journal.append("baseline", "opening", baseline)
    journal.append_many(additions)
    journal.append_many(
        [("response", r.revision, {"source": r.source, "row": r.row, "values": r.values}) for r in revisions]
    )
    school_text, management, ai_errors = render(
        tutors, revisions, latest, report_week, totals, journal, ai_enabled=True, zone=zone
    )
    sheets.update_roster(tutors, latest, totals, report_week)
    deliveries = [
        (
            r["email"],
            f"E2S Weekly Report - {r['school']}",
            f"Dear {r['name']},\n\n"
            f"Here is this week's summary for {r['school']} tutors:\n\n"
            f"{school_text[r['school']]}\n\n"
            "Best regards,\n"
            "English2Success Team",
        )
        for r in reps
        if r["school"] in school_text
    ]
    deliveries.extend(
        (email, "E2S Complete Weekly Report - All Schools", management)
        for email in settings.MANAGEMENT_EMAILS
    )
    failures = 0
    sender = DeliverySession()
    for email, subject, body in deliveries:
        try:
            deliver(email, subject, body, journal, sender)
        except Problem as exc:
            event("recipient_delivery_failed", "ERROR", recipient_ref=reference(email), **error_details(exc))
            failures += 1
    event("report_delivery_summary", planned=len(deliveries), failed=failures, ai_failed=ai_errors)
    if failures or ai_errors:
        raise Problem("report_run_incomplete")
    return {"delivered_or_previously_accepted": len(deliveries)}


def reminder_job(report_week, apply=False, sheets=None, campaign="monday"):
    sheets = sheets or Sheets()
    _, rows = sheets.read(settings.TUTOR_INFO_CSV_URL)
    tutors = load_roster(rows)
    event("reminder_preview", recipients=len(tutors), week=str(report_week), campaign=campaign)
    if not apply:
        return
    if not settings.FORM_URL or not settings.DRIVE_FOLDER_URL or not valid_email(settings.SENDER_EMAIL):
        raise Problem("reminder_configuration_missing")
    journal = sheets.journal(writable=True)
    failures = 0
    sender = DeliverySession()
    for tutor in tutors.values():
        body = (
            f"Dear {tutor.name.split()[0]},\n\n"
            "Here is the Google Forms link to submit your lesson report for this week:\n"
            f"👉 {settings.FORM_URL}\n\n"
            "Please submit it before Sunday 22:00 GMT SHARP, even if you did not have class this week.\n\n"
            "Thank you so much for your time and dedication!\n\n"
            "Here is the google drive folder with teaching resources. There are also resources uploaded by other tutors on the Resources by Tutors folder. There, you can also share your own resources with other tutors.\n"
            f"Here is the drive link: {settings.DRIVE_FOLDER_URL}\n\n"
            "If you have any questions, please reach out to your UWC representative or contact me at:\n"
            f"{settings.SENDER_EMAIL}\n\n"
            "Best regards,\n"
            "Enes \n"
            "P.S. This is an automated email, but you can reply to it if you have any questions."
        )
        try:
            deliver(
                tutor.email, "Important: Please Submit Your Weekly Report", body, journal, sender
            )
        except Problem as exc:
            event(
                "recipient_delivery_failed",
                "ERROR",
                recipient_ref=reference(tutor.email),
                **error_details(exc),
            )
            failures += 1
    if failures:
        raise Problem("reminder_delivery_incomplete")
