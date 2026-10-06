from django.apps import AppConfig


class AccountingConfig(AppConfig):
    name = 'accounting'
    verbose_name = 'Accounting'

    def ready(self):
        from . import signals  # noqa: F401  (connects auto-posting)
        from . import locks  # noqa: F401  (blocks deleting journals in closed periods)
