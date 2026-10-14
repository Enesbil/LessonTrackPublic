import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from lessontrack import reports as r
from lessontrack.jobs import calculate_totals


def roster():
    return r.load_roster(
        [
            {
                "row": 2,
                "source": "roster",
                "values": {
                    "Tutor Name": "Tutor A",
                    "Tutor School": "School A",
                    "Email": "a@example.com",
                    "Total Hours": "10",
                    "Last Processed Timestamp": "2026-06-28 12:00:00",
                },
            }
        ]
    )


def response(timestamp="9/27/2026 14:00:00", class_date="9/25/2026", hours="1", taught="Yes", row=2):
    return {
        "source": "responses",
        "row": row,
        "values": {
            "Timestamp": timestamp,
            r.NAME: "Tutor A",
            r.TAUGHT: taught,
            r.HOURS: hours,
            r.CLASS_DATE: class_date,
            r.ACTIVITIES: "Practiced reading.",
            r.PLANS: "Practice conversation.",
            r.ISSUES: "No Issues",
            "Email Address": "a@example.com",
        },
    }


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.network = patch(
            "socket.socket.connect", side_effect=AssertionError("Network forbidden in tests")
        )
        self.network.start()
        self.addCleanup(self.network.stop)
        self.tutors = roster()
        self.tid = self.tutors["Tutor A"].id

    def select(self, items):
        return r.select_reports(items, self.tutors, placeholder_policy="submission_week")

    def test_latest_replaces_same_week_and_recalculates_delta(self):
        first = response(hours="2")
        correction = response(timestamp="9/28/2026 12:00:00", hours="3", row=3)
        _, old, _ = self.select([first])
        revisions, latest, issues = self.select([first, correction])
        baseline = {"start_week": "2026-06-29", "hours": {self.tid: "10"}}
        self.assertFalse(issues)
        self.assertEqual(len(revisions), 2)
        self.assertEqual(calculate_totals(old, self.tutors, baseline)[self.tid], Decimal(12))
        self.assertEqual(calculate_totals(latest, self.tutors, baseline)[self.tid], Decimal(13))

    def test_late_previous_week_does_not_replace_current_week(self):
        old = response("8/7/2026 12:00:00", "8/2/2026")
        current = response("8/9/2026 12:00:00", "8/9/2026")
        _, latest, issues = self.select([old, current])
        self.assertFalse(issues)
        self.assertEqual(set(week for tid, week in latest), {date(2026, 7, 27), date(2026, 8, 3)})

    def test_input_order_and_rerun_do_not_change_result(self):
        first = response("9/9/2026 12:00:00", "9/8/2026")
        next_report = response("9/10/2026 12:00:00", "9/9/2026", "2")
        _, expected, _ = self.select([first, next_report])
        revisions, actual, issues = self.select([next_report, first, first, next_report])
        self.assertEqual(expected, actual)
        self.assertEqual(len(revisions), 2)
        self.assertFalse(issues)

    def test_both_placeholder_years_are_no_teaching_and_not_deduplicated_by_date(self):
        for placeholder in ("01/01/2025", "1/1/2026"):
            with self.subTest(placeholder=placeholder):
                first = response("9/20/2026 10:00:00", placeholder, "0", "No")
                second = response("9/27/2026 10:00:00", placeholder, "0", "No")
                _, latest, issues = self.select([first, second])
                self.assertEqual(len(latest), 2)
                self.assertFalse(issues)
                self.assertTrue(all(not x.taught and x.hours == 0 for x in latest.values()))

    def test_placeholder_conflict_is_rejected(self):
        _, _, issues = self.select([response(class_date="1/1/2026")])
        self.assertEqual(issues[0]["code"], "placeholder_with_teaching")

    def test_fractional_hours_preserved_exactly(self):
        _, latest, issues = self.select([response(hours="0.75")])
        self.assertFalse(issues)
        self.assertEqual(next(iter(latest.values())).hours, Decimal("0.75"))

    def test_nonfinite_negative_and_text_hours_rejected(self):
        for value in ("nan", "Infinity", "-1", "1,5", "169"):
            with self.subTest(value=value):
                _, _, issues = self.select([response(hours=value)])
                self.assertEqual(issues[0]["code"], "invalid_hours")

    def test_no_with_positive_hours_and_yes_zero_rejected(self):
        for taught, hours in [("No", "1"), ("Yes", "0")]:
            _, _, issues = self.select([response(taught=taught, hours=hours)])
            self.assertEqual(issues[0]["code"], "conflicting_hours_and_taught")

    def test_tied_latest_timestamps_are_not_guessed(self):
        a, b = response(timestamp="9/27/2026"), response(timestamp="9/27/2026", hours="2")
        revisions, latest, issues = self.select([a, b])
        self.assertEqual(len(revisions), 2)
        self.assertFalse(latest)
        self.assertEqual(issues[0]["code"], "ambiguous_latest_submission")

    def test_earlier_tie_does_not_block_unambiguous_later_correction(self):
        rows = [response(timestamp="9/27/2026", hours=str(h)) for h in (1, 2)]
        rows.append(response(timestamp="9/28/2026 12:00:00", hours="3"))
        _, latest, issues = self.select(rows)
        self.assertFalse(issues)
        self.assertEqual(next(iter(latest.values())).hours, 3)

    def test_sparse_archive_metadata_is_not_a_tutor(self):
        headers, rows = r.rows_from_values(
            [["Timestamp", "Name"], ["", ""], ["9/27/2026", "Tutor A"], ["Archive created on:", "9/28/2026"]],
            "source",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row"], 3)

    def test_duplicate_headers_fail(self):
        with self.assertRaisesRegex(r.Problem, "sheet_invalid_headers"):
            r.rows_from_values([["Email", " email "]], "source")

    def test_collected_email_mismatch_is_not_silent_reassignment(self):
        item = response()
        item["values"]["Email Address"] = "alternate@example.com"
        _, latest, issues = self.select([item])
        self.assertFalse(issues)
        self.assertEqual(next(iter(latest.values())).tutor_id, self.tid)

    def test_unknown_tutor_rejected(self):
        item = response()
        item["values"][r.NAME] = "Unknown"
        _, _, issues = self.select([item])
        self.assertEqual(issues[0]["code"], "unknown_tutor")

    def test_serial_dates_keep_time_precision(self):
        stamp = r.parse_datetime(46201.75)
        self.assertEqual(stamp.hour, 18)

    def test_timezones_and_year_boundary(self):
        self.assertEqual(r.week_of(date(2026, 1, 1)), date(2025, 12, 29))
        self.assertIsNotNone(r.parse_datetime("2026-09-27T23:30:00-04:00").tzinfo)
        with self.assertRaisesRegex(r.Problem, "ambiguous_local_timestamp"):
            r.parse_datetime("2026-11-01T01:30:00", "America/New_York")

    def test_opening_balance_cannot_silently_swallow_earlier_correction(self):
        _, latest, _ = self.select([response()])
        with self.assertRaisesRegex(r.Problem, "report_predates_opening_balance"):
            calculate_totals(latest, self.tutors, {"start_week": "2026-09-28", "hours": {self.tid: "10"}})

    def test_explicitly_reconciled_earlier_revision_is_not_counted_twice(self):
        _, latest, _ = self.select([response()])
        report = next(iter(latest.values()))
        baseline = {
            "start_week": "2026-09-28",
            "hours": {self.tid: "10"},
            "covered_revisions": [report.revision],
        }
        self.assertEqual(calculate_totals(latest, self.tutors, baseline)[self.tid], 10)
        _, corrected, _ = self.select([response(hours="2")])
        with self.assertRaisesRegex(r.Problem, "report_predates_opening_balance"):
            calculate_totals(corrected, self.tutors, baseline)


if __name__ == "__main__":
    unittest.main()
