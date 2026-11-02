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


class FormSubmissionToken(models.Model):
    """
    One-time token embedded in forms whose POST has a side effect that must not
    repeat: sending an email, recording a payment. The view claims (deletes) the
    token before acting; a double-click, refresh-resubmit or Back-and-resubmit
    arrives with an already-claimed token and is refused. Claiming is a single
    DELETE, so two simultaneous requests can't both win. See core.once.
    """
    token = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)


class FailedLoginAttempt(models.Model):
    """
    One row per failed login, keyed by the (lower-cased) email/username typed.
    Used to lock an identifier out for a while after repeated failures so a
    password can't be brute-forced. Stored in the DB rather than the cache
    because production runs several gunicorn workers that don't share memory.
    See core.auth.
    """
    identifier = models.CharField(max_length=254, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class RoleDefault(models.Model):
    """
    Record that setup_groups has applied one starter default: a role it created
    (permission='') or a permission it gave that role. Each default is applied only
    once, so a role or permission the client later removes stays removed, while
    defaults for new features still reach existing roles on their first deploy.
    """
    group_name = models.CharField(max_length=150)
    permission = models.CharField(max_length=255, blank=True, help_text="'app_label.codename', or blank for the role itself.")
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group_name', 'permission')

    def __str__(self):
        return f'{self.group_name}: {self.permission or "(role created)"}'


class DailyJobRun(models.Model):
    """One row per day the daily jobs ran (see core.daily); the unique date stops double runs."""
    day = models.DateField(unique=True)
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.day)
