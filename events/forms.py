from django import forms

from core.client import event_field_hidden, terms
from core.forms import BootstrapModelForm
from core.phone import to_international
from customers.models import Customer

from .models import Event


class EventForm(BootstrapModelForm):
    # Quick-add: lets a brand-new client be captured on the event form itself instead
    # of a separate trip to "New Customer" first. Only offered when creating an event.
    new_customer_name = forms.CharField(label='New customer name', max_length=200, required=False)
    new_customer_phone = forms.CharField(label='New customer phone', max_length=30, required=False)
    new_customer_email = forms.EmailField(label='New customer email', required=False)

    NEW_CUSTOMER_FIELDS = ('new_customer_name', 'new_customer_phone', 'new_customer_email')

    class Meta:
        model = Event
        fields = ['customer', 'event_type', 'status', 'event_date', 'end_date', 'venue', 'guest_count', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'event_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, allow_new_customer=False, **kwargs):
        super().__init__(*args, **kwargs)
        words = terms()
        for name in ('venue', 'guest_count', 'end_date'):
            if event_field_hidden(name):
                del self.fields[name]
        self.fields['customer'].label = words['Customer']
        self.fields['event_type'].label = f"{words['Event']} type"
        self.fields['event_type'].help_text = words['event_type_help']
        self.fields['event_date'].label = words['event_date']
        if 'end_date' in self.fields:
            self.fields['end_date'].label = words['end_date']
            self.fields['end_date'].help_text = words['end_date_help']
        if 'new_customer_name' in self.fields:
            for suffix in ('name', 'phone', 'email'):
                self.fields[f'new_customer_{suffix}'].label = f"New {words['customer']} {suffix}"
        self.allow_new_customer = allow_new_customer
        if allow_new_customer:
            self.fields['customer'].required = False
        else:
            for name in self.NEW_CUSTOMER_FIELDS:
                del self.fields[name]

    def clean(self):
        cleaned = super().clean()
        if not self.allow_new_customer or cleaned.get('customer'):
            return cleaned
        name = (cleaned.get('new_customer_name') or '').strip()
        phone = (cleaned.get('new_customer_phone') or '').strip()
        if not name or not phone:
            words = terms()
            self.add_error('customer', f"Pick an existing {words['customer']}, or enter the new {words['customer']}'s name and phone.")
            return cleaned
        normalized = to_international(phone)
        for existing in Customer.objects.only('pk', 'name', 'phone'):
            if to_international(existing.phone) == normalized:
                self.add_error(
                    'new_customer_phone',
                    f'{existing.name} already has this phone number. Search for them above instead of adding a duplicate.',
                )
                break
        return cleaned

    def save_new_customer(self, created_by):
        """Create the quick-added customer (if any) and attach it to the event. Call before save()."""
        if not self.allow_new_customer or self.cleaned_data.get('customer'):
            return None
        customer = Customer.objects.create(
            name=self.cleaned_data['new_customer_name'].strip(),
            phone=self.cleaned_data['new_customer_phone'].strip(),
            email=self.cleaned_data.get('new_customer_email') or '',
            created_by=created_by,
        )
        self.instance.customer = customer
        return customer
