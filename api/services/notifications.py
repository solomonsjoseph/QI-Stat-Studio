from __future__ import annotations

import smtplib
from email.message import EmailMessage

from api.config import settings


def _send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.from_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_port == 587:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(message)


def send_share_invite(email: str, project_title: str, share_url: str, deadline: str | None = None) -> None:
    deadline_line = f"\nReview deadline: {deadline}" if deadline else ""
    body = (
        f"You have been invited to review a QI Stat Studio project.\n\n"
        f"Project: {project_title}\n"
        f"Review link: {share_url}"
        f"{deadline_line}\n\n"
        "Use the link above to view the analysis package, download reports, and leave mentor feedback."
    )
    _send_email(email, f"Mentor review requested: {project_title}", body)


def send_deadline_reminder(email: str, deadline: str, project_title: str, share_url: str) -> None:
    body = (
        f"This is a reminder that mentor feedback is due soon.\n\n"
        f"Project: {project_title}\n"
        f"Deadline: {deadline}\n"
        f"Review link: {share_url}\n\n"
        "Please review the project and leave comments before the deadline."
    )
    _send_email(email, f"Reminder: feedback due for {project_title}", body)
