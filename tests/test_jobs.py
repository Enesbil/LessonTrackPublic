import contextlib
from datetime import date
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lessontrack import jobs, mail, settings
from lessontrack.diagnostics import Problem
from lessontrack.reports import CLASS_DATE, HOURS, NAME, TAUGHT
from lessontrack.storage import Journal
from tests.test_reports import response, roster


class FakeSheets:
    def __init__(self, reports=None):
        self.reports = [response()] if reports is None else reports
        self.state = Journal()
        self.writes = 0
        self.write_journal_opens = 0

    def read(self, url, title=None):
        if url == settings.TUTOR_INFO_CSV_URL:
            values = {
                "Tutor Name": "Tutor A",
                "Tutor School": "School A",
                "Email": "a@example.com",
                "Total Hours": "10",
                "Last Processed Timestamp": "2026-06-28 12:00:00",
            }
            return list(values), [{"source": "roster", "row": 2, "values": values}]
        if url == settings.REPRESENTATIVE_CSV_URL:
            return ["Representative Name", "Representative Email", "School"], [
                {
                    "source": "reps",
                    "row": 2,
                    "values": {
                        "Representative Name": "Rep",
                        "Representative Email": "rep@example.com",
                        "School": "School A",
                    },
                }
            ]
        if url == settings.RESPONSE_CSV_URL:
            return ["Timestamp", NAME, TAUGHT, HOURS, CLASS_DATE], self.reports
        raise AssertionError("Unexpected sheet")

    def response_timezone(self):
        return "UTC"

    def journal(self, writable=False):
        self.write_journal_opens += int(writable)
        return self.state

    def update_roster(self, tutors, latest, totals, week):
        self.writes += 1
        self.totals = totals


