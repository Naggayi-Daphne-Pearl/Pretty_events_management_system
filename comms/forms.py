from django import forms

from core.forms import BootstrapModelForm

from .models import CommunicationLog


class CommunicationLogForm(BootstrapModelForm):
    class Meta:
        model = CommunicationLog
        fields = ['channel', 'direction', 'event', 'message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        # Only this customer's own events make sense here.
        self.fields['event'].queryset = customer.events.order_by('-event_date')
        self.fields['event'].empty_label = 'Not about a specific event'
