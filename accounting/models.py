from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse

from core.models import TimeStampedModel


class Account(TimeStampedModel):
    """
    One line of the chart of accounts. `account_type` drives the maths (which side
    increases it); `detail_type` drives where it appears on the reports (e.g. a
    Cash & Bank asset shows under current assets and on the Banking page).
    """

    class Type(models.TextChoices):
        ASSET = 'asset', 'Asset'
        LIABILITY = 'liability', 'Liability'
        EQUITY = 'equity', 'Equity'
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'

    class Detail(models.TextChoices):
        CASH_BANK = 'cash_bank', 'Cash & bank'
        CURRENT_ASSET = 'current_asset', 'Current asset'
        FIXED_ASSET = 'fixed_asset', 'Fixed asset'
        OTHER_ASSET = 'other_asset', 'Other asset'
        CURRENT_LIABILITY = 'current_liability', 'Current liability'
        LONG_TERM_LIABILITY = 'long_term_liability', 'Long-term liability'
        EQUITY = 'equity', 'Equity'
        INCOME = 'income', 'Operating income'
        OTHER_INCOME = 'other_income', 'Other income'
        COST_OF_SALES = 'cost_of_sales', 'Cost of sales'
        EXPENSE = 'expense', 'Operating expense'
        OTHER_EXPENSE = 'other_expense', 'Other expense'

    DETAILS_BY_TYPE = {
        Type.ASSET: [Detail.CASH_BANK, Detail.CURRENT_ASSET, Detail.FIXED_ASSET, Detail.OTHER_ASSET],
        Type.LIABILITY: [Detail.CURRENT_LIABILITY, Detail.LONG_TERM_LIABILITY],
        Type.EQUITY: [Detail.EQUITY],
        Type.INCOME: [Detail.INCOME, Detail.OTHER_INCOME],
        Type.EXPENSE: [Detail.COST_OF_SALES, Detail.EXPENSE, Detail.OTHER_EXPENSE],
    }
    DEBIT_NORMAL = {Type.ASSET, Type.EXPENSE}

    code = models.CharField(max_length=20, unique=True, help_text='e.g. 1000. Accounts sort by code.')
    name = models.CharField(max_length=150)
    account_type = models.CharField(max_length=20, choices=Type.choices)
    detail_type = models.CharField(max_length=30, choices=Detail.choices)
    parent = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='children',
        help_text='Optional: show this account as a sub-account of another of the same type.',
    )
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, help_text='Inactive accounts keep their history but can\'t be used on new entries.')
    system_key = models.CharField(
        max_length=40, unique=True, null=True, blank=True, editable=False,
        help_text='Set on accounts the app posts to automatically; these can be renamed but not deleted or retyped.',
    )

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} · {self.name}'

    def get_absolute_url(self):
        return reverse('accounting:account_detail', args=[self.pk])

    @property
    def is_debit_normal(self):
        return self.account_type in self.DEBIT_NORMAL

    @property
    def is_bank(self):
        return self.detail_type == self.Detail.CASH_BANK

    def signed_balance(self, debit, credit):
        """Balance in this account's natural direction (positive = normal)."""
        return (debit - credit) if self.is_debit_normal else (credit - debit)

    def clean(self):
        if self.detail_type and self.account_type and self.detail_type not in self.DETAILS_BY_TYPE.get(self.account_type, []):
            raise ValidationError({'detail_type': 'That detail type doesn\'t belong to this account type.'})
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({'parent': 'An account can\'t be its own parent.'})
            if self.parent.account_type != self.account_type:
                raise ValidationError({'parent': 'A sub-account must have the same type as its parent.'})
            ancestor = self.parent
            while ancestor is not None:
                if ancestor.pk == self.pk:
                    raise ValidationError({'parent': 'That would create a loop of sub-accounts.'})
                ancestor = ancestor.parent

    @property
    def depth(self):
        depth, node = 0, self.parent
        while node is not None and depth < 10:
            depth, node = depth + 1, node.parent
        return depth


class JournalEntry(TimeStampedModel):
    """
    A balanced set of debits and credits on one date. Entries are either typed
    by an accountant (manual, transfer, opening balance) or generated from an
    income/expense record, which then owns it: those can only be changed by
    editing the record, so the books and the operational screens never disagree.
    """

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual journal'
        OPENING = 'opening', 'Opening balance'
        TRANSFER = 'transfer', 'Transfer'
        INCOME = 'income', 'Income record'
        EXPENSE = 'expense', 'Expense record'

    AUTO_SOURCES = {Source.INCOME, Source.EXPENSE}

    number = models.CharField(max_length=20, unique=True, blank=True)
    date = models.DateField()
    memo = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=60, blank=True, help_text='Receipt number, bank reference, etc.')
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    income_record = models.OneToOneField(
        'finance.IncomeRecord', on_delete=models.CASCADE, null=True, blank=True, related_name='journal_entry',
    )
    expense_record = models.OneToOneField(
        'finance.ExpenseRecord', on_delete=models.CASCADE, null=True, blank=True, related_name='journal_entry',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='journal_entries_created',
    )

    class Meta:
        ordering = ['-date', '-pk']
        verbose_name_plural = 'journal entries'

    def __str__(self):
        return self.number or f'Journal entry #{self.pk}'

    def get_absolute_url(self):
        return reverse('accounting:journal_detail', args=[self.pk])

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.number:
            self.number = f'JE-{self.date.year}-{self.pk:05d}'
            super().save(update_fields=['number'])

    @property
    def is_auto(self):
        return self.source in self.AUTO_SOURCES

    @property
    def total(self):
        return sum((line.debit for line in self.lines.all()), Decimal('0'))

    @property
    def source_record(self):
        return self.income_record or self.expense_record


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='lines')
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0'))
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0'))

    class Meta:
        ordering = ['pk']
        constraints = [
            # Each line is a debit OR a credit, never negative, never both, never empty.
            models.CheckConstraint(
                condition=Q(debit__gte=0, credit__gte=0) & (Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)),
                name='journalline_one_positive_side',
            ),
        ]

    def __str__(self):
        side = f'Dr {self.debit}' if self.debit else f'Cr {self.credit}'
        return f'{self.account} {side}'
