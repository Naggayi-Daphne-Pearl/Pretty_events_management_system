from django.utils import timezone

from core.models import ActivityLog

from .models import Event


def sync_event_status(event, today=None):
    """Apply Event.sync_status_with_calendar and record any change in the Activity Log."""
    new_status = event.sync_status_with_calendar(today=today)
    if new_status:
        ActivityLog.objects.create(
            actor=None,
            action='event.status_auto',
            description=f'Event "{event}" moved to {event.get_status_display()} automatically (event date)',
        )
    return new_status


def sync_event_statuses(today=None):
    """
    Bulk version for every confirmed/in-progress event that has started. Cheap
    enough to run on page loads (dashboard, events list) and also exposed as the
    `sync_event_statuses` management command for a daily cron. Returns the
    number of events changed.
    """
    today = today or timezone.localdate()
    candidates = Event.objects.filter(
        status__in=[Event.Status.CONFIRMED, Event.Status.IN_PROGRESS], event_date__lte=today,
    ).select_related('customer').prefetch_related('equipment_issues__returns')
    return sum(1 for event in candidates if sync_event_status(event, today=today))
