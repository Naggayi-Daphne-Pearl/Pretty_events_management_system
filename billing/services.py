from decimal import Decimal

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
        # The tax share of this payment, in proportion to the invoice's tax in its total.
        total = invoice.total
        tax_share = (amount * invoice.tax_amount / total).quantize(Decimal('0.01')) if total and invoice.tax_amount else 0
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
            tax_amount=tax_share,
        )
        advanced = invoice.event.advance_status_at_least(Event.Status.CONFIRMED)
    return payment, advanced


def quotation_acceptance_problem(quotation):
    """Why a client can't accept this quotation online right now, or '' if they can."""
    from .models import Quotation
    if quotation.has_invoice:
        return 'already_accepted'
    if quotation.status in (Quotation.Status.REJECTED, Quotation.Status.EXPIRED):
        return 'closed'
    if quotation.valid_until and quotation.valid_until < timezone.localdate():
        return 'expired'
    if quotation.event.status == Event.Status.CANCELLED:
        return 'closed'
    return ''


def accept_quotation_online(quotation, accepted_by=''):
    """
    The client accepted from the shared link: turn the quotation into an invoice,
    confirm the event, and record who accepted it and when for the staff.
    Returns the invoice. Callers check quotation_acceptance_problem() first.
    """
    from comms.models import CommunicationLog
    from core.models import ActivityLog

    from .models import Quotation

    who = accepted_by.strip()[:100] or 'the client'
    with transaction.atomic():
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        if quotation_acceptance_problem(quotation):
            return getattr(quotation, 'invoice', None)
        invoice = Invoice.create_from_quotation(quotation)
        quotation.status = Quotation.Status.APPROVED
        quotation.save(update_fields=['status'])
        quotation.event.advance_status_at_least(Event.Status.CONFIRMED)
        CommunicationLog.objects.create(
            customer=quotation.event.customer, event=quotation.event,
            channel=CommunicationLog.Channel.OTHER, direction=CommunicationLog.Direction.INBOUND,
            message=f'Accepted quotation {quotation.number} online ({who}). Invoice {invoice.number} was created.',
        )
        ActivityLog.objects.create(
            actor=None, action='quotation.accepted_online',
            description=f'{quotation.event.customer.name} accepted {quotation.number} online; invoice {invoice.number} created',
        )
    return invoice
