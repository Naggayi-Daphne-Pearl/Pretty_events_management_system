from django import forms

from core.forms import BootstrapModelForm

from .models import ExpenseCategory, ExpenseRecord, IncomeRecord


class ExpenseCategoryForm(BootstrapModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name']


class IncomeRecordForm(BootstrapModelForm):
    """Source is deliberately not a field here — it's always 'other' for a manual
    entry. 'Invoice Payment' is set automatically when a payment is recorded
    (see billing.views.invoice_add_payment), never chosen by hand, so offering
    it here would just invite duplicate/miscategorized income."""

    class Meta:
        model = IncomeRecord
        fields = ['amount', 'date', 'event', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }


class ExpenseRecordForm(BootstrapModelForm):
    class Meta:
        model = ExpenseRecord
        fields = ['amount', 'category', 'date', 'event', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }
