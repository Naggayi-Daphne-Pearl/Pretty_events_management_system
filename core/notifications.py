"""
The notifications bell: things that need someone's attention, gathered from across
the app and filtered to what the user's role can see. Worked out from the records
(nothing to mark as read), and cached for a minute per user so it doesn't slow every page.
"""
from datetime import timedelta

from django.core.cache import cache
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

CACHE_SECONDS = 60
SHORTAGE_LOOKAHEAD_DAYS = 60


def _item(level, icon, text, url):
    return {'level': level, 'icon': icon, 'text': text, 'url': url}


def collect(user):
    from billing.models import Invoice, MobileMoneyTransaction
    from events.models import Event
    from inventory.models import EquipmentItem
    from inventory.services import RESERVING_STATUSES, event_shortages

    from .models import ActivityLog
    from .permissions import scope_events_to_assignments

    today = timezone.localdate()
    items = []

    if user.has_perm('billing.view_invoice'):
        overdue = Invoice.objects.filter(status=Invoice.Status.OVERDUE).count()
        if overdue:
            items.append(_item('danger', 'bi-exclamation-circle',
                               f'{overdue} overdue invoice{"s" if overdue != 1 else ""}',
                               reverse('billing:invoice_list') + '?status=overdue'))

    if user.has_perm('billing.view_quotation'):
        since = timezone.now() - timedelta(days=3)
        for log in ActivityLog.objects.filter(action='quotation.accepted_online', created_at__gte=since)[:5]:
            items.append(_item('ok', 'bi-check2-circle', log.description, reverse('billing:quotation_list')))

    if user.has_perm('events.view_event'):
        # Equipment still out after the event's last day.
        late = scope_events_to_assignments(Event.objects.all(), user).annotate(
            last=Coalesce('end_date', 'event_date'),
        ).filter(last__lt=today, equipment_issues__isnull=False).distinct()
        late_ids = [
            e.pk for e in late.prefetch_related('equipment_issues__returns')
            if any(i.quantity_outstanding > 0 for i in e.equipment_issues.all())
        ]
        if late_ids:
            n = len(late_ids)
            url = (reverse('events:detail', args=[late_ids[0]]) + '#equipment') if n == 1 else reverse('events:list')
            items.append(_item('danger', 'bi-box-arrow-in-left',
                               f'Equipment not back from {n} finished event{"s" if n != 1 else ""}', url))

    if user.has_perm('inventory.view_equipmentitem') and user.has_perm('events.view_event'):
        upcoming = scope_events_to_assignments(Event.objects.select_related('customer'), user).filter(
            status__in=RESERVING_STATUSES, event_date__gte=today,
            event_date__lte=today + timedelta(days=SHORTAGE_LOOKAHEAD_DAYS),
        ).order_by('event_date').prefetch_related('invoices__line_items', 'quotations__line_items', 'equipment_issues__returns')[:30]
        for event in upcoming:
            shortages = event_shortages(event)
            if shortages:
                names = ', '.join(s['item'].name for s in shortages[:2]) + ('…' if len(shortages) > 2 else '')
                items.append(_item('danger', 'bi-calendar-x',
                                   f'Double-booked: {names} for {event.customer.name} ({event.event_date:%d %b})',
                                   reverse('events:detail', args=[event.pk])))

    if user.has_perm('billing.view_payment'):
        waiting = MobileMoneyTransaction.objects.filter(status=MobileMoneyTransaction.Status.UNMATCHED).count()
        if waiting:
            items.append(_item('warn', 'bi-phone',
                               f'{waiting} mobile money payment{"s" if waiting != 1 else ""} to match',
                               reverse('billing:mobile_money')))

    if user.has_perm('inventory.view_equipmentitem'):
        low = EquipmentItem.objects.low_stock().count()
        if low:
            items.append(_item('warn', 'bi-box-seam', f'{low} item{"s" if low != 1 else ""} low on stock',
                               reverse('inventory:item_list')))
    return items


def for_user(user):
    key = f'notifications:{user.pk}'
    items = cache.get(key)
    if items is None:
        items = collect(user)
        cache.set(key, items, CACHE_SECONDS)
    return items
