"""SMTP-first delivery with explicit accepted, rejected and uncertain outcomes."""

import base64
from email.mime.text import MIMEText
import os
import smtplib
import ssl
from uuid import uuid4

from . import settings
from .diagnostics import Problem, event, error_details, reference, stage
from .reports import digest, valid_email


def get_app_password():
    return os.getenv("GMAIL_APP_PASSWORD")


def message(recipient, subject, body, delivery_id):
    if not valid_email(settings.SENDER_EMAIL) or not valid_email(recipient) or "\n" in subject or "\r" in subject:
        raise Problem("invalid_mail_envelope")
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"], msg["To"], msg["Subject"] = settings.SENDER_EMAIL, recipient, subject
    msg["Message-ID"] = f"<{delivery_id}@english2success.com>"
    return msg


def smtp_send(msg, smtp_factory=smtplib.SMTP):
    server, sending, accepted = None, False, False
    try:
        password = get_app_password()
        if not password:
            raise Problem("smtp_password_missing")
        server = smtp_factory(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=40)
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        server.login(settings.SENDER_EMAIL, password)
        sending = True
        refused = server.sendmail(settings.SENDER_EMAIL, [msg["To"]], msg.as_string())
        if refused:
            return "rejected"
        accepted = True
        event("smtp_accepted", recipient_ref=reference(msg["To"]))
        return "accepted"
    except smtplib.SMTPAuthenticationError as exc:
        event("smtp_authentication_failed", "ERROR", **error_details(exc))
        return "auth_failed"
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
        event("smtp_rejected", "ERROR", **error_details(exc))
        return "rejected"
    except Exception as exc:
        if isinstance(exc, Problem) and exc.code == "smtp_password_missing":
            event("smtp_authentication_failed", "ERROR", **error_details(exc))
            return "auth_failed"
        outcome = "uncertain" if sending else "rejected"
        event("smtp_" + outcome, "ERROR", **error_details(exc))
        return outcome
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception as exc:
                event("smtp_cleanup_failed", "WARNING", accepted=accepted, **error_details(exc))
                try:
                    server.close()
                except Exception:
                    pass


def oauth_send(msg):
    """Refresh existing credentials automatically; never start an interactive browser."""
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google_auth_httplib2 import AuthorizedHttp
    import httplib2

    sending = False
    try:
        path = settings.ROOT / "gmail_token.json"
        if os.getenv("GMAIL_TOKEN_FILE"):
            from pathlib import Path

            path = Path(os.environ["GMAIL_TOKEN_FILE"])
        creds = Credentials.from_authorized_user_file(
            str(path), ["https://www.googleapis.com/auth/gmail.send"]
        )
        if not creds.valid:
            if not creds.refresh_token:
                raise Problem("gmail_refresh_token_missing")
            with stage("gmail_token_refresh"):
                creds.refresh(Request())
                temporary = path.with_name(".gmail-token-" + uuid4().hex)
                try:
                    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(creds.to_json())
                    os.replace(temporary, path)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        service = build(
            "gmail", "v1", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=40)), cache_discovery=False
        )
        sending = True
        result = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()})
            .execute(num_retries=0)
        )
        event("gmail_accepted", recipient_ref=reference(msg["To"]), provider_message_id=result.get("id", ""))
        return "accepted"
    except (RefreshError, FileNotFoundError) as exc:
        event("gmail_authentication_failed", "ERROR", **error_details(exc))
        return "auth_failed"
    except HttpError as exc:
        status = int(exc.resp.status)
        event("gmail_failed", "ERROR", http_status=status)
        return "rejected" if 400 <= status < 500 else ("uncertain" if sending else "rejected")
    except Exception as exc:
        event("gmail_failed", "ERROR", **error_details(exc))
        return "uncertain" if sending else "rejected"


class DeliverySession:
    """Do not repeat known credential failures for every recipient in a batch."""

    def __init__(self):
        self.smtp_available = True
        self.oauth_available = True

    def __call__(self, msg):
        outcome = smtp_send(msg) if self.smtp_available else "auth_failed"
        if outcome == "auth_failed":
            self.smtp_available = False
        if outcome in {"accepted", "uncertain"}:
            return outcome
        if self.oauth_available:
            event("mail_fallback", "WARNING", transport="gmail_oauth")
            outcome = oauth_send(msg)
            if outcome == "auth_failed":
                self.oauth_available = False
        return "rejected" if outcome == "auth_failed" else outcome


def transport(msg):
    return DeliverySession()(msg)


def deliver(recipient, subject, body, journal, sender=transport):
    delivery_id = digest([recipient.lower(), subject, body])
    previous = journal.latest("delivery").get(delivery_id, {})
    if previous.get("status") == "accepted":
        event("delivery_skipped_accepted", delivery_id=delivery_id)
        return
    if previous.get("status") in {"pending", "uncertain"}:
        event("delivery_needs_review", "ERROR", delivery_id=delivery_id)
        raise Problem("delivery_acceptance_uncertain")
    msg = message(recipient, subject, body, delivery_id)
    attempt_id = uuid4().hex
    # Durable intent before external side effect. A crash leaves pending, never a blind retry.
    journal.append(
        "delivery",
        delivery_id,
        {"status": "pending", "attempt_id": attempt_id, "recipient_ref": reference(recipient)},
    )
    with stage("mail_delivery", delivery_id=delivery_id, recipient_ref=reference(recipient)):
        try:
            outcome = sender(msg)
        except Exception as exc:
            event("mail_transport_exception", "ERROR", **error_details(exc))
            outcome = "uncertain"
        if outcome not in {"accepted", "rejected", "uncertain"}:
            outcome = "uncertain"
        journal.append(
            "delivery",
            delivery_id,
            {"status": outcome, "attempt_id": attempt_id, "recipient_ref": reference(recipient)},
        )
        event("delivery_result", delivery_id=delivery_id, status=outcome)
        if outcome != "accepted":
            raise Problem("mail_" + outcome)
