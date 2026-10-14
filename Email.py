"""Compatibility entrypoints. Operational implementations live in lessontrack/."""

from uuid import uuid4

from lessontrack import settings
from lessontrack.cli import main
from lessontrack.diagnostics import Problem, Run
from lessontrack.mail import get_app_password, message, transport

__all__ = [
    "get_app_password",
    "send_email",
    "test_email_system",
    "send_weekly_reports",
    "Monday_email_to_tutors",
]


def send_email(recipient, subject, body, is_failure_notification=False):
    """Explicit one-off send for the pairing script/manual check. Failures raise."""
    with Run("manual_email", "apply", settings.ROOT / ".lessontrack/runs"):
        outcome = transport(message(recipient, subject, body, uuid4().hex))
        if outcome != "accepted":
            raise Problem("mail_" + outcome)
    return True


def test_email_system(test_email=None):
    return send_email(
        test_email or settings.SENDER_EMAIL,
        "English2Success: Email System Test",
        "Hello,\n\n"
        "This is a test email from the English2Success reporting system.\n\n"
        "If you're receiving this email, the email sending functionality is working correctly.\n\n"
        "Best regards,\n"
        "English2Success Automated System",
    )


def send_weekly_reports(apply=False):
    return main(["report"] + (["--apply"] if apply else []))


def Monday_email_to_tutors(apply=False):
    return main(["remind"] + (["--apply"] if apply else []))
