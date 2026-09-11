from django import forms

from core.forms import BootstrapModelForm

from .models import ExpenseRecord, IncomeRecord


class IncomeRecordForm(BootstrapModelForm):
    class Meta:
        model = IncomeRecord
        fields = ['amount', 'source', 'date', 'event', 'description']
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
