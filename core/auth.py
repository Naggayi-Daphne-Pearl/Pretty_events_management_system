from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.backends import ModelBackend
from django.shortcuts import redirect
from django.utils import timezone

from .models import FailedLoginAttempt

SESSION_STARTED_KEY = 'auth_started_at'


class EmailBackend(ModelBackend):
    """
    Log in with an email address (case-insensitive). A plain username still
    works as a fallback so older admin accounts without an email aren't locked
    out. If two accounts somehow share an email, neither can log in by email:
    guessing which one was meant would be a security hole.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        User = get_user_model()
        identifier = username.strip()
        if '@' in identifier:
            matches = list(User.objects.filter(email__iexact=identifier)[:2])
            user = matches[0] if len(matches) == 1 else None
        else:
            user = User.objects.filter(username=identifier).first()
        if user is None:
            User().set_password(password)  # same work as a real check, so timing doesn't reveal accounts
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


# ---------- Failed-login lockout ----------

def _window_start():
    return timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def normalise_identifier(value):
    return (value or '').strip().lower()[:254]


def is_locked_out(identifier):
    identifier = normalise_identifier(identifier)
    if not identifier:
        return False
    recent = FailedLoginAttempt.objects.filter(identifier=identifier, created_at__gte=_window_start()).count()
    return recent >= settings.LOGIN_MAX_FAILED_ATTEMPTS


def record_failed_login(identifier):
    identifier = normalise_identifier(identifier)
    if identifier:
        FailedLoginAttempt.objects.create(identifier=identifier)
    # Keep the table small: anything outside the window no longer matters.
    FailedLoginAttempt.objects.filter(created_at__lt=_window_start()).delete()


def clear_failed_logins(*identifiers):
    FailedLoginAttempt.objects.filter(
        identifier__in=[normalise_identifier(i) for i in identifiers if i],
    ).delete()


# ---------- Absolute session lifetime ----------

class SessionMaxAgeMiddleware:
    """
    SESSION_COOKIE_AGE already logs people out after inactivity; this adds a hard
    cap (SESSION_MAX_AGE_HOURS) from the moment they logged in, so a session that
    is kept busy can't stay signed in forever either.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            started = request.session.get(SESSION_STARTED_KEY)
            now = timezone.now().timestamp()
            if started is None:
                request.session[SESSION_STARTED_KEY] = now
            elif now - started > settings.SESSION_MAX_AGE_HOURS * 3600:
                logout(request)
                messages.info(request, 'For security you were signed out after '
                                       f'{settings.SESSION_MAX_AGE_HOURS} hours. Please log in again.')
                return redirect(settings.LOGIN_URL)
        return self.get_response(request)
