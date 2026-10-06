from django.core.management.base import BaseCommand

from billing.services import sync_invoice_statuses


class Command(BaseCommand):
    help = (
        'Mark unpaid and partly paid invoices as Overdue once their due date has passed. '
        'Safe to run any time; also runs automatically when the dashboard or invoice list is opened.'
    )

    def handle(self, *args, **options):
        changed = sync_invoice_statuses()
        self.stdout.write(self.style.SUCCESS(f'{changed} invoice(s) marked overdue.'))
