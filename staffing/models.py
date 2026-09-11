from django.conf import settings
from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel
from events.models import Event


class StaffMember(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='staff_profile',
        help_text='Link to a login account, if this staff member needs system access.',
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    title = models.CharField(max_length=100, blank=True, help_text='e.g. Driver, Decorator, Site Supervisor')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return self.full_name

    def get_absolute_url(self):
        return reverse('staffing:detail', args=[self.pk])


class EventAssignment(TimeStampedModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='assignments')
    staff_member = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='assignments')
    role_on_event = models.CharField(max_length=100, blank=True, help_text='e.g. Lead, Setup crew, Driver')
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['event', 'staff_member']
        unique_together = ('event', 'staff_member')

    def __str__(self):
        return f'{self.staff_member} on {self.event}'
