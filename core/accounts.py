from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .emailing import send_plain_email


def _set_password_link(request, user, url_name):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return request.build_absolute_uri(reverse(url_name, kwargs={'uidb64': uid, 'token': token}))


def send_staff_invite(request, user):
    """
    Email a new staff login a one-time link to choose their own password. The
    link uses Django's password-reset token, so it stops working once used (or
    after PASSWORD_RESET_TIMEOUT). Returns True if the email went out.
    """
    context = {
        'user': user,
        'link': _set_password_link(request, user, 'invite_accept'),
        'company': settings.COMPANY_LEGAL_NAME,
        'invited_by': request.user.get_full_name() or request.user.email or request.user.username,
        'valid_days': settings.PASSWORD_RESET_TIMEOUT // 86400,
    }
    return send_plain_email(
        to_email=user.email,
        subject=f'You have been invited to {settings.COMPANY_LEGAL_NAME}',
        body=render_to_string('registration/invite_email.txt', context),
    )


def send_password_reset(request, user):
    """Admin-triggered reset link (same email a user gets from "Forgot password")."""
    context = {
        'user': user,
        'link': _set_password_link(request, user, 'password_reset_confirm'),
        'company': settings.COMPANY_LEGAL_NAME,
        'valid_days': settings.PASSWORD_RESET_TIMEOUT // 86400,
    }
    return send_plain_email(
        to_email=user.email,
        subject=f'Reset your {settings.COMPANY_LEGAL_NAME} password',
        body=render_to_string('registration/password_reset_email.txt', context),
    )
