from django.conf import settings
from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel
from customers.models import Customer


class Event(TimeStampedModel):
    class Status(models.TextChoices):
        INQUIRY = 'inquiry', 'Inquiry'
        QUOTED = 'quoted', 'Quoted'
        CONFIRMED = 'confirmed', 'Confirmed'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='events')
    event_type = models.CharField(max_length=100, help_text='e.g. Wedding, Introduction, Corporate function')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INQUIRY)
    event_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text='Leave blank for single-day events')
    venue = models.CharField(max_length=255)
    guest_count = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='events_created',
    )

    class Meta:
        ordering = ['-event_date']
        permissions = [
            (
                'view_assigned_events_only',
                'Can view only events they are personally assigned to (row-level restriction)',
            ),
        ]

    def __str__(self):
        return f'{self.event_type} - {self.customer.name} ({self.event_date})'

    def get_absolute_url(self):
        return reverse('events:detail', args=[self.pk])

    @property
    def is_upcoming(self):
        from django.utils import timezone
        return self.event_date >= timezone.localdate() and self.status not in (
            self.Status.COMPLETED, self.Status.CANCELLED,
        )

    # Pipeline order for advance_status_at_least — deliberately excludes CANCELLED,
    # which is a terminal, out-of-band state a status.index() lookup should never touch.
    STATUS_PIPELINE = [Status.INQUIRY, Status.QUOTED, Status.CONFIRMED, Status.IN_PROGRESS, Status.COMPLETED]

    def advance_status_at_least(self, target):
        """
        Move status forward to `target` if it's currently earlier in the pipeline
        (e.g. creating a quotation nudges Inquiry -> Quoted). Never moves backward
        and never touches a cancelled event. Staff can still override the status
        manually at any time via the event edit form. Returns True if it changed.
        """
        if self.status == self.Status.CANCELLED:
            return False
        try:
            current_index = self.STATUS_PIPELINE.index(self.status)
            target_index = self.STATUS_PIPELINE.index(target)
        except ValueError:
            return False
        if target_index > current_index:
            self.status = target
            self.save(update_fields=['status'])
            return True
        return False

    @property
    def last_day(self):
        return self.end_date or self.event_date

    def has_outstanding_equipment(self):
        return any(issue.quantity_outstanding > 0 for issue in self.equipment_issues.all())

    def sync_status_with_calendar(self, today=None):
        """
        Date-driven moves for confirmed bookings only (never touches inquiries,
        quotes or cancelled events, so an unconfirmed booking is never marked
        as happening): Confirmed -> In Progress once the event starts, then
        -> Completed after its last day, but only once all issued equipment is
        back, since outstanding equipment means the job isn't really finished.
        Returns the new status if it changed, else None.
        """
        from django.utils import timezone
        today = today or timezone.localdate()
        if self.status not in (self.Status.CONFIRMED, self.Status.IN_PROGRESS) or self.event_date > today:
            return None
        if self.last_day < today and not self.has_outstanding_equipment():
            target = self.Status.COMPLETED
        else:
            target = self.Status.IN_PROGRESS
        return target if self.advance_status_at_least(target) else None
