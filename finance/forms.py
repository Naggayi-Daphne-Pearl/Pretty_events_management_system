from django import forms

from core.forms import BootstrapModelForm

from .models import ExpenseCategory, ExpenseRecord, IncomeRecord


class ExpenseCategoryForm(BootstrapModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name', 'account']
        labels = {'account': 'Expense account'}


class IncomeRecordForm(BootstrapModelForm):
    """Source is deliberately not a field here — it's always 'other' for a manual
    entry. 'Invoice Payment' is set automatically when a payment is recorded
    (see billing.views.invoice_add_payment), never chosen by hand, so offering
    it here would just invite duplicate/miscategorized income."""

    class Meta:
        model = IncomeRecord
        fields = ['amount', 'date', 'deposit_account', 'income_account', 'event', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['deposit_account'].empty_label = 'Cash on Hand (default)'
        self.fields['income_account'].empty_label = 'Other Income (default)'


class ExpenseRecordForm(BootstrapModelForm):
    class Meta:
        model = ExpenseRecord
        fields = ['amount', 'category', 'expense_account', 'date', 'paid_from_account', 'event', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounting.models import Account
        field = self.fields['expense_account']
        # Every active expense ledger account, grouped the way the income statement groups them.
        field.queryset = Account.objects.filter(account_type='expense', is_active=True).order_by('code')
        field.empty_label = 'Use the category\'s account (General Expenses if none)'
        field.label_from_instance = lambda a: f'{a.code} · {a.name} ({a.get_detail_type_display()})'
        self.fields['paid_from_account'].empty_label = 'Cash on Hand (default)'

    def category_accounts(self):
        """{category_id: account_id} so the form can pre-select the category's ledger account."""
        return {str(c.pk): c.account_id for c in ExpenseCategory.objects.exclude(account=None).only('pk', 'account')}
