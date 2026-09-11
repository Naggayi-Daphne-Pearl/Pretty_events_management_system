from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AdminPasswordChangeForm, UserCreationForm
from django.contrib.auth.models import Group

User = get_user_model()


class BootstrapFieldsMixin:
    """Adds Bootstrap form-control/form-select/form-check classes to every field automatically."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css_class = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = 'form-select'
            else:
                css_class = 'form-control'
            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = f'{existing} {css_class}'.strip()


class BootstrapModelForm(BootstrapFieldsMixin, forms.ModelForm):
    pass


class StaffAccountCreationForm(BootstrapFieldsMixin, UserCreationForm):
    """Creates a staff login: username, a REQUIRED email, a password the admin sets now
    (not an email-confirmation sign-up flow), and which role(s) to put them in."""

    email = forms.EmailField(required=True)
    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'), required=False,
        widget=forms.CheckboxSelectMultiple, label='Roles',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data['roles'])
        return user


class StaffAccountUpdateForm(BootstrapFieldsMixin, forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'), required=False,
        widget=forms.CheckboxSelectMultiple, label='Roles',
    )

    class Meta:
        model = User
        fields = ('email', 'is_active', 'roles')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        if self.instance.pk:
            self.fields['roles'].initial = self.instance.groups.all()

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data['roles'])
        return user


class StaffSetPasswordForm(BootstrapFieldsMixin, AdminPasswordChangeForm):
    """Lets a superuser set a new password for a staff account directly —
    no old password required, no email-based reset flow needed for this MVP."""
