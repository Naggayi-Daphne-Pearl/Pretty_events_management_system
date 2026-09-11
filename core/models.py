from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ActivityLog(models.Model):
    """
    A simple audit trail — who did what, when. Covers both access-control
    actions (roles/permissions, staff accounts, password resets) and business
    record changes (customers, events, quotations, invoices, payments,
    inventory, staff assignments, communication logs created/updated) — see
    core.activity.log_model_activity(), called from each app's create/update
    views. Business records also carry their own created_at/updated_at/
    created_by for a per-record view; this is the cross-cutting timeline.
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
