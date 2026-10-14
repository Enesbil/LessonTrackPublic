import contextlib
import io
import json
import smtplib
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from lessontrack import ai, mail, settings
from lessontrack.diagnostics import Problem, Run, stage
from lessontrack.storage import Journal, Sheets
from lessontrack.reports import parse_report
from tests.test_reports import response, roster


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        configured = patch.multiple(settings, SENDER_EMAIL="sender@example.com", OPENAI_API_KEY="test-key")
        configured.start()
        self.addCleanup(configured.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in tests"))
        network.start()
        self.addCleanup(network.stop)

    def msg(self):
        return mail.message("recipient@example.com", "Subject", "Body", "stable-id")

    def test_smtp_acceptance_survives_quit_failure(self):
        smtp = Mock()
        smtp.sendmail.return_value = {}
        smtp.quit.side_effect = OSError("connection closed")
        with patch.object(mail, "get_app_password", return_value="secret"):
            self.assertEqual(mail.smtp_send(self.msg(), Mock(return_value=smtp)), "accepted")
        smtp.close.assert_called_once()

    def test_connection_loss_during_data_is_uncertain(self):
        smtp = Mock()
        smtp.sendmail.side_effect = smtplib.SMTPServerDisconnected("unknown acceptance")
        with patch.object(mail, "get_app_password", return_value="secret"):
            self.assertEqual(mail.smtp_send(self.msg(), Mock(return_value=smtp)), "uncertain")

    def test_uncertain_smtp_never_falls_back(self):
        with (
            patch.object(mail, "smtp_send", return_value="uncertain"),
            patch.object(mail, "oauth_send") as oauth,
        ):
            self.assertEqual(mail.transport(self.msg()), "uncertain")
            oauth.assert_not_called()

    def test_confirmed_rejection_can_fall_back(self):
        with (
            patch.object(mail, "smtp_send", return_value="rejected"),
            patch.object(mail, "oauth_send", return_value="accepted") as oauth,
        ):
            self.assertEqual(mail.transport(self.msg()), "accepted")
            oauth.assert_called_once()

    def test_batch_does_not_repeat_known_authentication_failures(self):
        session = mail.DeliverySession()
        with (
            patch.object(mail, "smtp_send", return_value="auth_failed") as smtp,
            patch.object(mail, "oauth_send", return_value="auth_failed") as oauth,
        ):
            self.assertEqual(session(self.msg()), "rejected")
            self.assertEqual(session(self.msg()), "rejected")
        self.assertEqual(smtp.call_count, 1)
        self.assertEqual(oauth.call_count, 1)

    def test_sheets_reads_retry_503_but_writes_do_not(self):
        import gspread
        from google.auth.credentials import AnonymousCredentials
        from lessontrack.storage import make_client

        bad_response = Mock(status_code=503)
        bad_response.json.return_value = {
            "error": {"code": 503, "message": "temporary", "status": "UNAVAILABLE"}
        }
        error = gspread.exceptions.APIError(bad_response)
        for method, expected_calls in [("get", 2), ("post", 1)]:
            with (
                self.subTest(method=method),
                patch("lessontrack.storage.time.sleep"),
                patch(
                    "gspread.http_client.HTTPClient.request", side_effect=[error, Mock(status_code=200)]
                ) as request,
            ):
                client = make_client(AnonymousCredentials())
                if method == "get":
                    client.http_client.request(method, "https://example.invalid")
                else:
                    with self.assertRaises(gspread.exceptions.APIError):
                        client.http_client.request(method, "https://example.invalid")
                self.assertEqual(request.call_count, expected_calls)

    def test_journal_header_created_in_same_atomic_request_as_sheet(self):
        import gspread
        from lessontrack.storage import EVENT_HEADERS

        book, worksheet = Mock(), Mock()
        book.worksheet.side_effect = [gspread.WorksheetNotFound("journal"), worksheet]
        worksheet.get_all_values.return_value = [EVENT_HEADERS]
        sheets = Sheets(Mock())
        with patch.object(sheets, "book", return_value=book):
            journal = sheets.journal(writable=True)
        self.assertIs(journal.worksheet, worksheet)
        requests = book.batch_update.call_args.args[0]["requests"]
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            requests[0]["addSheet"]["properties"]["sheetId"], requests[1]["updateCells"]["range"]["sheetId"]
        )

    def test_ai_billing_quota_failure_is_not_retried(self):
        report = parse_report(response(), roster())
        response_mock = Mock(status_code=429, headers={})
        response_mock.json.return_value = {"error": {"code": "insufficient_quota", "message": "secret text"}}
        post = Mock(return_value=response_mock)
        with self.assertRaisesRegex(Problem, "ai_insufficient_quota"):
            ai.summarize(report, [report], Journal(), post=post)
        self.assertEqual(post.call_count, 1)

    def test_accepted_delivery_not_sent_twice_after_journal_reload(self):
        journal = Journal()
        sender = Mock(return_value="accepted")
        mail.deliver("a@example.com", "subject", "body", journal, sender)
        reloaded = Journal(journal.entries)
        mail.deliver("a@example.com", "subject", "body", reloaded, sender)
        self.assertEqual(sender.call_count, 1)

    def test_durable_pending_before_send(self):
        journal = Journal()

        def sender(msg):
            self.assertEqual(next(iter(journal.latest("delivery").values()))["status"], "pending")
            return "accepted"

        mail.deliver("a@example.com", "subject", "body", journal, sender)

    def test_crash_after_delivery_record_failure_cannot_blindly_resend(self):
        journal = Journal()
        original = journal.append

        def append(kind, key, payload):
            if payload.get("status") == "accepted":
                raise OSError("journal unavailable")
            return original(kind, key, payload)

        sender = Mock(return_value="accepted")
        with patch.object(journal, "append", side_effect=append):
            with self.assertRaises(OSError):
                mail.deliver("a@example.com", "subject", "body", journal, sender)
        with self.assertRaisesRegex(Problem, "delivery_acceptance_uncertain"):
            mail.deliver("a@example.com", "subject", "body", Journal(journal.entries), sender)
        self.assertEqual(sender.call_count, 1)

    def test_rejected_delivery_can_be_retried(self):
        journal = Journal()
        sender = Mock(side_effect=["rejected", "accepted"])
        with self.assertRaisesRegex(Problem, "mail_rejected"):
            mail.deliver("a@example.com", "subject", "body", journal, sender)
        mail.deliver("a@example.com", "subject", "body", journal, sender)
        self.assertEqual(sender.call_count, 2)

    def test_journal_append_timeout_does_not_claim_saved(self):
        worksheet = Mock()
        worksheet.append_rows.side_effect = requests.Timeout("unknown acceptance")
        journal = Journal(worksheet=worksheet)
        with self.assertRaises(requests.Timeout):
            journal.append("example", "key", {"value": 1})
        self.assertFalse(journal.entries)
        worksheet.append_rows.assert_called_once()

    def test_journal_deduplicates_reread_events(self):
        worksheet = Mock()
        journal = Journal(worksheet=worksheet)
        journal.append("response", "x", {"a": 1})
        journal.append("response", "x", {"a": 1})
        self.assertEqual(worksheet.append_rows.call_count, 1)

    def test_ai_truncated_refused_and_empty_not_cached_as_success(self):
        report = parse_report(response(), roster())
        choices = [
            {"finish_reason": "length", "message": {"content": "partial"}},
            {"finish_reason": "stop", "message": {"content": "", "refusal": "refused"}},
            {"finish_reason": "stop", "message": {"content": ""}},
        ]
        for choice in choices:
            with self.subTest(choice=choice):
                journal = Journal()
                http = Mock(status_code=200, headers={"x-request-id": "req-test"})
                http.json.return_value = {"choices": [choice]}
                with self.assertRaises(Problem):
                    ai.summarize(report, [report], journal, post=Mock(return_value=http))
                self.assertFalse(journal.latest("summary"))

    def test_ai_retries_transient_errors_and_records_request_id(self):
        report = parse_report(response(), roster())
        failed = Mock(status_code=429, headers={"x-request-id": "req-failed"})
        okay = Mock(status_code=200, headers={"x-request-id": "req-okay"})
        okay.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "Summary"}}]}
        post, sleep, journal = Mock(side_effect=[failed, okay]), Mock(), Journal()
        self.assertEqual(ai.summarize(report, [report], journal, post, sleep), "Summary")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(next(iter(journal.latest("summary").values()))["request_id"], "req-okay")
        self.assertEqual(ai.summarize(report, [report], journal, post, sleep), "Summary")
        self.assertEqual(post.call_count, 2)

    def test_ai_credentials_failure_not_retried_and_identity_fields_not_sent(self):
        report = parse_report(response(), roster())
        post = Mock(return_value=Mock(status_code=401, headers={}))
        with self.assertRaisesRegex(Problem, "ai_http_401"):
            ai.summarize(report, [report], Journal(), post=post)
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertIn("max_completion_tokens", payload)
        self.assertNotIn("max_tokens", payload)
        user_text = payload["messages"][1]["content"]
        self.assertNotIn("Tutor A", user_text)
        self.assertNotIn("a@example.com", user_text)

    def test_trace_has_stack_and_run_id_but_no_exception_message(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                with Run("test", "preview", temp) as run:
                    with stage("provider"):
                        raise RuntimeError("secret-key private@example.com private narrative")
            text = (run.directory / "events.jsonl").read_text()
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertTrue(all(x["run_id"] == run.id for x in rows))
            self.assertNotIn("secret-key", text)
            self.assertNotIn("private@example.com", text)
            self.assertTrue(next(x for x in rows if x["event"] == "stage_failed")["trace"])
            self.assertEqual(json.loads((run.directory / "summary.json").read_text())["status"], "failed")

    def test_gid_query_does_not_fall_back_to_first_sheet(self):
        client, book = Mock(), Mock()
        client.open_by_key.return_value = book
        book.get_worksheet_by_id.side_effect = Problem("missing")
        with self.assertRaises(Problem):
            Sheets(client).worksheet("https://docs.google.com/spreadsheets/d/test?gid=123")
        book.get_worksheet.assert_not_called()

    def test_safe_roster_write_preserves_admin_fields(self):
        tutors = roster()
        sheet = Mock(col_count=20)
        sheet.get_all_values.return_value = [
            ["Tutor Name", "Email", "Tutor School", "Total Hours", "Tutee Name", "Custom Notes"],
            ["Tutor A", "a@example.com", "School A", "10", "Keep Student", "Keep Notes"],
        ]
        sheets = Sheets(Mock())
        with patch.object(sheets, "worksheet", return_value=sheet):
            from datetime import date
            from decimal import Decimal

            sheets.update_roster(tutors, {}, {tutors["Tutor A"].id: Decimal(10)}, date(2026, 9, 21))
        sheet.clear.assert_not_called()
        updates = sheet.batch_update.call_args.args[0]
        changed = {u["range"] for u in updates}
        self.assertNotIn("E2", changed)
        self.assertNotIn("F2", changed)
        self.assertTrue(sheet.batch_update.call_args.kwargs["raw"])


if __name__ == "__main__":
    unittest.main()
