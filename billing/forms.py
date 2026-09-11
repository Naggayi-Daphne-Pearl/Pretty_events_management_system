from django import forms
from django.forms import inlineformset_factory

from core.forms import BootstrapModelForm

from .models import Invoice, InvoiceLineItem, Payment, Quotation, QuotationLineItem


class QuotationForm(BootstrapModelForm):
    class Meta:
        model = Quotation
        fields = ['status', 'valid_until', 'notes']
        widgets = {
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class LineItemFormMixin:
    """Bootstrap-styled line item forms, laid out as a compact row."""


class QuotationLineItemForm(BootstrapModelForm):
    class Meta:
        model = QuotationLineItem
        fields = ['description', 'quantity', 'unit_price']


QuotationLineItemFormSet = inlineformset_factory(
    Quotation, QuotationLineItem, form=QuotationLineItemForm, extra=1, can_delete=True,
)


class InvoiceForm(BootstrapModelForm):
    class Meta:
        model = Invoice
        fields = ['status', 'issue_date', 'due_date', 'notes']
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class InvoiceLineItemForm(BootstrapModelForm):
    class Meta:
        model = InvoiceLineItem
        fields = ['description', 'quantity', 'unit_price']


InvoiceLineItemFormSet = inlineformset_factory(
    Invoice, InvoiceLineItem, form=InvoiceLineItemForm, extra=1, can_delete=True,
)


class PaymentForm(BootstrapModelForm):
    class Meta:
        model = Payment
        fields = ['amount', 'method', 'paid_at', 'notes']
        widgets = {
            'paid_at': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Payment amount must be greater than zero.')
        return amount
