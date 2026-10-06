from django import forms
from django.db.models import Q, Value
from django.db.models.functions import Replace

from core.forms import BootstrapModelForm
from core.phone import to_international

from .models import Customer


def customers_with_phone(phone, exclude_pk=None):
    """Existing customers whose phone or alt phone is this number, however it was typed."""
    target = to_international(phone)
    if len(target) < 7:
        return []
    tail = target[-9:]

    def bare(field):
        return Replace(Replace(Replace(field, Value(' '), Value('')), Value('-'), Value('')), Value('+'), Value(''))

    candidates = Customer.objects.annotate(p=bare('phone'), a=bare('alt_phone')).filter(
        Q(p__endswith=tail) | Q(a__endswith=tail),
    ).exclude(pk=exclude_pk)
    return [c for c in candidates if target in (to_international(c.phone), to_international(c.alt_phone))]


class CustomerForm(BootstrapModelForm):
    confirm_duplicate = forms.BooleanField(
        required=False, label='This is a different person: save anyway',
    )

    class Meta:
        model = Customer
        fields = ['name', 'phone', 'alt_phone', 'email', 'address', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []

    def clean(self):
        cleaned = super().clean()
        phone = cleaned.get('phone')
        phone_changed = 'phone' in self.changed_data or not self.instance.pk
        if phone and phone_changed and not cleaned.get('confirm_duplicate'):
            self.duplicates = customers_with_phone(phone, exclude_pk=self.instance.pk)
            if self.duplicates:
                raise forms.ValidationError(
                    'A customer with this phone number already exists. Open their record instead, '
                    'or tick the box below if this really is someone else.'
                )
        return cleaned
