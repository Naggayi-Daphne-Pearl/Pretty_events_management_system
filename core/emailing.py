import logging
import smtplib
from functools import wraps

from anymail.exceptions import AnymailError
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


def email_enabled_required(view_func):
    """
    Guard for views that send email. While EMAIL_ENABLED is off the buttons are hidden,
    but an old link or bookmark could still reach the view: send the visitor back where
    they came from with a clear note instead of a form that can only fail.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if settings.EMAIL_ENABLED:
            return view_func(request, *args, **kwargs)
        messages.info(request, 'Sending email from the system isn\'t switched on yet. '
                               'Ask your administrator; in the meantime, download the PDF or use WhatsApp.')
        back = request.META.get('HTTP_REFERER', '')
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}) and back != request.build_absolute_uri():
            return redirect(back)
        return redirect('login' if not request.user.is_authenticated else 'dashboard')
    return _wrapped


def send_plain_email(*, to_email, subject, body):
    """Plain-text email (invites, notices). Returns True on success; failures are logged."""
    try:
        EmailMessage(subject=subject, body=body, to=[to_email]).send()
    except (smtplib.SMTPException, OSError, AnymailError):
        logger.exception('Sending "%s" to %s failed', subject, to_email)
        return False
    return True


def send_pdf_email(*, to_email, subject, body, pdf_bytes, filename):
    """Send a plain-text email with an optional PDF attachment.

    Returns True on success, False if sending failed (bad SMTP creds, network,
    mail server unreachable within EMAIL_TIMEOUT, or the Brevo API refusing it,
    e.g. an unverified sender) so callers
    can show a friendly message instead of a 500. The real cause is logged.
    """
    email = EmailMessage(subject=subject, body=body, to=[to_email])
    if pdf_bytes:
        email.attach(filename, pdf_bytes, 'application/pdf')
    try:
        email.send()
    except (smtplib.SMTPException, OSError, AnymailError):
        logger.exception('Sending "%s" to %s failed', subject, to_email)
        return False
    return True
