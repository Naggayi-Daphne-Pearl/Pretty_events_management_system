"""Extra dashboard figures: the getting-started checklist and the week/month numbers."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


def setup_checklist(user):
    """
    First steps after go-live, for the owner. Each tick is worked out from the data,
    so the card disappears by itself once the required steps are done.
    """
    if not user.is_superuser:
        return None
    from accounting.models import JournalEntry
    from billing.models import TaxGroup
    from customers.models import Customer
    from inventory.models import EquipmentItem
    from staffing.models import StaffMember

    steps = [
        {'label': 'Add your equipment and its hire prices', 'url': reverse('inventory:item_create'),
         'done': EquipmentItem.objects.filter(default_rate__isnull=False).exists()},
        {'label': 'Add staff and give logins to those who use the system', 'url': reverse('staffing:list'),
         'done': StaffMember.objects.exists() and get_user_model().objects.filter(is_active=True).count() > 1},
        {'label': 'Enter opening balances for cash, mobile money and bank', 'url': reverse('accounting:banking'),
         'done': JournalEntry.objects.filter(source=JournalEntry.Source.OPENING).exists()},
        {'label': 'Set up taxes such as VAT, if you charge them', 'url': reverse('billing:tax_list'),
         'done': TaxGroup.objects.exists(), 'optional': True},
        {'label': 'Add your first customer and event', 'url': reverse('customers:create'),
         'done': Customer.objects.exists()},
    ]
    if all(s['done'] for s in steps if not s.get('optional')):
        return None
    return {'steps': steps, 'done': sum(1 for s in steps if s['done']), 'total': len(steps)}


def week_and_month(user):
    """Income this month vs last, payments due this week, equipment going out this week."""
    from billing.models import Invoice
    from events.models import Event
    from finance.models import IncomeRecord
    from inventory.services import RESERVING_STATUSES, booked_quantities

    from .permissions import scope_events_to_assignments

    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    data = {}

    if user.has_perm('finance.view_incomerecord'):
        month_start = today.replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        # Same number of days into last month, so the comparison is fair mid-month.
        last_same_day = min(last_month_start + (today - month_start), last_month_end)

        def net_income(start, end):
            totals = IncomeRecord.objects.filter(date__gte=start, date__lte=end).aggregate(
                total=Sum('amount'), tax=Sum('tax_amount'))
            return (totals['total'] or 0) - (totals['tax'] or 0)

        this_month = net_income(month_start, today)
        last_month = net_income(last_month_start, last_same_day)
        data['income_this_month'] = this_month
        data['income_last_month'] = last_month
        data['income_change'] = round((this_month - last_month) * 100 / last_month) if last_month else None

    if user.has_perm('billing.view_invoice'):
        due = Invoice.objects.exclude(status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED]).filter(
            due_date__gte=today, due_date__lte=week_end,
        ).prefetch_related('line_items', 'payments')
        data['due_this_week'] = sum((inv.balance_due for inv in due), 0)
        data['due_this_week_count'] = len(due)

    if user.has_perm('events.view_event') and user.has_perm('inventory.view_equipmentitem'):
        events = scope_events_to_assignments(Event.objects.all(), user).filter(
            status__in=RESERVING_STATUSES, event_date__gte=today, event_date__lte=week_end,
        ).prefetch_related('invoices__line_items', 'quotations__line_items')
        data['items_out_this_week'] = sum(sum(booked_quantities(e).values()) for e in events)
        data['events_out_this_week'] = len(events)
    return data
