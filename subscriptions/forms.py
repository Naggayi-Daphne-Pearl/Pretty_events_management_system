from django import forms
from django.utils import timezone

from billing.forms import TaxChoiceMixin
from core.client import terms
from core.forms import BootstrapModelForm
from events.models import Event

from .models import Subscription


class SubscriptionForm(BootstrapModelForm):
    class Meta:
        model = Subscription
        fields = ['event', 'name', 'amount', 'interval', 'start_date', 'invoice_days_before', 'tax_group',
                  'is_active', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        words = terms()
        event = self.fields['event']
        event.label = words['Event']
        event.queryset = Event.objects.exclude(status=Event.Status.CANCELLED).select_related('customer').order_by(
            'customer__name', '-event_date')
        event.label_from_instance = lambda e: f'{e.customer.name} · {e.event_type} ({e.event_date:%b %Y})'
        event.help_text = f"The invoices go on this {words['event']}, with its other invoices."
        # The tax choice works like a quotation's, without capturing a rate (each invoice does that).
        tax = self.fields['tax_group']
        tax.queryset = TaxChoiceMixin.tax_queryset(self.instance.tax_group_id)
        tax.empty_label = 'No tax'
        if self.instance.pk and self.instance.periods_invoiced:
            # Moving the start would re-number periods already invoiced.
            self.fields['start_date'].disabled = True
            self.fields['start_date'].help_text = 'Fixed once the first invoice has been raised.'

    def clean_start_date(self):
        start = self.cleaned_data.get('start_date')
        if start and 'start_date' in self.changed_data and start < timezone.localdate():
            # A past start would raise an invoice for every period since then, all at once.
            raise forms.ValidationError(
                'This date has passed. Enter the next date this charge is due; '
                'bill any earlier periods with an ordinary invoice.'
            )
        return start
