import logging
import smtplib

from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def send_plain_email(*, to_email, subject, body):
    """Plain-text email (invites, notices). Returns True on success; failures are logged."""
    try:
        EmailMessage(subject=subject, body=body, to=[to_email]).send()
    except (smtplib.SMTPException, OSError):
        logger.exception('Sending "%s" to %s failed', subject, to_email)
        return False
    return True


def send_pdf_email(*, to_email, subject, body, pdf_bytes, filename):
    """Send a plain-text email with an optional PDF attachment.

    Returns True on success, False if sending failed (e.g. bad SMTP creds,
    network, or the mail server unreachable within EMAIL_TIMEOUT) so callers
    can show a friendly message instead of a 500. The real cause is logged.
    """
    email = EmailMessage(subject=subject, body=body, to=[to_email])
    if pdf_bytes:
        email.attach(filename, pdf_bytes, 'application/pdf')
    try:
        email.send()
    except (smtplib.SMTPException, OSError):
        logger.exception('Sending "%s" to %s failed', subject, to_email)
        return False
    return True
