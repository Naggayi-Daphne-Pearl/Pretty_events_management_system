from .models import ActivityLog


def log_activity(request, action, description):
    ActivityLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        description=description,
    )
