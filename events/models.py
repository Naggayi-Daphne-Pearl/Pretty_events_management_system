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
