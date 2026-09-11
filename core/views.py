from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from billing.models import Invoice
from events.models import Event
from inventory.models import EquipmentItem

from .permissions import scope_events_to_assignments


@login_required
def dashboard(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    events_qs = scope_events_to_assignments(Event.objects.select_related('customer'), request.user)

    upcoming_week = events_qs.filter(
        event_date__gte=today, event_date__lte=week_end,
    ).exclude(status__in=[Event.Status.COMPLETED, Event.Status.CANCELLED])
    upcoming_month = events_qs.filter(
        event_date__gte=today, event_date__lte=month_end,
    ).exclude(status__in=[Event.Status.COMPLETED, Event.Status.CANCELLED])

    context = {
        'upcoming_week': upcoming_week.order_by('event_date')[:10],
        'upcoming_week_count': upcoming_week.count(),
        'upcoming_month_count': upcoming_month.count(),
    }

    if request.user.has_perm('billing.view_invoice'):
        unpaid_invoices = Invoice.objects.exclude(
            status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED],
        ).select_related('event__customer')
        context['unpaid_invoices'] = unpaid_invoices.order_by('due_date')[:10]
        context['unpaid_count'] = unpaid_invoices.count()
        context['unpaid_total'] = sum((inv.balance_due for inv in unpaid_invoices), 0)

    if request.user.has_perm('inventory.view_equipmentitem'):
        low_stock = [item for item in EquipmentItem.objects.all() if item.available_quantity <= 5]
        context['low_stock_items'] = low_stock[:10]

    return render(request, 'core/dashboard.html', context)
