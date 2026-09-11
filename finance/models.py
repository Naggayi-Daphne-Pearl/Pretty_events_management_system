from django.conf import settings
from django.db import models
from django.utils import timezone

from billing.models import Payment
from core.models import TimeStampedModel
from events.models import Event


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Expense categories'

    def __str__(self):
        return self.name


class IncomeRecord(TimeStampedModel):
    class Source(models.TextChoices):
        INVOICE_PAYMENT = 'invoice_payment', 'Invoice Payment'
        OTHER = 'other', 'Other'

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.OTHER)
    date = models.DateField(default=timezone.localdate)
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='income_records')
    payment = models.OneToOneField(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='income_record',
    )
    description = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='income_records_recorded',
    )

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.amount} - {self.get_source_display()} ({self.date})'


class ExpenseRecord(TimeStampedModel):
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    date = models.DateField(default=timezone.localdate)
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='expense_records')
    description = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expense_records_recorded',
    )

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.amount} - {self.category} ({self.date})'
