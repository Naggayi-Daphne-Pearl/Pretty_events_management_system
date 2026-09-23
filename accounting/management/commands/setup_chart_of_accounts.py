from django.core.management.base import BaseCommand

from accounting.chart import ensure_chart_of_accounts


class Command(BaseCommand):
    help = 'Create any missing default accounts. Existing accounts are never changed, so this is safe to re-run.'

    def handle(self, *args, **options):
        created = ensure_chart_of_accounts()
        self.stdout.write(self.style.SUCCESS(f'Chart of accounts ready ({created} account(s) created).'))
