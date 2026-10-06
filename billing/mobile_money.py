"""
Incoming mobile money payments (MTN MoMo, Airtel Money) via webhook.

The provider (or a payment aggregator) POSTs each received payment to
/billing/mobile-money/webhook/<provider>/. The request must carry an
X-Signature header: the hex HMAC-SHA256 of the raw body, keyed with
MOBILE_MONEY_WEBHOOK_SECRET. With no secret configured the endpoint is off (404).

Each provider's body is turned into one common shape by a parser in PARSERS.
'generic' accepts that shape directly:

    {"transaction_id": "...", "amount": 150000, "currency": "UGX",
     "phone": "256772123456", "name": "Jane Doe", "reference": "INV-2026-00012",
     "timestamp": "2026-10-06T10:15:00+03:00"}

Going live with MTN or Airtel directly (or an aggregator such as Flutterwave or
Yo! Payments) means adding a parser for their callback format here, and
pointing their callback URL at this endpoint.
"""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from accounting.locks import is_locked
from core.models import ActivityLog

from .models import Invoice, MobileMoneyTransaction, Payment
from .services import record_payment

INVOICE_NUMBER = re.compile(r'INV[\s\-_/]*(\d{4})[\s\-_/]*(\d{1,5})', re.IGNORECASE)


class WebhookError(ValueError):
    """The body couldn't be understood; the provider gets a 400."""


def signature_ok(body, signature):
    secret = settings.MOBILE_MONEY_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def parse_generic(data):
    try:
        amount = Decimal(str(data['amount']))
        transaction_id = str(data['transaction_id']).strip()
    except (KeyError, InvalidOperation) as exc:
        raise WebhookError(f'missing or bad field: {exc}') from exc
    if not transaction_id or amount <= 0:
        raise WebhookError('transaction_id and a positive amount are required')
    received_at = parse_datetime(str(data.get('timestamp') or '')) or timezone.now()
    return {
        'transaction_id': transaction_id,
        'amount': amount,
        'currency': str(data.get('currency') or settings.CURRENCY).upper()[:3],
        'payer_phone': str(data.get('phone') or '')[:30],
        'payer_name': str(data.get('name') or '')[:150],
        'reference': str(data.get('reference') or '')[:255],
        'received_at': received_at,
    }


PARSERS = {
    'generic': parse_generic,
    # 'mtn': parse_mtn,      add once the MTN MoMo collection callback format is confirmed
    # 'airtel': parse_airtel,
}


def find_invoice(reference):
    """The open invoice named in the payer's reference, e.g. "inv 2026 12" -> INV-2026-00012."""
    match = INVOICE_NUMBER.search(reference or '')
    if not match:
        return None
    number = f'INV-{match.group(1)}-{int(match.group(2)):05d}'
    return Invoice.objects.exclude(status=Invoice.Status.CANCELLED).filter(number=number).first()


def apply_to_invoice(txn, invoice, user=None):
    """Record the transaction as a payment on `invoice` and mark it matched."""
    paid_at = timezone.localtime(txn.received_at).date()
    if is_locked(paid_at):  # reported after its month was closed: book it today instead
        paid_at = timezone.localdate()
    payment, _ = record_payment(
        invoice, amount=txn.amount, method=Payment.Method.MOBILE_MONEY,
        paid_at=paid_at,
        reference_number=txn.transaction_id[:50],
        notes=f'Mobile money from {txn.payer_name or txn.payer_phone}'[:255],
        received_by=user,
    )
    txn.payment = payment
    txn.status = MobileMoneyTransaction.Status.MATCHED
    txn.allocated_by = user
    txn.save(update_fields=['payment', 'status', 'allocated_by', 'updated_at'])
    ActivityLog.objects.create(
        actor=user, action='mobile_money.matched',
        description=f'{txn} recorded on invoice {invoice.number}' + ('' if user else ' automatically'),
    )
    return payment


def receive(provider, data):
    """
    Store one webhook delivery and, if it names an open invoice, record the payment.
    Returns (transaction, created). A repeat delivery returns the stored one unchanged.
    """
    parser = PARSERS.get(provider)
    if parser is None:
        raise WebhookError(f'unknown provider {provider!r}')
    fields = parser(data)
    with transaction.atomic():
        existing = MobileMoneyTransaction.objects.select_for_update().filter(
            provider=provider, transaction_id=fields['transaction_id'],
        ).first()
        if existing:
            return existing, False
        try:
            with transaction.atomic():
                txn = MobileMoneyTransaction.objects.create(provider=provider, raw=data, **fields)
        except IntegrityError:  # a simultaneous duplicate delivery won the race
            return MobileMoneyTransaction.objects.get(provider=provider, transaction_id=fields['transaction_id']), False
        invoice = find_invoice(txn.reference) if txn.currency == settings.CURRENCY else None
        if invoice:
            apply_to_invoice(txn, invoice)
    return txn, True


def parse_body(body):
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookError('body is not JSON') from exc
    if not isinstance(data, dict):
        raise WebhookError('body must be a JSON object')
    return data
