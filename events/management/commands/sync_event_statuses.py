from django.core.management.base import BaseCommand

from events.services import sync_event_statuses


class Command(BaseCommand):
    help = (
        'Move confirmed events to In Progress once they start, and to Completed after '
        'their last day once all equipment is returned. Safe to run any time; also runs '
        'automatically when the dashboard or events list is opened.'
    )

    def handle(self, *args, **options):
        changed = sync_event_statuses()
        self.stdout.write(self.style.SUCCESS(f'{changed} event(s) updated.'))
