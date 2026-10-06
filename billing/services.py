from django.db import transaction
from django.utils import timezone

from events.models import Event

from .models import Invoice, Payment


def sync_invoice_statuses(today=None):
    """
    Mark open invoices whose due date has passed as Overdue. Cheap enough to run on
    page loads (dashboard, invoice list, outstanding payments) and also exposed as the
    `sync_invoice_statuses` management command for a daily cron. Returns the number
    of invoices changed.
    """
    today = today or timezone.localdate()
    candidates = Invoice.objects.filter(
        status__in=[Invoice.Status.UNPAID, Invoice.Status.PARTIALLY_PAID], due_date__lt=today,
    ).prefetch_related('line_items', 'payments')
    changed = 0
    for invoice in candidates:
        before = invoice.status
        invoice.refresh_status()
        changed += invoice.status != before
    return changed


def record_payment(invoice, *, amount, method, paid_at=None, reference_number='', notes='', received_by=None):
    """
    Record money received against an invoice: the payment (which issues its receipt and
    refreshes the invoice status), the matching income record (which posts the ledger
    journal), and the event moving to Confirmed. Used by the payment form and by the
    mobile money webhook. Returns (payment, event_status_changed).
    """
    from finance.models import IncomeRecord

    with transaction.atomic():
        payment = Payment.objects.create(
            invoice=invoice, amount=amount, method=method, paid_at=paid_at or timezone.localdate(),
            reference_number=reference_number, notes=notes, received_by=received_by,
        )
        # A payment IS income: record it automatically so Finance/P&L totals are right
        # without staff re-entering every invoice payment as an income record too.
        IncomeRecord.objects.create(
            amount=payment.amount,
            source=IncomeRecord.Source.INVOICE_PAYMENT,
            date=payment.paid_at,
            event=invoice.event,
            payment=payment,
            description=f'Payment on invoice {invoice.number}',
            recorded_by=received_by,
        )
        advanced = invoice.event.advance_status_at_least(Event.Status.CONFIRMED)
    return payment, advanced
