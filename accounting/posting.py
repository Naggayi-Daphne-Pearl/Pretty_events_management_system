"""
Cash-basis auto-posting: money actually received or paid is what hits the books.
- Income record (incl. every invoice payment): Dr the bank/cash account it went
  into, Cr the income account.
- Expense record: Dr the expense account (from its category), Cr the bank/cash
  account it was paid from.
Invoices themselves post nothing (cash basis); what clients still owe is on the
Outstanding Payments report.
"""
from django.db import transaction

from .chart import system_account
from .models import JournalEntry
from .services import save_entry

# Where each payment method's money lands if the record doesn't say.
METHOD_TO_ACCOUNT = {
    'cash': 'cash',
    'mobile_money': 'mobile_money',
    'bank_transfer': 'bank',
    'cheque': 'bank',
    'other': 'cash',
}


def deposit_account_for(income_record):
    if income_record.deposit_account_id:
        return income_record.deposit_account
    payment = income_record.payment
    return system_account(METHOD_TO_ACCOUNT.get(payment.method if payment else 'cash', 'cash'))


def income_account_for(income_record):
    if income_record.income_account_id:
        return income_record.income_account
    return system_account('event_income' if income_record.source == 'invoice_payment' else 'other_income')


def expense_account_for(expense_record):
    """The account chosen on the expense, else its category's account, else General Expenses."""
    if expense_record.expense_account_id:
        return expense_record.expense_account
    category_account = getattr(expense_record.category, 'account', None)
    return category_account or system_account('general_expense')


def paid_from_account_for(expense_record):
    return expense_record.paid_from_account or system_account('cash')


@transaction.atomic
def sync_income_record(record):
    entry = JournalEntry.objects.filter(income_record=record).first() or JournalEntry(
        income_record=record, source=JournalEntry.Source.INCOME, created_by=record.recorded_by,
    )
    if not record.amount or record.amount <= 0:
        if entry.pk:
            entry.delete()
        return None
    entry.date = record.date
    entry.memo = record.description or 'Income'
    entry.reference = record.payment.receipt.number if record.payment_id and hasattr(record.payment, 'receipt') else ''
    return save_entry(entry, [
        {'account': deposit_account_for(record), 'debit': record.amount, 'description': entry.memo, 'allow_inactive': True},
        {'account': income_account_for(record), 'credit': record.amount, 'description': entry.memo, 'allow_inactive': True},
    ])


@transaction.atomic
def sync_expense_record(record):
    entry = JournalEntry.objects.filter(expense_record=record).first() or JournalEntry(
        expense_record=record, source=JournalEntry.Source.EXPENSE, created_by=record.recorded_by,
    )
    if not record.amount or record.amount <= 0:
        if entry.pk:
            entry.delete()
        return None
    entry.date = record.date
    entry.memo = record.description or f'Expense: {record.category}'
    return save_entry(entry, [
        {'account': expense_account_for(record), 'debit': record.amount, 'description': entry.memo, 'allow_inactive': True},
        {'account': paid_from_account_for(record), 'credit': record.amount, 'description': entry.memo, 'allow_inactive': True},
    ])


def post_history(rebuild=False):
    """Post every income/expense record that has no journal entry yet (or all, if rebuild).
    Returns (income_posted, expenses_posted)."""
    from finance.models import ExpenseRecord, IncomeRecord
    incomes = IncomeRecord.objects.select_related('payment__receipt', 'deposit_account', 'income_account')
    expenses = ExpenseRecord.objects.select_related('category__account', 'expense_account', 'paid_from_account')
    if not rebuild:
        incomes = incomes.filter(journal_entry__isnull=True)
        expenses = expenses.filter(journal_entry__isnull=True)
    income_count = sum(1 for r in incomes if sync_income_record(r))
    expense_count = sum(1 for r in expenses if sync_expense_record(r))
    return income_count, expense_count
