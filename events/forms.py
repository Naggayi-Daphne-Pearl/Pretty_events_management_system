from django import forms

from core.forms import BootstrapModelForm

from .models import Event


class EventForm(BootstrapModelForm):
    class Meta:
        model = Event
        fields = ['customer', 'event_type', 'status', 'event_date', 'end_date', 'venue', 'guest_count', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'event_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
