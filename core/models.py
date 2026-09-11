from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActivityLog(models.Model):
    """
    A simple audit trail — who did what, when — for access-control-sensitive
    actions (roles/permissions, staff accounts, password resets). Business
    records already carry their own created_at/updated_at/created_by, so this
    is deliberately scoped to actions that aren't otherwise traceable, rather
    than logging every click across the whole app.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity_logs',
    )
    action = models.CharField(max_length=100, help_text='e.g. "role.created", "staff_account.password_reset"')
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor_name = self.actor.username if self.actor else 'system'
        return f'{self.created_at:%Y-%m-%d %H:%M} — {actor_name} — {self.description}'
