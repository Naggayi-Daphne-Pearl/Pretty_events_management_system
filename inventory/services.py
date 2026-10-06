"""
Date-aware equipment availability.

`EquipmentItem.available_quantity` only knows what is physically out today. These
helpers also count what confirmed bookings have reserved for their dates, so a new
quote or confirmation for the same Saturday sees that the round tables are taken.

An event reserves equipment while it is Confirmed or In Progress, from its first to
its last day. What it reserves is its booked items (see `booked_quantities`), or what
was actually issued to it if that is more.
"""
from collections import Counter
from datetime import timedelta

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from events.models import Event

from .models import EquipmentIssue, EquipmentItem

RESERVING_STATUSES = (Event.Status.CONFIRMED, Event.Status.IN_PROGRESS)


def booked_quantities(event):
    """
    {equipment_item_id: quantity} the event has booked: its open invoices' items, or
    if it has none, its approved quotations, or failing that its newest open quotation.
    Lines not tied to an inventory item (labour, transport) are ignored.
    """
    counts = Counter()
    invoices = [i for i in event.invoices.all() if i.status != i.Status.CANCELLED]
    if invoices:
        sources = invoices
    else:
        quotations = [q for q in event.quotations.all() if q.status not in (q.Status.REJECTED, q.Status.EXPIRED)]
        approved = [q for q in quotations if q.status == q.Status.APPROVED]
        sources = approved or sorted(quotations, key=lambda q: q.created_at, reverse=True)[:1]
    for doc in sources:
        for line in doc.line_items.all():
            if line.equipment_item_id:
                counts[line.equipment_item_id] += int(line.quantity)
    return counts


def _issued_outstanding(event):
    counts = Counter()
    for issue in event.equipment_issues.all():
        counts[issue.equipment_item_id] += issue.quantity_outstanding
    return counts


def _reservation(event):
    """Booked items, raised to whatever was actually issued and is still out."""
    booked = booked_quantities(event)
    for item_id, qty in _issued_outstanding(event).items():
        booked[item_id] = max(booked[item_id], qty)
    return booked


def overlapping_events(start, end, exclude_event=None):
    qs = Event.objects.filter(status__in=RESERVING_STATUSES, event_date__lte=end).annotate(
        last=Coalesce('end_date', 'event_date'),
    ).filter(last__gte=start).prefetch_related(
        'invoices__line_items', 'quotations__line_items', 'equipment_issues__returns',
    ).select_related('customer')
    if exclude_event is not None and exclude_event.pk:
        qs = qs.exclude(pk=exclude_event.pk)
    return list(qs)


def _still_out_elsewhere(start, end, event_ids):
    """
    Equipment issued to events outside the window and not yet back. It counts as
    unavailable unless it is due back before the window starts (and isn't late).
    """
    today = timezone.localdate()
    counts = Counter()
    issues = EquipmentIssue.objects.exclude(event_id__in=event_ids).annotate(
        back=Coalesce(Sum('returns__quantity_returned'), 0),
    ).filter(quantity_issued__gt=F('back'))
    for issue in issues:
        out = issue.quantity_issued - issue.back
        due = issue.expected_return_date
        if due is not None and today <= due < start:
            continue
        counts[issue.equipment_item_id] += out
    return counts


def availability(start, end=None, exclude_event=None):
    """
    {equipment_item_id: quantity free on every day of [start, end]} for all items,
    i.e. total owned minus the busiest day's reservations and anything still out.
    """
    end = end or start
    events = overlapping_events(start, end, exclude_event)
    reservations = [(e, _reservation(e)) for e in events]
    elsewhere = _still_out_elsewhere(start, end, [e.pk for e in events] + ([exclude_event.pk] if exclude_event and exclude_event.pk else []))

    peak = Counter()
    day = start
    while day <= end:
        on_day = Counter()
        for event, reserved in reservations:
            if event.event_date <= day <= event.last_day:
                on_day.update(reserved)
        for item_id, qty in on_day.items():
            peak[item_id] = max(peak[item_id], qty)
        day += timedelta(days=1)

    return {
        item.pk: item.total_quantity - peak[item.pk] - elsewhere[item.pk]
        for item in EquipmentItem.objects.only('pk', 'total_quantity')
    }


def availability_for_event(event):
    return availability(event.event_date, event.last_day, exclude_event=event)


