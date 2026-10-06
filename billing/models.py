from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel
from events.models import Event
from inventory.models import EquipmentItem


class DocumentSequence(models.Model):
    """
    The last number issued per document type and year (QUO-2026-00001, ...). Numbers
    restart at 1 each year and are taken inside the saving transaction with the row
    locked, so two people saving at once can't get the same number and a save that
    fails doesn't burn one (unlike a database id, which leaves a gap).
    """
    prefix = models.CharField(max_length=10)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('prefix', 'year')

    def __str__(self):
        return f'{self.prefix}-{self.year}: {self.last_number}'

    @classmethod
    def next_number(cls, prefix, model):
        """Format and reserve the next number. Must run inside the transaction that saves the document."""
        year = timezone.localdate().year
        with transaction.atomic():
            seq = cls.objects.select_for_update().filter(prefix=prefix, year=year).first()
            if seq is None:
                # First document of the year: carry on from any numbers already issued
                # under the old id-based scheme so nothing is ever reused.
                existing = model.objects.filter(number__startswith=f'{prefix}-{year}-').values_list('number', flat=True)
                start = max((int(n.rsplit('-', 1)[1]) for n in existing if n.rsplit('-', 1)[1].isdigit()), default=0)
                try:
                    with transaction.atomic():
                        seq = cls.objects.create(prefix=prefix, year=year, last_number=start)
                except IntegrityError:  # someone else created it first
                    seq = cls.objects.select_for_update().get(prefix=prefix, year=year)
            seq.last_number += 1
            seq.save(update_fields=['last_number'])
        return f'{prefix}-{year}-{seq.last_number:05d}'


class NumberedDocumentMixin(models.Model):
    """Gives a document its yearly number when first saved. Subclasses set NUMBER_PREFIX."""
    NUMBER_PREFIX = ''

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.number:
            with transaction.atomic():
                self.number = DocumentSequence.next_number(self.NUMBER_PREFIX, type(self))
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


def percent(rate):
    """18.00 -> '18', 7.50 -> '7.5'."""
    return f'{rate.normalize():f}' if rate % 1 else f'{int(rate)}'


