from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem
from core.models import ActivityLog

from .models import Subscription

# Never raise more than this many invoices for one subscription in a single run (e.g.
# a start date typed years in the past); the rest follow on later days.
MAX_CATCH_UP = 12


def invoice_next_period(subscription, actor=None, today=None):
    """Raise the invoice for the subscription's next unbilled period and move it on one period."""
    today = today or timezone.localdate()
    due = subscription.next_due_date
    end = subscription.period_end(due) - timedelta(days=1)
    with transaction.atomic():
        invoice = Invoice(event=subscription.event, issue_date=min(today, due), due_date=due, created_by=actor,
                          notes=f'{subscription.name}: {due:%d %b %Y} to {end:%d %b %Y}')
        invoice.apply_tax_group(subscription.tax_group)
        invoice.save()
        InvoiceLineItem.objects.create(
            invoice=invoice, description=f'{subscription.name} ({due:%d %b %Y} – {end:%d %b %Y})',
            quantity=1, unit_price=subscription.amount,
        )
        subscription.invoices.add(invoice)
        subscription.periods_invoiced += 1
        subscription.save()
        ActivityLog.objects.create(
            actor=actor, action='subscription.invoiced',
            description=f'Invoice {invoice.number} raised for renewal "{subscription}", due {due:%d %b %Y}',
        )
    return invoice


def is_due_for_invoice(subscription, today):
    return subscription.next_due_date - timedelta(days=subscription.invoice_days_before) <= today


def invoice_due_subscriptions(today=None):
    """Daily job: raise every renewal invoice that has come into its invoicing window. Returns the count."""
    today = today or timezone.localdate()
    raised = 0
    candidates = Subscription.objects.filter(is_active=True, next_due_date__lte=today + timedelta(days=366))
    for subscription in candidates.select_related('event__customer', 'tax_group'):
        for _ in range(MAX_CATCH_UP):
            if not is_due_for_invoice(subscription, today):
                break
            invoice_next_period(subscription, today=today)
            raised += 1
    return raised


def renewal_message(subscription):
    """WhatsApp text letting the client know a renewal is coming up."""
    from django.conf import settings

    from comms.outreach import _money

    return (
        f'Hello {subscription.customer.name}, this is {settings.COMPANY_LEGAL_NAME}. A friendly reminder that '
        f'your {subscription.name} for {subscription.event.event_type} renews on '
        f'{subscription.next_due_date:%d %b %Y}, at {_money(subscription.amount)}'
        f'{" plus " + subscription.tax_group.name if subscription.tax_group else ""}. '
        f'Reply here if you have any questions. Thank you!'
    )
