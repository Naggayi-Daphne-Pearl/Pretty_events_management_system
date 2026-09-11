from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel
from events.models import Event
from inventory.models import EquipmentItem


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
        return (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))


class Quotation(TimeStampedModel):
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

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.number:
            self.number = f'QUO-{self.created_at.year}-{self.pk:05d}'
            super().save(update_fields=['number'])

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.line_items.all()), Decimal('0'))

    @property
    def total(self):
        return self.subtotal

    @property
    def has_invoice(self):
        return hasattr(self, 'invoice')


class QuotationLineItem(LineItemMixin):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='line_items')

    def __str__(self):
        return self.description


class Invoice(TimeStampedModel):
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

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.number:
            self.number = f'INV-{self.created_at.year}-{self.pk:05d}'
            super().save(update_fields=['number'])

    @property
    def subtotal(self):
        return sum((item.line_total for item in self.line_items.all()), Decimal('0'))

    @property
    def total(self):
        return self.subtotal

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal('0'))

    @property
    def balance_due(self):
        return self.total - self.amount_paid

    def refresh_status(self):
        """Recompute payment status from recorded payments. Call after saving a payment."""
        if self.status == self.Status.CANCELLED:
            return
        paid = self.amount_paid
        total = self.total
        if paid <= 0:
            new_status = self.Status.UNPAID
        elif paid < total:
            new_status = self.Status.PARTIALLY_PAID
        else:
            new_status = self.Status.PAID
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


class Receipt(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt')
    issued_at = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number or f'Receipt (draft) #{self.pk}'

    def get_absolute_url(self):
        return reverse('billing:receipt_detail', args=[self.pk])

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.number:
            self.number = f'RCT-{self.created_at.year}-{self.pk:05d}'
            super().save(update_fields=['number'])
