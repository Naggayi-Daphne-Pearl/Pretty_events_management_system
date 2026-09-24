import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import (
    AdminPasswordChangeForm, AuthenticationForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm,
)
from django.contrib.auth.models import Group

from .auth import clear_failed_logins, is_locked_out, record_failed_login

User = get_user_model()


class BootstrapFieldsMixin:
    """Adds Bootstrap form-control/form-select/form-check classes to every field automatically."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                # CheckboxSelectMultiple/RadioSelect subclass ChoiceWidget directly (not
                # Select/SelectMultiple), so they must be checked before that branch below.
                css_class = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = 'form-select'
            else:
                css_class = 'form-control'
            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = f'{existing} {css_class}'.strip()


class BootstrapModelForm(BootstrapFieldsMixin, forms.ModelForm):
    pass


def email_taken(email, exclude_pk=None):
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def unique_username_from_email(email):
    """Usernames still exist under the hood (Django requires one) but people log in
    with their email, so derive a unique one instead of asking for it."""
    base = re.sub(r'[^\w.@+-]', '', email.split('@')[0])[:140] or 'user'
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


class StaffAccountCreationForm(BootstrapFieldsMixin, forms.Form):
    """
    Creates a staff login from an email address. By default the person is emailed
    a link to set their own password (the admin never knows it). An admin can
    instead set a password now, e.g. when email isn't working yet.
    """

    email = forms.EmailField(required=True, help_text='They log in with this address.')
    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'), required=False,
        widget=forms.CheckboxSelectMultiple, label='Roles',
    )
    set_password_now = forms.BooleanField(
        required=False, label='Set a password for them now instead of emailing an invite',
    )
    password1 = forms.CharField(label='Password', required=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Confirm password', required=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.EMAIL_ENABLED:
            # No way to send an invite, so the admin sets the first password (they can
            # share it in person, and the staff member changes it from My Profile).
            del self.fields['set_password_now']
            self.fields['password1'].required = True
            self.fields['password2'].required = True
        # Show the rules up front: the most common "can't create staff" cause is a password
        # quietly rejected for being short, common, all digits or too like their email.
        self.fields['password1'].help_text = (
            'At least 8 characters, not all numbers, not a common password, and not too similar to their email.'
        )

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if email_taken(email):
            raise forms.ValidationError('Another login already uses this email address.')
        return email

    def clean(self):
        cleaned = super().clean()
        if not settings.EMAIL_ENABLED:
            cleaned['set_password_now'] = True
        if cleaned.get('set_password_now'):
            p1, p2 = cleaned.get('password1'), cleaned.get('password2')
            if not p1:
                self.add_error('password1', 'Enter a password, or untick "set a password now" to email an invite.')
            elif p1 != p2:
                self.add_error('password2', 'The two passwords don\'t match.')
            else:
                try:
                    password_validation.validate_password(p1)
                except forms.ValidationError as error:
                    self.add_error('password1', error)
        return cleaned

    @property
    def sends_invite(self):
        return not self.cleaned_data.get('set_password_now')

    def save(self):
        email = self.cleaned_data['email']
        user = User(username=unique_username_from_email(email), email=email)
        if self.sends_invite:
            user.set_unusable_password()
        else:
            user.set_password(self.cleaned_data['password1'])
        user.save()
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
        self.fields['email'].help_text = 'They log in with this address.'
        if self.instance.pk:
            self.fields['roles'].initial = self.instance.groups.all()

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if email_taken(email, exclude_pk=self.instance.pk):
            raise forms.ValidationError('Another login already uses this email address.')
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data['roles'])
        return user


class StaffSetPasswordForm(BootstrapFieldsMixin, AdminPasswordChangeForm):
    """Lets a superuser set a new password for a staff account directly —
    no old password required, no email-based reset flow needed for this MVP."""


class SelfPasswordChangeForm(BootstrapFieldsMixin, PasswordChangeForm):
    """Self-service password change — unlike StaffSetPasswordForm, this requires
    the user's own current password (it's for changing your own, not resetting
    someone else's)."""


class EmailAuthenticationForm(BootstrapFieldsMixin, AuthenticationForm):
    """Login by email, with a lockout after repeated failures (see core.auth)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Incorrect email or password.',
        'locked_out': (
            'Too many failed attempts. For security, logging in with this email is paused for '
            '%(minutes)s minutes. You can reset your password in the meantime.'
        ),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Email'
        self.fields['username'].widget.attrs.update({'autocomplete': 'email', 'inputmode': 'email', 'autofocus': True})

    def clean(self):
        identifier = self.cleaned_data.get('username')
        if identifier and is_locked_out(identifier):
            raise forms.ValidationError(
                self.error_messages['locked_out'], code='locked_out',
                params={'minutes': settings.LOGIN_LOCKOUT_MINUTES},
            )
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            if identifier:
                record_failed_login(identifier)
            raise
        clear_failed_logins(identifier, self.get_user().email, self.get_user().username)
        return cleaned


class EmailPasswordResetForm(BootstrapFieldsMixin, PasswordResetForm):
    """
    Django's reset form, except invited staff who haven't set a password yet can use
    "Forgot password" too (Django normally skips accounts without a usable password).
    Django itself logs a mail-server failure instead of crashing, and the visitor
    always sees the same "if an account exists…" page either way.
    """

    def get_users(self, email):
        return (
            u for u in User._default_manager.filter(email__iexact=email, is_active=True)
            if u.email and u.email.lower() == email.lower()
        )


class EmailSetPasswordForm(BootstrapFieldsMixin, SetPasswordForm):
    """New-password form used by both the reset link and the staff invite link."""

    def save(self, commit=True):
        user = super().save(commit=commit)
        clear_failed_logins(user.email, user.username)
        return user
