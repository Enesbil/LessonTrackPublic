"""Send tutor/student pairing notices from a private JSON file."""

import argparse
import json
from pathlib import Path

from Email import send_email
from lessontrack.reports import valid_email

REQUIRED = {"tutor_name", "tutor_email", "student_name", "student_email", "student_phone"}


def get_tutor_student_pairings(path):
    pairings = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(pairings, list):
        raise ValueError("Pairings file must contain a JSON list")
    for pairing in pairings:
        if not isinstance(pairing, dict) or not REQUIRED <= pairing.keys():
            raise ValueError("Each pairing needs tutor and student contact fields")
        if any(not isinstance(pairing[key], str) or not pairing[key].strip() for key in REQUIRED):
            raise ValueError("Pairing fields must be nonempty strings")
        if not valid_email(pairing["tutor_email"]) or not valid_email(pairing["student_email"]):
            raise ValueError("Pairing email address is invalid")
    return pairings


def create_pairing_email(tutor_name, student_name, student_email, student_phone):
    """
    Creates the email content for tutor pairing notification.
    """
    first_name = tutor_name.split()[0]

    email_body = f"""Dear {first_name},

Thank you for continuing with English2Success this summer semester.

You have been matched with the following student:

• Student Name: {student_name}
• Student Email: {student_email}
• Student Number: {student_phone}

If this is the same student you have been working with previously, please continue as usual. If this is a new student, please reach out to the student to introduce yourself and arrange your first meeting.

Please try contacting your student through both email and WhatsApp (using the phone number provided) to ensure they receive your message.

Please note that each week, you will receive a form to complete, where we will ask about the student's progress. It is important to fill out this form every week so we can continue to support your sessions effectively.

Additionally: Please make sure the student completes a Duolingo Practice Test this week. It is free, and very helpful for the student to get a sense of their current level, aswell as for us to measure their progress.

The link to the FreeDuolingo Practice Test is: https://englishtest.duolingo.com/quick

If you have any questions or encounter any difficulties in contacting the student, please let us know.

Thank you for your commitment to the program.

Best regards,
Enes
English2Success Team"""

    return email_body


def send_all_pairing_emails(pairings):
    failures = 0
    for pairing in pairings:
        body = create_pairing_email(
            pairing["tutor_name"], pairing["student_name"],
            pairing["student_email"], pairing["student_phone"]
        )
        try:
            send_email(pairing["tutor_email"], "English2Success: You've Been Matched with a Student", body)
        except Exception as exc:
            print(f"Delivery failed: {type(exc).__name__}; see LessonTrack diagnostics")
            failures += 1
    print(f"Pairings: {len(pairings)}; failures: {failures}")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview or send student pairings from a private JSON file.")
    parser.add_argument("--pairings-json", type=Path, required=True)
    parser.add_argument("--send", action="store_true", help="Send real pairing emails")
    args = parser.parse_args()
    pairings = get_tutor_student_pairings(args.pairings_json)
    if not args.send:
        parser.exit(message=f"Preview: {len(pairings)} pairings; no email sent. Use --send to deliver.\n")
    raise SystemExit(1 if send_all_pairing_emails(pairings) else 0)
