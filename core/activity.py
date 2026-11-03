from .models import ActivityLog


def log_activity(request, action, description):
    ActivityLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        description=description,
    )


def display_name(instance):
    """The record type in the business's own words: 'project' rather than 'event', and so on."""
    from .client import terms
    name = instance._meta.verbose_name
    words = terms()
    return {'event': words['event'], 'customer': words['customer'],
            'event assignment': f"{words['event']} assignment"}.get(name, name)


def log_model_activity(request, instance, verb, extra=''):
    """
    Shorthand for the common "created/updated <this record>" case — used across
    customers, events, quotations, invoices, inventory, staff, etc. so every
    business-record change shows up in the Activity Log, not just role/login
    changes. `verb` is a past-tense word: 'created', 'updated', 'deleted'.
    """
    model_name = display_name(instance)
    action = f'{instance._meta.model_name}.{verb}'
    description = f'{verb.capitalize()} {model_name} "{instance}"'
    if extra:
        description += f' {extra}'
    log_activity(request, action, description)
