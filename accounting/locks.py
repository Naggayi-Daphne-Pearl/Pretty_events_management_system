"""Period locking: see accounting.models.PeriodClose."""
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import JournalEntry, PeriodClose


def locked_through():
    """The date the books are closed through, or None if nothing is closed."""
    latest = PeriodClose.objects.order_by('-created_at', '-pk').first()
    return latest.closed_through if latest else None


def is_locked(day):
    lock = locked_through()
    return bool(lock and day and day <= lock)


def lock_message(day):
    return (f'The books are closed through {locked_through():%d %b %Y}, so nothing dated {day:%d %b %Y} can be '
            'added or changed. Date it after that, or ask an accountant to reopen the period.')


def check_open(day):
    """Raise ValidationError if `day` falls in a closed period."""
    if is_locked(day):
        raise ValidationError(lock_message(day))


class OpenPeriodFormMixin:
    """For forms that create dated money records: `locked_date_fields` must fall in an open period."""
    locked_date_fields = ('date',)

    def clean(self):
        cleaned = super().clean()
        for name in self.locked_date_fields:
            day = cleaned.get(name)
            if day and is_locked(day):
                self.add_error(name, lock_message(day))
        return cleaned


@receiver(pre_delete, sender=JournalEntry, dispatch_uid='accounting.protect_closed_period')
def protect_closed_period(sender, instance, **kwargs):
    # Covers direct deletes and cascades (e.g. deleting an income record deletes its entry).
    check_open(instance.date)
