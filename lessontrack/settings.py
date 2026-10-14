"""Runtime configuration. Set private values through environment variables or Actions secrets."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TUTOR_INFO_CSV_URL = os.getenv("TUTOR_INFO_CSV_URL", "")
RESPONSE_CSV_URL = os.getenv("RESPONSE_CSV_URL", "")
REPRESENTATIVE_CSV_URL = os.getenv("REPRESENTATIVE_CSV_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
MANAGEMENT_EMAILS = [
    address.strip() for address in os.getenv("MANAGEMENT_EMAILS", "").split(",") if address.strip()
]

MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
RESPONSE_TAB = os.getenv("RESPONSE_TAB", "Form Responses 1")
STATE_TAB = os.getenv("STATE_TAB", "LessonTrack Events")
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "UTC")
PLACEHOLDER_POLICY = "submission_week"
FORM_URL = os.getenv("FORM_URL", "")
DRIVE_FOLDER_URL = os.getenv("DRIVE_FOLDER_URL", "")
