from django import forms

from core.forms import BootstrapModelForm

from .models import Customer


class CustomerForm(BootstrapModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'alt_phone', 'email', 'address', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
