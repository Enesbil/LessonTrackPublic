"""Pure weekly accounting: no Google, OpenAI, filesystem writes or email."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo

from .diagnostics import Problem, event, reference

NAME = "Select your name from the list."
TAUGHT = "Did you tutor this week?"
HOURS = "How many hours did you tutor this week?\nIf you did not teach at all this week, respond with 0."
CLASS_DATE = "Date of Class (if you did not tutor put 01/01/2025)"
ACTIVITIES = "What did you do in class? What content did you go over, what resources did you use? (if you did not tutor this week write why you did not)"
PLANS = "What are your future lesson plans for next week and beyond?"
ISSUES = 'Were there any serious issues? (if not respond: "No Issues")'
PLACEHOLDERS = {date(2025, 1, 1), date(2026, 1, 1)}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def week_of(day):
    return day - timedelta(days=day.weekday())


def header(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def rows_from_values(values, source):
    if not values:
        raise Problem("sheet_missing_header")
    headers = [str(x).strip() for x in values[0]]
    normalized = [header(x) for x in headers]
    if any(not x for x in normalized) or len(set(normalized)) != len(normalized):
        raise Problem("sheet_invalid_headers")
    rows = []
    for number, values_row in enumerate(values[1:], 2):
        if not any(str(x).strip() for x in values_row):
            continue
        if str(values_row[0]).strip() == "Archive created on:":
            continue
        if len(values_row) > len(headers):
            raise Problem("sheet_row_wider_than_header")
        row = dict(zip(headers, list(values_row) + [""] * (len(headers) - len(values_row))))
        rows.append({"source": source, "row": number, "values": row})
    return headers, rows


def field(row, name, required=True):
    matches = [v for k, v in row.items() if header(k) == header(name)]
    if len(matches) != 1:
        if required:
            raise Problem("required_column_missing")
        return ""
    return str(matches[0]).strip()


def number(value, maximum=None):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise Problem("invalid_hours") from None
    if not result.is_finite() or result < 0 or (maximum is not None and result > maximum):
        raise Problem("invalid_hours")
    return result


def parse_datetime(value, zone="UTC"):
    if isinstance(value, (int, float)):
        result = datetime(1899, 12, 30) + timedelta(days=value)
    else:
        text = str(value).strip()
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            result = None
            for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y"):
                try:
                    result = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    pass
            if result is None:
                raise Problem("invalid_date")
    if result.tzinfo is None:
        local = result.replace(tzinfo=ZoneInfo(zone))
        # A DST fold/gap cannot be ordered safely without an explicit UTC offset.
        if local.utcoffset() != local.replace(fold=1).utcoffset():
            raise Problem("ambiguous_local_timestamp")
        result = local
    return result


@dataclass(frozen=True)
class Tutor:
    id: str
    name: str
    school: str
    email: str
    row: int
    total_hours: Decimal
    checkpoint: str


def load_roster(rows):
    tutors = {}
    seen_emails = set()
    for item in rows:
        row = item["values"]
        name = field(row, "Tutor Name")
        school, email = field(row, "Tutor School"), field(row, "Email").lower()
        if not name or not school or not valid_email(email):
            raise Problem("invalid_roster_identity")
        tutor_id = field(row, "Tutor ID", required=False) or reference(name)
        if name in tutors or email in seen_emails or tutor_id in {t.id for t in tutors.values()}:
            raise Problem("duplicate_roster_identity")
        tutors[name] = Tutor(
            tutor_id,
            name,
            school,
            email,
            item["row"],
            number(field(row, "Total Hours") or "0"),
            field(row, "Last Processed Timestamp", required=False),
        )
        seen_emails.add(email)
    if not tutors:
        raise Problem("empty_roster")
    return tutors


def valid_email(value):
    return bool(re.fullmatch(r"[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+", value))


@dataclass(frozen=True)
class Report:
    revision: str
    tutor_id: str
    week: date
    submitted: datetime
    hours: Decimal
    taught: bool
    source: str
    row: int
    values: dict
    inferred_from: str


def parse_report(item, tutors, zone="UTC", placeholder_policy="review", today=None):
    row = item["values"]
    name = field(row, NAME)
    if name not in tutors:
        raise Problem("unknown_tutor")
    tutor = tutors[name]
    raw_timestamp = next((v for k, v in row.items() if header(k) == header("Timestamp")), "")
    submitted = parse_datetime(raw_timestamp, zone)
    raw_date = next((v for k, v in row.items() if header(k) == header(CLASS_DATE)), "")
    class_date = parse_datetime(raw_date, zone).date()
    taught_text = field(row, TAUGHT).casefold()
    if taught_text not in {"yes", "no"}:
        raise Problem("invalid_taught_answer")
    taught = taught_text == "yes"
    hours = number(field(row, HOURS), Decimal(168))
    if (not taught and hours != 0) or (taught and hours == 0):
        raise Problem("conflicting_hours_and_taught")
    if class_date in PLACEHOLDERS:
        if taught or hours != 0:
            raise Problem("placeholder_with_teaching")
        if placeholder_policy != "submission_week":
            raise Problem("placeholder_week_needs_review")
        report_week = week_of(submitted.astimezone(ZoneInfo(zone)).date())
        inferred_from = "submission_placeholder"
    else:
        if class_date > submitted.astimezone(ZoneInfo(zone)).date():
            raise Problem("class_date_after_submission")
        if taught and class_date.year < 2025:
            raise Problem("implausible_class_date")
        report_week = week_of(class_date)
        inferred_from = "class_date"
    if today is not None and submitted.astimezone(ZoneInfo(zone)).date() > today:
        raise Problem("future_submission")
    email = field(row, "Email Address", required=False).lower()
    if email and email != tutor.email:
        event(
            "respondent_email_differs", "WARNING", source=item["source"], row=item["row"], tutor_ref=tutor.id
        )
    submitted = submitted.astimezone(timezone.utc)
    revision = digest({"tutor": tutor.id, "timestamp": submitted.isoformat(), "values": row})
    return Report(
        revision,
        tutor.id,
        report_week,
        submitted,
        hours,
        taught,
        item["source"],
        item["row"],
        row,
        inferred_from,
    )


def select_reports(items, tutors, zone="UTC", placeholder_policy="review", today=None):
    """Latest wins per class-date week. Ambiguous ties are errors, not row-order guesses."""
    revisions, latest, issues = {}, {}, []
    for item in items:
        try:
            report = parse_report(item, tutors, zone, placeholder_policy, today)
        except Problem as exc:
            issue = {"source": item["source"], "row": item["row"], "code": exc.code}
            issues.append(issue)
            event("response_rejected", "ERROR", **issue)
            continue
        revisions[report.revision] = report
    groups = {}
    for report in revisions.values():
        groups.setdefault((report.tutor_id, report.week), []).append(report)
    for key, group in groups.items():
        group.sort(key=lambda r: r.submitted)
        newest = group[-1]
        tied = [r for r in group if r.submitted == newest.submitted]
        if len(tied) > 1:
            issue = {"source": newest.source, "row": newest.row, "code": "ambiguous_latest_submission"}
            issues.append(issue)
            event("response_rejected", "ERROR", **issue)
            continue
        latest[key] = newest
        event(
            "weekly_report_selected",
            tutor_ref=newest.tutor_id,
            week=str(newest.week),
            revision=newest.revision,
            source=newest.source,
            row=newest.row,
            versions=len(group),
            inferred_from=newest.inferred_from,
        )
    return list(revisions.values()), latest, issues
