from .models import ActivityLog


def log_activity(request, action, description):
    ActivityLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        description=description,
    )


def log_model_activity(request, instance, verb, extra=''):
    """
    Shorthand for the common "created/updated <this record>" case — used across
    customers, events, quotations, invoices, inventory, staff, etc. so every
    business-record change shows up in the Activity Log, not just role/login
    changes. `verb` is a past-tense word: 'created', 'updated', 'deleted'.
    """
    model_name = instance._meta.verbose_name
    action = f'{instance._meta.model_name}.{verb}'
    description = f'{verb.capitalize()} {model_name} "{instance}"'
    if extra:
        description += f' {extra}'
    log_activity(request, action, description)
