"""Email alerts: notifications of the kinds in EMAIL_ALERT_KINDS are also emailed to people who have an email
address in Settings > Users & Roles.

- With SMTP_HOST set, mail goes through that server (TLS when SMTP_TLS is true).
- Without it (local testing), each email is written as a .eml file to MAIL_OUTBOX_DIR, so it can be opened and
  checked, and nothing leaves the machine.
Sending runs in a background thread, so a slow mail server never slows a request down.
"""
import logging
import smtplib
import threading
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("pms.mail")
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def outbox_dir() -> Path:
    path = Path(settings.MAIL_OUTBOX_DIR)
    return path if path.is_absolute() else BACKEND_ROOT / path


def alert_kinds() -> set:
    return {k.strip() for k in settings.EMAIL_ALERT_KINDS.split(",") if k.strip()}


def _message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _deliver(msg: EmailMessage) -> None:
    try:
        if settings.SMTP_HOST:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
                if settings.SMTP_TLS:
                    smtp.starttls()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            folder = outbox_dir()
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.eml"
            (folder / name).write_bytes(bytes(msg))
    except Exception:  # noqa: BLE001 - an email problem must never break the action that caused it
        logger.exception("Could not send email to %s", msg["To"])


def send(to: str, subject: str, body: str, wait: bool = False) -> None:
    if not settings.EMAIL_ALERTS_ENABLED or not to:
        return
    msg = _message(to, subject[:200], body)
    if wait:
        _deliver(msg)
    else:
        threading.Thread(target=_deliver, args=(msg,), daemon=True).start()


def app_link(link: str | None) -> str:
    base = settings.APP_BASE_URL.rstrip("/")
    return f"{base}/appModules/projects/{link.lstrip('/')}" if link else f"{base}/appModules/projects/dashboard/"
