from django import forms

from core.forms import BootstrapModelForm

from .models import CommunicationLog


class CommunicationLogForm(BootstrapModelForm):
    class Meta:
        model = CommunicationLog
        fields = ['channel', 'direction', 'message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 3}),
        }
