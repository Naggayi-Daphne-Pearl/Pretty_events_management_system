from django.conf import settings
from django.db import models
from django.utils import timezone

from billing.models import Payment
from core.models import TimeStampedModel
from events.models import Event


BANK_ACCOUNTS = {'detail_type': 'cash_bank', 'is_active': True}


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='expense_categories',
        limit_choices_to={'account_type': 'expense', 'is_active': True},
        help_text='Expense account these costs are booked to. Leave blank for General Expenses.',
    )

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
    deposit_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        limit_choices_to=BANK_ACCOUNTS, verbose_name='Received into',
        help_text='Cash, mobile money or bank account the money went into. Invoice payments pick this from the payment method.',
    )
    income_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        limit_choices_to={'account_type': 'income', 'is_active': True}, verbose_name='Income account',
        help_text='Leave blank for Other Income (or Event Services Income for invoice payments).',
    )
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
    expense_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='expense_records',
        limit_choices_to={'account_type': 'expense', 'is_active': True}, verbose_name='Expense account',
        help_text='General ledger account this cost is booked to. Filled in from the category; change it if needed.',
    )
    paid_from_account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
        limit_choices_to=BANK_ACCOUNTS, verbose_name='Paid from',
        help_text='Cash, mobile money or bank account the money came out of. Leave blank for Cash on Hand.',
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expense_records_recorded',
    )

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.amount} - {self.category} ({self.date})'
