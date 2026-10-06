from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from accounting.locks import OpenPeriodFormMixin
from core.forms import BootstrapFieldsMixin, BootstrapModelForm

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
    """
    A row removed in the browser posts none of its fields. Report it as unchanged,
    so together with BaseLineItemFormSet it is skipped rather than failing as a
    blank, required row.
    """

    def has_changed(self):
        if self.is_bound and not any(self.add_prefix(name) in self.data for name in self.fields):
            return False
        return super().has_changed()


class BaseLineItemFormSet(forms.BaseInlineFormSet):
    """
    New rows are optional: a blank row (like the one the editor starts with) or a
    removed one is ignored instead of blocking the save. At least one real line is
    still required, checked here rather than by min_num, which would force row 0 to
    be filled in even after it was removed.
    """

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        if i >= self.initial_form_count():
            form.empty_permitted = True
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not kept:
            raise forms.ValidationError('Add at least one line item.')


class QuotationLineItemForm(LineItemFormMixin, BootstrapModelForm):
    class Meta:
        model = QuotationLineItem
        fields = ['equipment_item', 'description', 'quantity', 'unit_price']
        labels = {'equipment_item': 'Inventory item'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['equipment_item'].empty_label = '— Not from inventory (labor, misc., etc.) —'


# min_num=1 only makes the editor start with one blank row; BaseLineItemFormSet
# does the "at least one line" check.
QuotationLineItemFormSet = inlineformset_factory(
    Quotation, QuotationLineItem, form=QuotationLineItemForm, formset=BaseLineItemFormSet, extra=0,
    can_delete=True, min_num=1,
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


class InvoiceLineItemForm(LineItemFormMixin, BootstrapModelForm):
    class Meta:
        model = InvoiceLineItem
        fields = ['equipment_item', 'description', 'quantity', 'unit_price']
        labels = {'equipment_item': 'Inventory item'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['equipment_item'].empty_label = '— Not from inventory (labor, misc., etc.) —'


class BaseInvoiceLineItemFormSet(BaseLineItemFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or not self.instance.pk:
            return
        paid = self.instance.amount_paid
        if not paid:
            return
        new_total = Decimal('0')
        for form in self.forms:
            data = getattr(form, 'cleaned_data', None) or {}
            if not data or data.get('DELETE'):
                continue
            quantity, price = data.get('quantity') or 0, data.get('unit_price') or 0
            new_total += (Decimal(quantity) * Decimal(price)).quantize(Decimal('0.01'))
        if new_total < paid:
            raise forms.ValidationError(
                f'The new total ({new_total:,.0f}) is less than the {paid:,.0f} already paid on this invoice. '
                'Keep the total at or above the amount paid; if the client is owed money back, record that separately.'
            )


InvoiceLineItemFormSet = inlineformset_factory(
    Invoice, InvoiceLineItem, form=InvoiceLineItemForm, formset=BaseInvoiceLineItemFormSet, extra=0, can_delete=True,
    min_num=1,
)


class EmailDocumentForm(BootstrapFieldsMixin, forms.Form):
    to_email = forms.EmailField(label='Send to')
    message = forms.CharField(label='Message', widget=forms.Textarea(attrs={'rows': 6}))


class PaymentForm(OpenPeriodFormMixin, BootstrapModelForm):
    locked_date_fields = ('paid_at',)

    class Meta:
        model = Payment
        fields = ['amount', 'method', 'paid_at', 'reference_number', 'notes']
        widgets = {
            'paid_at': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.TextInput(attrs={'placeholder': 'What this payment is for, e.g. "2 parasols 5x5"'}),
            'reference_number': forms.TextInput(attrs={'placeholder': 'Cheque no. / mobile money ref (optional)'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Payment amount must be greater than zero.')
        return amount
