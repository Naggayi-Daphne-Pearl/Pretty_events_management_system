from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.forms import BootstrapFieldsMixin, BootstrapModelForm

from .models import Account, JournalEntry
from .services import validate_lines


def active_accounts():
    return Account.objects.filter(is_active=True).order_by('code')


class AccountForm(BootstrapModelForm):
    class Meta:
        model = Account
        fields = ['code', 'name', 'account_type', 'detail_type', 'parent', 'description', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].queryset = Account.objects.exclude(pk=self.instance.pk).order_by('code')
        self.fields['parent'].required = False
        # Changing the type of an account that already has entries (or that the app
        # posts to) would silently flip the meaning of its history. Lock it.
        if self.instance.pk and (self.instance.system_key or self.instance.lines.exists()):
            self.fields['account_type'].disabled = True
            self.fields['account_type'].help_text = 'Locked: this account already has entries or is used for automatic posting.'
        if self.instance.system_key:
            self.fields['is_active'].disabled = True
            self.fields['is_active'].help_text = 'The app posts to this account automatically, so it must stay active.'


class JournalEntryForm(BootstrapModelForm):
    class Meta:
        model = JournalEntry
        fields = ['date', 'source', 'reference', 'memo']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'})}
        labels = {'source': 'Type', 'memo': 'Narration'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source'].choices = [
            (JournalEntry.Source.MANUAL, 'Manual journal'), (JournalEntry.Source.OPENING, 'Opening balance'),
        ]
        if not self.instance.pk and not self.initial.get('date'):
            # (the unsaved instance puts date=None into initial, so setdefault wouldn't work)
            self.initial['date'] = timezone.localdate()


class JournalLineForm(BootstrapFieldsMixin, forms.Form):
    account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False)
    description = forms.CharField(max_length=255, required=False)
    debit = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0, required=False)
    credit = forms.DecimalField(max_digits=16, decimal_places=2, min_value=0, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = active_accounts()
        self.fields['debit'].widget.attrs.update({'class': 'form-control text-end jl-debit', 'step': '0.01'})
        self.fields['credit'].widget.attrs.update({'class': 'form-control text-end jl-credit', 'step': '0.01'})

    def clean(self):
        cleaned = super().clean()
        debit, credit = cleaned.get('debit') or Decimal('0'), cleaned.get('credit') or Decimal('0')
        if (debit or credit) and not cleaned.get('account'):
            self.add_error('account', 'Choose an account for this amount.')
        if debit and credit:
            raise ValidationError('A line is a debit or a credit, not both.')
        return cleaned


class BaseJournalLineFormSet(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        self.lines = [
            {'account': f.cleaned_data['account'], 'description': f.cleaned_data.get('description') or '',
             'debit': f.cleaned_data.get('debit') or 0, 'credit': f.cleaned_data.get('credit') or 0}
            for f in self.forms
            if f.cleaned_data and f.cleaned_data.get('account') and not f.cleaned_data.get('DELETE')
        ]
        validate_lines(self.lines)


JournalLineFormSet = forms.formset_factory(JournalLineForm, formset=BaseJournalLineFormSet, extra=0, min_num=2, can_delete=True)


def lines_initial(entry):
    return [{'account': l.account, 'description': l.description, 'debit': l.debit or None, 'credit': l.credit or None}
            for l in entry.lines.select_related('account')]


class TransferForm(BootstrapFieldsMixin, forms.Form):
    """Move money between two cash/bank/mobile-money accounts (e.g. banking the day's cash)."""
    from_account = forms.ModelChoiceField(queryset=Account.objects.none(), label='From')
    to_account = forms.ModelChoiceField(queryset=Account.objects.none(), label='To')
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal('0.01'))
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=timezone.localdate)
    reference = forms.CharField(max_length=60, required=False)
    memo = forms.CharField(max_length=255, required=False, label='Narration')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        banks = active_accounts().filter(detail_type=Account.Detail.CASH_BANK)
        self.fields['from_account'].queryset = banks
        self.fields['to_account'].queryset = banks

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('from_account') and cleaned.get('from_account') == cleaned.get('to_account'):
            raise ValidationError('Choose two different accounts.')
        return cleaned


class AccountEntryForm(BootstrapFieldsMixin, forms.Form):
    """
    Quick manual entry against one account, from that account's ledger page. The
    other side goes to `offset_account`, so the result is always a balanced
    two-line journal. For entries split across several accounts, use the full
    journal form instead.
    """
    side = forms.ChoiceField(widget=forms.RadioSelect, label='This account is')
    amount = forms.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal('0.01'))
    offset_account = forms.ModelChoiceField(queryset=Account.objects.none(), label='Other account')
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=timezone.localdate)
    source = forms.ChoiceField(
        label='Type', initial=JournalEntry.Source.MANUAL,
        choices=[(JournalEntry.Source.MANUAL, 'Manual journal'), (JournalEntry.Source.OPENING, 'Opening balance')],
    )
    reference = forms.CharField(max_length=60, required=False)
    memo = forms.CharField(max_length=255, required=False, label='Narration')

    def __init__(self, *args, account, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        # Say in plain words what each side does to *this* account.
        up, down = ('increases', 'decreases') if account.is_debit_normal else ('decreases', 'increases')
        self.fields['side'].choices = [
            ('debit', f'Debited ({up} {account.name})'),
            ('credit', f'Credited ({down} {account.name})'),
        ]
        self.fields['offset_account'].queryset = active_accounts().exclude(pk=account.pk)
        self.fields['offset_account'].help_text = (
            'Where the other side goes, e.g. Bank Account, Owner\'s Capital, or Opening Balance Equity for opening balances.'
        )

    def lines(self):
        d = self.cleaned_data
        memo = d['memo'] or f'Entry on {self.account.name}'
        this = {'account': self.account, 'description': memo, d['side']: d['amount']}
        other_side = 'credit' if d['side'] == 'debit' else 'debit'
        other = {'account': d['offset_account'], 'description': memo, other_side: d['amount']}
        return [this, other]