class JobTests(unittest.TestCase):
    def setUp(self):
        configured = patch.multiple(
            settings,
            TUTOR_INFO_CSV_URL="https://example.invalid/roster",
            RESPONSE_CSV_URL="https://example.invalid/responses",
            REPRESENTATIVE_CSV_URL="https://example.invalid/representatives",
            SENDER_EMAIL="sender@example.com",
            OPENAI_API_KEY="test-key",
            MANAGEMENT_EMAILS=["manager@example.com", "director@example.com"],
            FORM_URL="https://example.invalid/form",
            DRIVE_FOLDER_URL="https://example.invalid/drive",
        )
        configured.start()
        self.addCleanup(configured.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in tests"))
        network.start()
        self.addCleanup(network.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.baseline = Path(self.temp.name) / "baseline.json"
        self.baseline.write_text(
            json.dumps({"start_week": "2026-06-29", "hours": {roster()["Tutor A"].id: "10"}})
        )
        self.week = date(2026, 9, 21)

    def test_preview_never_writes_sends_or_calls_ai(self):
        sheets = FakeSheets()
        with (
            patch.object(jobs, "summarize", side_effect=AssertionError("AI forbidden")),
            patch.object(jobs, "deliver", side_effect=AssertionError("Mail forbidden")),
        ):
            result = jobs.report_job(self.week, sheets=sheets)
        self.assertEqual(result["revisions"], 1)
        self.assertEqual(sheets.writes, 0)
        self.assertEqual(sheets.write_journal_opens, 0)
        self.assertFalse(sheets.state.entries)

    def test_invalid_response_blocks_all_mutation(self):
        sheets = FakeSheets([response(taught="No", hours="1")])
        with self.assertRaisesRegex(Problem, "invalid_responses_block_apply"):
            jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
        self.assertEqual(sheets.writes, 0)
        self.assertEqual(sheets.write_journal_opens, 0)

    def test_missing_opening_balance_does_not_reset_totals(self):
        sheets = FakeSheets()
        with self.assertRaisesRegex(Problem, "reviewed_opening_balance_required"):
            jobs.report_job(self.week, apply=True, sheets=sheets)
        self.assertFalse(sheets.state.entries)
        self.assertEqual(sheets.writes, 0)

    def test_missing_api_key_blocks_apply_before_writes(self):
        sheets = FakeSheets()
        with patch.object(settings, "OPENAI_API_KEY", ""):
            with self.assertRaisesRegex(Problem, "openai_api_key_missing"):
                jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
        self.assertFalse(sheets.state.entries)
        self.assertEqual(sheets.writes, 0)

    def test_new_tutor_zero_opening_balance_is_durable(self):
        from dataclasses import replace
        from decimal import Decimal

        tutors = {
            "New Tutor": replace(
                roster()["Tutor A"], id="new", name="New Tutor", total_hours=Decimal(0), checkpoint=""
            )
        }
        baseline = {"start_week": "2026-06-29", "hours": {"old": "10"}}
        journal = Journal()
        extended, additions = jobs.extend_opening_balance(baseline, journal, tutors)
        self.assertEqual(extended["hours"]["new"], "0")
        journal.append_many(additions)
        tutors["New Tutor"] = replace(tutors["New Tutor"], total_hours=Decimal(2), checkpoint="2026-09-27")
        extended, additions = jobs.extend_opening_balance(baseline, journal, tutors)
        self.assertEqual(extended["hours"]["new"], "0")
        self.assertFalse(additions)

    def test_failure_reading_representatives_prevents_writes(self):
        sheets = FakeSheets()
        original = sheets.read

        def read(url, title=None):
            if url == settings.REPRESENTATIVE_CSV_URL:
                raise OSError("provider unavailable")
            return original(url, title)

        sheets.read = read
        with self.assertRaises(OSError):
            jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
        self.assertFalse(sheets.state.entries)

    def test_end_to_end_rerun_preserves_totals_and_skips_accepted_mail(self):
        sheets = FakeSheets()
        with (
            patch.object(jobs, "summarize", return_value="Reading and conversation."),
            patch.object(mail, "smtp_send", return_value="accepted") as sender,
        ):
            jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
            self.assertEqual(sender.call_count, 3)
            totals = dict(sheets.totals)
            jobs.report_job(self.week, apply=True, sheets=sheets)
            self.assertEqual(sender.call_count, 3)
            self.assertEqual(sheets.totals, totals)
            self.assertEqual(next(iter(totals.values())), 11)
            self.assertEqual(len(sheets.state.latest("response")), 1)

    def test_correction_and_late_week_are_persisted_separately(self):
        sheets = FakeSheets()
        with (
            patch.object(jobs, "summarize", return_value="Summary"),
            patch.object(mail, "smtp_send", return_value="accepted"),
        ):
            jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
            sheets.reports = [
                response("9/28/2026 12:00:00", "9/25/2026", "2"),
                response("9/28/2026 13:00:00", "9/18/2026", "3"),
            ]
            jobs.report_job(self.week, apply=True, sheets=sheets)
        self.assertEqual(next(iter(sheets.totals.values())), 15)
        self.assertEqual(len(sheets.state.latest("response")), 3)

    def test_ai_failure_delivers_labeled_fallback_but_fails_run(self):
        sheets = FakeSheets()
        with (
            patch.object(jobs, "summarize", side_effect=Problem("ai_http_503")),
            patch.object(jobs, "deliver") as sender,
        ):
            with self.assertRaisesRegex(Problem, "report_run_incomplete"):
                jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
        self.assertEqual(sender.call_count, 3)
        self.assertIn("AI summary unavailable", sender.call_args_list[0].args[2])

    def test_fresh_header_only_response_sheet_is_valid(self):
        result = jobs.report_job(self.week, sheets=FakeSheets([]))
        self.assertEqual(result["revisions"], 0)
        self.assertFalse(result["issues"])

    def test_original_monday_tutor_email_wording(self):
        sheets = FakeSheets([])
        with patch.object(jobs, "deliver") as deliver:
            jobs.reminder_job(self.week, apply=True, sheets=sheets)
        recipient, subject, body = deliver.call_args.args[:3]
        self.assertEqual(recipient, "a@example.com")
        self.assertEqual(subject, "Important: Please Submit Your Weekly Report")
        self.assertTrue(body.startswith("Dear Tutor,\n\nHere is the Google Forms link"))
        self.assertIn("Please submit it before Sunday 22:00 GMT SHARP", body)
        self.assertIn("Thank you so much for your time and dedication!", body)
        self.assertTrue(body.endswith("P.S. This is an automated email, but you can reply to it if you have any questions."))

    def test_original_sunday_report_email_wording(self):
        sheets = FakeSheets([])
        with (patch.object(jobs, "deliver") as deliver, patch.object(jobs, "summarize")):
            jobs.report_job(self.week, apply=True, sheets=sheets, baseline_file=self.baseline)
        rep = deliver.call_args_list[0].args
        self.assertEqual(rep[1], "E2S Weekly Report - School A")
        self.assertTrue(rep[2].startswith("Dear Rep,\n\nHere is this week's summary for School A tutors:\n\n"))
        self.assertIn("Tutor A (Weekly Hours: 0, Submissions: 0, Lessons: 0, Total Hours: 10): No response this week", rep[2])
        self.assertTrue(rep[2].endswith("\n\nBest regards,\nEnglish2Success Team"))
        management = deliver.call_args_list[1].args
        self.assertEqual(management[1], "E2S Complete Weekly Report - All Schools")
        self.assertTrue(management[2].startswith("Weekly Tutor Report Summary\n\nOverall Statistics:\n"))
        self.assertIn("\n=== School A ===\n", management[2])

    def test_imports_have_no_operational_side_effects(self):
        with (
            patch.object(jobs, "report_job", side_effect=AssertionError("Job executed on import")),
            patch.object(jobs, "reminder_job", side_effect=AssertionError("Job executed on import")),
        ):
            for module in ("Monday", "Sunday", "Email", "ai_summary", "test_email", "test_sunday_no_email"):
                importlib.reload(importlib.import_module(module))

    def test_cli_failure_is_nonzero_and_has_diagnostics(self):
        from lessontrack.cli import main

        with (
            patch("lessontrack.cli.report_job", side_effect=OSError("secret provider error")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = main(["report", "--log-dir", self.temp.name])
        self.assertEqual(code, 1)
        summaries = list(Path(self.temp.name).glob("*/summary.json"))
        self.assertEqual(len(summaries), 1)
        self.assertEqual(json.loads(summaries[0].read_text())["status"], "failed")

    def test_representative_email_header_is_not_misread_as_name(self):
        _, rows = FakeSheets().read(settings.REPRESENTATIVE_CSV_URL)
        result = jobs.representatives(rows)
        self.assertEqual(result[0], {"name": "Rep", "school": "School A", "email": "rep@example.com"})


if __name__ == "__main__":
    unittest.main()