class TaxGroup(TimeStampedModel):
    """
    A tax the business charges on top of its prices, e.g. "VAT" at 18%. Set up by the
    client under Finance > Taxes and chosen per quotation/invoice (or none). A
    document keeps the name and rate it was issued with, so editing or retiring a
    group later never changes invoices already sent.
    """
    name = models.CharField(max_length=60, unique=True, help_text='As printed on documents, e.g. "VAT".')
    rate = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Percent added on top of the line items, e.g. 18 for 18%.',
    )
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, help_text='Inactive taxes can\'t be chosen on new documents.')
    is_default = models.BooleanField(
        default=False, help_text='Pre-selected on new quotations. Only one tax can be the default.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({percent(self.rate)}%)'

    def get_absolute_url(self):
        return reverse('billing:tax_list')

    def save(self, *args, **kwargs):
        if self.is_default:
            TaxGroup.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class TaxedDocumentMixin(models.Model):
    """Tax on a quotation or invoice: the chosen group, plus the name and rate it was issued with."""
    tax_group = models.ForeignKey(
        TaxGroup, on_delete=models.PROTECT, null=True, blank=True, related_name='+', verbose_name='Tax',
    )
    tax_name = models.CharField(max_length=60, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0'))

    class Meta:
        abstract = True

    def apply_tax_group(self, group):
        """Choose a tax (or None) and capture its current name and rate on this document."""
        self.tax_group = group
        self.tax_name = group.name if group else ''
        self.tax_rate = group.rate if group else Decimal('0')

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.line_items.all()), Decimal('0'))

    @property
    def tax_amount(self):
        return (self.subtotal * self.tax_rate / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def tax_label(self):
        return f'{self.tax_name} ({percent(self.tax_rate)}%)' if self.tax_rate else ''

    @property
    def total(self):
        return self.subtotal + self.tax_amount


class LineItemMixin(models.Model):
    """Shared fields for quotation/invoice line items."""
    equipment_item = models.ForeignKey(
        EquipmentItem, on_delete=models.SET_NULL, null=True, blank=True,
        help_text='Optional — link this line to an actual inventory item. Leave blank for '
                   'services/fees (delivery, setup, etc.) that aren\'t physical equipment.',
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1'))
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        abstract = True

    @property
    def line_total(self):
        # quantity and unit_price are both 2-decimal-place fields, so their raw product
        # has up to 4 decimal places (e.g. 20.00 * 15000.00 = 300000.0000) — quantize back
        # to money precision here, at the source, so it never leaks into anything summed
        # from it (invoice/quotation totals, balance_due) or fed back into a 2-decimal-
        # place form field's initial value (that raised "no more than 2 decimal places").
        total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        return total.quantize(Decimal('0.01'))


class Quotation(NumberedDocumentMixin, TaxedDocumentMixin, TimeStampedModel):
    NUMBER_PREFIX = 'QUO'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        EXPIRED = 'expired', 'Expired'

    number = models.CharField(max_length=20, unique=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='quotations')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='quotations_created',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'Quotation (draft) #{self.pk}'

    def get_absolute_url(self):
        return reverse('billing:quotation_detail', args=[self.pk])

    @property
    def has_invoice(self):
        return hasattr(self, 'invoice')


class QuotationLineItem(LineItemMixin):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='line_items')

    def __str__(self):
        return self.description


class Invoice(NumberedDocumentMixin, TaxedDocumentMixin, TimeStampedModel):
    NUMBER_PREFIX = 'INV'

    class Status(models.TextChoices):
        UNPAID = 'unpaid', 'Unpaid'
        PARTIALLY_PAID = 'partially_paid', 'Partially Paid'
        PAID = 'paid', 'Paid'
        OVERDUE = 'overdue', 'Overdue'
        CANCELLED = 'cancelled', 'Cancelled'

    number = models.CharField(max_length=20, unique=True, blank=True)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='invoices')
    quotation = models.OneToOneField(
        Quotation, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices_created',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'Invoice (draft) #{self.pk}'

    def get_absolute_url(self):
        return reverse('billing:invoice_detail', args=[self.pk])

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal('0'))

    @property
    def balance_due(self):
        return self.total - self.amount_paid

    @property
    def is_past_due(self):
        return bool(self.due_date) and self.due_date < timezone.localdate()

    def refresh_status(self):
        """
        Recompute status from recorded payments and the due date. Call after saving a
        payment or editing the invoice; `sync_invoice_statuses` runs it for invoices
        that fall past due with no one touching them.
        """
        if self.status == self.Status.CANCELLED:
            return
        paid = self.amount_paid
        total = self.total
        if paid >= total and total > 0:
            new_status = self.Status.PAID
        elif self.is_past_due:
            new_status = self.Status.OVERDUE
        elif paid > 0:
            new_status = self.Status.PARTIALLY_PAID
        else:
            new_status = self.Status.UNPAID
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=['status'])

    @classmethod
    def create_from_quotation(cls, quotation, created_by=None):
        invoice = cls.objects.create(
            event=quotation.event,
            quotation=quotation,
            due_date=None,
            created_by=created_by,
            # The invoice charges the tax the client was quoted, at the quoted rate.
            tax_group=quotation.tax_group, tax_name=quotation.tax_name, tax_rate=quotation.tax_rate,
        )
        for item in quotation.line_items.all():
            InvoiceLineItem.objects.create(
                invoice=invoice,
                equipment_item=item.equipment_item,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
        return invoice


class InvoiceLineItem(LineItemMixin):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')

    def __str__(self):
        return self.description


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        MOBILE_MONEY = 'mobile_money', 'Mobile Money'
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
        CHEQUE = 'cheque', 'Cheque'
        OTHER = 'other', 'Other'

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    paid_at = models.DateField(default=timezone.localdate)
    reference_number = models.CharField(
        max_length=50, blank=True,
        help_text='Cheque number, mobile money transaction ID, etc. — printed on the receipt as "Cash/Cheque No."',
    )
    notes = models.CharField(
        max_length=255, blank=True,
        help_text='What this payment is for, e.g. "2 parasols 5x5" — printed on the receipt as "Being payment of".',
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments_received',
    )

    class Meta:
        ordering = ['-paid_at', '-created_at']

    def __str__(self):
        return f'{self.amount} on {self.invoice.number}'

    def get_absolute_url(self):
        return reverse('billing:receipt_detail', args=[self.receipt.pk])

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self.invoice.refresh_status()
            if not hasattr(self, 'receipt'):
                Receipt.objects.create(payment=self)


class Receipt(NumberedDocumentMixin, TimeStampedModel):
    NUMBER_PREFIX = 'RCT'

    number = models.CharField(max_length=20, unique=True, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt')
    issued_at = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'Receipt (draft) #{self.pk}'

    def get_absolute_url(self):
        return reverse('billing:receipt_detail', args=[self.pk])


class MobileMoneyTransaction(TimeStampedModel):
    """
    One incoming mobile money payment reported by the provider's webhook (see
    billing.mobile_money). Payments whose reference names an invoice are recorded
    automatically; the rest wait on the Mobile Money page for staff to allocate.
    The provider's transaction id is unique, so a repeated webhook can't pay twice.
    """
    class Status(models.TextChoices):
        MATCHED = 'matched', 'Recorded on invoice'
        UNMATCHED = 'unmatched', 'Needs allocating'
        IGNORED = 'ignored', 'Ignored'

    provider = models.CharField(max_length=20)
    transaction_id = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default='UGX')
    payer_phone = models.CharField(max_length=30, blank=True)
    payer_name = models.CharField(max_length=150, blank=True)
    reference = models.CharField(max_length=255, blank=True, help_text='What the payer typed as the reason/reference.')
    received_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNMATCHED)
    payment = models.OneToOneField(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='mobile_money_transaction',
    )
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='Staff member who matched it to an invoice (blank when matched automatically).',
    )
    raw = models.JSONField(default=dict, blank=True, help_text='The webhook body as received, for audit.')

    class Meta:
        ordering = ['-received_at']
        unique_together = ('provider', 'transaction_id')

    def __str__(self):
        return f'{self.provider.upper()} {self.transaction_id} ({self.currency} {self.amount:,.0f})'
