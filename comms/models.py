from django.conf import settings
from django.db import models

from core.models import TimeStampedModel
from customers.models import Customer
from events.models import Event


class CommunicationLog(TimeStampedModel):
    """
    Structured storage of customer outreach. Entries are typed in by staff, or
    written automatically when staff email a document or start a WhatsApp chat /
    call from the app (see comms.views.contact_customer). Designed so a Phase 2
    SMS/WhatsApp API integration can read/write this same log.
    """
    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        CALL = 'call', 'Phone Call'
        EMAIL = 'email', 'Email'
        IN_PERSON = 'in_person', 'In Person'
        OTHER = 'other', 'Other'

    class Direction(models.TextChoices):
        OUTBOUND = 'outbound', 'Outbound'
        INBOUND = 'inbound', 'Inbound'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='communication_logs')
    event = models.ForeignKey(
        Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='communication_logs',
        help_text='Optional: the event this contact was about.',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.CALL)
    direction = models.CharField(max_length=20, choices=Direction.choices, default=Direction.OUTBOUND)
    message = models.TextField(blank=True)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='communication_logs_recorded',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_channel_display()} with {self.customer} ({self.created_at:%Y-%m-%d})'
