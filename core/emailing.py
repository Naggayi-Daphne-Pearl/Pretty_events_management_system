import smtplib

from django.core.mail import EmailMessage


def send_pdf_email(*, to_email, subject, body, pdf_bytes, filename):
    """Send a plain-text email with an optional PDF attachment.

    Returns True on success, False if sending failed (e.g. bad SMTP creds/
    network) so callers can show a friendly message instead of a 500.
    """
    email = EmailMessage(subject=subject, body=body, to=[to_email])
    if pdf_bytes:
        email.attach(filename, pdf_bytes, 'application/pdf')
    try:
        email.send()
    except (smtplib.SMTPException, OSError):
        return False
    return True
