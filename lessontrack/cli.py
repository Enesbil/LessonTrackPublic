import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import settings
from .diagnostics import Problem, Run
from .jobs import report_job, reminder_job
from .reports import week_of


@contextmanager
def writer_lock():
    """Local processes share this lock; GitHub jobs share the workflow concurrency group."""
    import fcntl

    path = settings.ROOT / ".lessontrack" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Problem("another_local_writer_is_running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description="LessonTrack: read-only preview unless --apply is provided.")
    parser.add_argument("job", choices=["report", "remind"])
    parser.add_argument(
        "--apply", action="store_true", help="Persist state and send email; never enabled in a CSV preview."
    )
    parser.add_argument(
        "--week", type=date.fromisoformat, help="Any date within the reporting week (YYYY-MM-DD)."
    )
    parser.add_argument("--roster-csv", type=Path)
    parser.add_argument("--responses-csv", type=Path, nargs="+", default=[])
    parser.add_argument(
        "--baseline-json", type=Path, help="Reviewed opening balances; see docs/OPERATIONS.md."
    )
    parser.add_argument(
        "--output", type=Path, help="Optional private preview text; excluded from diagnostic artifacts."
    )
    parser.add_argument(
        "--include-archives", action="store_true", help="Read archived response tabs for reconciliation."
    )
    parser.add_argument("--campaign", choices=["monday", "friday"], default="monday")
    parser.add_argument("--log-dir", type=Path, default=settings.ROOT / ".lessontrack/runs")
    args = parser.parse_args(argv)
    today = datetime.now(ZoneInfo(settings.REPORT_TIMEZONE)).date()
    default_day = today - timedelta(days=(today.weekday() + 1) % 7) if args.job == "report" else today
    report_week = week_of(args.week or default_day)
    try:
        with Run(args.job, "apply" if args.apply else "preview", args.log_dir):
            if bool(args.roster_csv) != bool(args.responses_csv):
                raise Problem("provide_both_roster_and_response_csvs")
            if args.job == "remind" and (
                args.roster_csv or args.output or args.baseline_json or args.include_archives
            ):
                raise Problem("unsupported_reminder_arguments")
            if args.apply and args.output:
                raise Problem("preview_output_not_available_in_apply")
            if args.output and args.output.resolve().is_relative_to(args.log_dir.resolve()):
                raise Problem("private_preview_must_be_outside_diagnostics")

            def execute():
                if args.job == "report":
                    result = report_job(
                        report_week,
                        args.apply,
                        args.roster_csv,
                        args.responses_csv,
                        args.baseline_json,
                        today=today,
                        output=args.output,
                        include_archives=args.include_archives,
                    )
                    if result.get("issues"):
                        raise Problem("preview_contains_invalid_responses")
                else:
                    reminder_job(report_week, args.apply, campaign=args.campaign)

            if args.apply:
                with writer_lock():
                    execute()
            else:
                execute()
        return 0
    except Exception as exc:
        # Run logged safe stack frames and codes. Do not print secret-bearing exception messages.
        import json
        import sys
        from .diagnostics import error_details

        print(json.dumps({"event": "command_failed", **error_details(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
