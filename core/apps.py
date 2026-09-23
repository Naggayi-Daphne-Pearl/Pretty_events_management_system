from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in
        from django.utils import timezone

        from .auth import SESSION_STARTED_KEY

        def stamp_session_start(sender, request, user, **kwargs):
            request.session[SESSION_STARTED_KEY] = timezone.now().timestamp()

        user_logged_in.connect(stamp_session_start, dispatch_uid='core.stamp_session_start', weak=False)
