from datetime import date

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from billing.models import Invoice
from events.models import Event
from inventory.models import EquipmentItem


@login_required
def index(request):
    return render(request, 'reports/index.html')


@login_required
@permission_required('events.view_event', raise_exception=True)
def event_summary(request):
    today = date.today()
    start = request.GET.get('start') or today.replace(day=1).isoformat()
    end = request.GET.get('end') or today.isoformat()

    events = Event.objects.filter(event_date__gte=start, event_date__lte=end)
    by_status = []
    for value, label in Event.Status.choices:
        by_status.append({'label': label, 'count': events.filter(status=value).count()})

    return render(request, 'reports/event_summary.html', {
        'start': start, 'end': end,
        'total': events.count(),
        'by_status': by_status,
        'events': events.select_related('customer').order_by('event_date'),
    })


@login_required
@permission_required('billing.view_invoice', raise_exception=True)
def outstanding_payments(request):
    invoices = Invoice.objects.exclude(
        status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED],
    ).select_related('event__customer').order_by('due_date')
    total_outstanding = sum((inv.balance_due for inv in invoices), 0)
    return render(request, 'reports/outstanding_payments.html', {
        'invoices': invoices,
        'total_outstanding': total_outstanding,
    })


@login_required
@permission_required('inventory.view_equipmentitem', raise_exception=True)
def inventory_summary(request):
    items = EquipmentItem.objects.select_related('category').all()
    return render(request, 'reports/inventory_summary.html', {'items': items})