def event_shortages(event):
    """
    Items this event has booked that won't all be free on its dates because other
    confirmed events (or equipment not yet returned) need them. Returns a list of
    {'item', 'needed', 'available', 'clashes'} where clashes are the other events
    holding that item over the same dates.
    """
    needed = booked_quantities(event)
    if not needed:
        return []
    free = availability_for_event(event)
    short_ids = [item_id for item_id, qty in needed.items() if qty > free.get(item_id, 0)]
    if not short_ids:
        return []
    others = [(e, _reservation(e)) for e in overlapping_events(event.event_date, event.last_day, exclude_event=event)]
    items = EquipmentItem.objects.in_bulk(short_ids)
    return [
        {
            'item': items[item_id],
            'needed': needed[item_id],
            'available': max(free.get(item_id, 0), 0),
            'clashes': [e for e, reserved in others if reserved.get(item_id)],
        }
        for item_id in short_ids
    ]


def upcoming_bookings(item, days=90):
    """Confirmed events over the next `days` that reserve this item, with how many."""
    today = timezone.localdate()
    rows = []
    for event in overlapping_events(today, today + timedelta(days=days)):
        qty = _reservation(event).get(item.pk)
        if qty:
            rows.append({'event': event, 'quantity': qty})
    return sorted(rows, key=lambda r: r['event'].event_date)


def warn_if_short(request, event):
    """Flash a warning when a newly confirmed event has booked more than will be free."""
    from django.contrib import messages
    if event.status not in RESERVING_STATUSES:
        return
    shortages = event_shortages(event)
    if shortages:
        parts = ', '.join(f"{s['item'].name} ({s['needed']} booked, {s['available']} free)" for s in shortages)
        messages.warning(request, f'Not enough equipment on these dates: {parts}. See the event page for the clashing bookings.')


def job_rows(event):
    """Per item for an event's job sheet: booked, issued so far, still out."""
    booked = booked_quantities(event)
    issued, out = Counter(), Counter()
    for issue in event.equipment_issues.all():
        issued[issue.equipment_item_id] += issue.quantity_issued
        out[issue.equipment_item_id] += issue.quantity_outstanding
    items = EquipmentItem.objects.filter(pk__in=set(booked) | set(issued)).select_related('category').order_by(
        'category__name', 'name',
    )
    return [
        {'item': item, 'booked': booked[item.pk], 'issued': issued[item.pk], 'out': out[item.pk],
         'to_load': max(booked[item.pk] - issued[item.pk], 0)}
        for item in items
    ]


def load_items(event, quantities, user):
    """
    Record equipment going out to `event`: {item_id: qty}. Each quantity must be
    physically available now. All or nothing; returns a list of problems (empty = saved).
    """
    from django.db import transaction

    wanted = {item_id: qty for item_id, qty in quantities.items() if qty > 0}
    items = EquipmentItem.objects.with_availability().in_bulk(list(wanted))
    problems = [
        f'Only {items[item_id].available_quantity} {items[item_id].unit} of {items[item_id].name} are in the store.'
        for item_id, qty in wanted.items() if item_id in items and qty > items[item_id].available_quantity
    ]
    if problems or not wanted:
        return problems or ['Enter how many of at least one item went out.']
    today = timezone.localdate()
    with transaction.atomic():
        for item_id, qty in wanted.items():
            EquipmentIssue.objects.create(
                event=event, equipment_item=items[item_id], quantity_issued=qty, issued_at=today,
                expected_return_date=event.last_day + timedelta(days=1), issued_by=user,
            )
    return []


def return_items(event, quantities, user, condition_notes=''):
    """
    Record equipment coming back from `event`: {item_id: qty}, spread over that item's
    outstanding issues oldest first. Returns a list of problems (empty = saved).
    """
    from django.db import transaction

    from .models import EquipmentReturn

    wanted = {item_id: qty for item_id, qty in quantities.items() if qty > 0}
    if not wanted:
        return ['Enter how many of at least one item came back.']
    issues = {}
    for issue in event.equipment_issues.select_related('equipment_item').prefetch_related('returns').order_by('issued_at', 'pk'):
        if issue.quantity_outstanding > 0:
            issues.setdefault(issue.equipment_item_id, []).append(issue)
    problems = []
    for item_id, qty in wanted.items():
        out = sum(i.quantity_outstanding for i in issues.get(item_id, []))
        if qty > out:
            name = issues[item_id][0].equipment_item.name if item_id in issues else 'that item'
            problems.append(f'Only {out} of {name} are still out for this event.')
    if problems:
        return problems
    today = timezone.localdate()
    with transaction.atomic():
        for item_id, qty in wanted.items():
            for issue in issues[item_id]:
                take = min(qty, issue.quantity_outstanding)
                if take:
                    EquipmentReturn.objects.create(
                        issue=issue, quantity_returned=take, returned_at=today,
                        condition_notes=condition_notes[:255], received_by=user,
                    )
                    qty -= take
                if not qty:
                    break
    return []
