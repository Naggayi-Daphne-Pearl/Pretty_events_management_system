import secrets
from datetime import timedelta

from django.utils import timezone

from .models import FormSubmissionToken

FIELD_NAME = 'once_token'
TOKEN_LIFETIME = timedelta(days=1)


def issue_token(user):
    # Housekeeping: forms opened but never submitted leave tokens behind.
    FormSubmissionToken.objects.filter(created_at__lt=timezone.now() - TOKEN_LIFETIME).delete()
    token = secrets.token_urlsafe(24)
    FormSubmissionToken.objects.create(token=token, user=user)
    return token


def claim_token(request):
    """True exactly once per issued token (and only for the user it was issued to)."""
    token = request.POST.get(FIELD_NAME, '')
    if not token:
        return False
    deleted, _ = FormSubmissionToken.objects.filter(
        token=token, user=request.user, created_at__gte=timezone.now() - TOKEN_LIFETIME,
    ).delete()
    return deleted == 1
