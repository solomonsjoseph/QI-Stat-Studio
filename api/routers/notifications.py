import logging

logger = logging.getLogger(__name__)


def send_deadline_reminder(email: str, deadline: str, project_title: str) -> None:
    # ponytail: SMTP stub — wire smtplib in v1.1 (Month 7+)
    logger.info("stub: deadline reminder to %s for '%s' due %s", email, deadline, project_title)
