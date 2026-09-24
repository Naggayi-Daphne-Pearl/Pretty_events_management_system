from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import redirect, render

from .activity import log_activity


def confirm_and_delete(request, obj, *, cancel_url, success_url, blockers=(), also_deleted=(), hint='', after_delete=None):
    """
    Shared "are you sure?" + delete flow for business records.

    `blockers` lists linked records that make deletion unsafe (e.g. an invoice's
    payments). While any exist the page only explains what's linked and never
    offers a Delete button, so financial history can't be wiped by accident.
    `also_deleted` lists harmless child records removed along with it, shown so
    the user knows exactly what the delete covers. `after_delete`, if given, runs
    inside the same transaction right after the delete (e.g. to deal with a
    linked login), so either everything happens or nothing does.
    """
    blockers = [b for b in blockers if b]
    also_deleted = [a for a in also_deleted if a]
    verbose_name = obj._meta.verbose_name
    label = str(obj)

    if request.method == 'POST' and not blockers:
        try:
            with transaction.atomic():
                obj.delete()
                if after_delete:
                    after_delete()
        except ProtectedError:
            # Something got linked between the page loading and the POST; the DB-level
            # PROTECT caught it. Fall through and re-render with a clear message.
            messages.error(request, f'This {verbose_name} was just linked to other records and can\'t be deleted.')
        else:
            log_activity(request, f'{obj._meta.model_name}.deleted', f'Deleted {verbose_name} "{label}"')
            messages.success(request, f'{verbose_name.capitalize()} "{label}" deleted.')
            return redirect(success_url)

    return render(request, 'partials/confirm_delete.html', {
        'object': obj,
        'label': label,
        'verbose_name': verbose_name,
        'blockers': blockers,
        'also_deleted': also_deleted,
        'hint': hint,
        'cancel_url': cancel_url,
    })


def count_label(count, singular, plural=None):
    """'1 event' / '3 events', or '' when count is 0 (dropped by confirm_and_delete)."""
    if not count:
        return ''
    word = singular if count == 1 else (plural or f'{singular}s')
    return f'{count:,} {word}'
