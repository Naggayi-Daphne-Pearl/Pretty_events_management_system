from django import forms

from core.forms import BootstrapModelForm

from .models import EquipmentIssue, EquipmentItem, EquipmentReturn


class EquipmentItemForm(BootstrapModelForm):
    class Meta:
        model = EquipmentItem
        fields = ['name', 'category', 'total_quantity', 'unit', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class EquipmentIssueForm(BootstrapModelForm):
    class Meta:
        model = EquipmentIssue
        fields = ['equipment_item', 'quantity_issued', 'issued_at', 'expected_return_date', 'notes']
        widgets = {
            'issued_at': forms.DateInput(attrs={'type': 'date'}),
            'expected_return_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get('equipment_item')
        qty = cleaned.get('quantity_issued')
        if item and qty:
            if qty > item.available_quantity:
                raise forms.ValidationError(
                    f'Only {item.available_quantity} {item.unit} of {item.name} are currently available.'
                )
        return cleaned


class EquipmentReturnForm(BootstrapModelForm):
    class Meta:
        model = EquipmentReturn
        fields = ['quantity_returned', 'returned_at', 'condition_notes']
        widgets = {
            'returned_at': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, issue=None, **kwargs):
        self.issue = issue
        super().__init__(*args, **kwargs)

    def clean_quantity_returned(self):
        qty = self.cleaned_data['quantity_returned']
        if self.issue and qty > self.issue.quantity_outstanding:
            raise forms.ValidationError(
                f'Only {self.issue.quantity_outstanding} are still outstanding on this issue.'
            )
        return qty
