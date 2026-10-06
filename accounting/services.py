from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .locks import check_open
from .models import JournalEntry, JournalLine

CENT = Decimal('0.01')


def validate_lines(lines):
    """`lines` is a list of dicts with account, debit, credit (and optional description)."""
    lines = [l for l in lines if (l.get('debit') or 0) or (l.get('credit') or 0)]
    if len(lines) < 2:
        raise ValidationError('A journal entry needs at least two lines.')
    for line in lines:
        debit, credit = Decimal(line.get('debit') or 0), Decimal(line.get('credit') or 0)
        if debit < 0 or credit < 0:
            raise ValidationError('Amounts can\'t be negative. Use the other column instead.')
        if debit and credit:
            raise ValidationError('Each line is either a debit or a credit, not both.')
        if not line['account'].is_active and not line.get('allow_inactive'):
            raise ValidationError(f'"{line["account"]}" is inactive and can\'t be used on new entries.')
    total_debit = sum((Decimal(l.get('debit') or 0) for l in lines), Decimal('0')).quantize(CENT)
    total_credit = sum((Decimal(l.get('credit') or 0) for l in lines), Decimal('0')).quantize(CENT)
    if total_debit != total_credit:
        raise ValidationError(
            f'Debits ({total_debit:,.2f}) and credits ({total_credit:,.2f}) must be equal. '
            f'Difference: {abs(total_debit - total_credit):,.2f}.'
        )
    return lines


@transaction.atomic
def save_entry(entry, lines):
    """
    The only way journal lines get written: validates the entry balances, then
    replaces the entry's lines. Raises ValidationError (nothing saved) if not.
    """
    lines = validate_lines(lines)
    check_open(entry.date)
    if entry.pk:
        original = JournalEntry.objects.filter(pk=entry.pk).values_list('date', flat=True).first()
        check_open(original)
    entry.save()
    entry.lines.all().delete()
    JournalLine.objects.bulk_create([
        JournalLine(
            entry=entry, account=l['account'], description=l.get('description', '')[:255],
            debit=Decimal(l.get('debit') or 0).quantize(CENT), credit=Decimal(l.get('credit') or 0).quantize(CENT),
        )
        for l in lines
    ])
    return entry


@transaction.atomic
def reverse_entry(entry, *, date, user):
    """
    Cancel `entry` with a new entry that swaps every debit and credit, dated `date`
    (which must be in an open period). The original stays untouched, so the trail
    shows what was posted, and who reversed it when.
    """
    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if not entry.can_be_reversed:
        raise ValidationError(f'{entry.number} can\'t be reversed.')
    reversal = JournalEntry(
        date=date, source=JournalEntry.Source.REVERSAL, reverses=entry, created_by=user,
        memo=f'Reversal of {entry.number}' + (f': {entry.memo}' if entry.memo else ''),
        reference=entry.number,
    )
    return save_entry(reversal, [
        {'account': line.account, 'description': line.description, 'debit': line.credit, 'credit': line.debit,
         'allow_inactive': True}
        for line in entry.lines.select_related('account')
    ])
