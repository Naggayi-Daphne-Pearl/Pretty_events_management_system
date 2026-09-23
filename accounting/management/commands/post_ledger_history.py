from django.core.management.base import BaseCommand

from accounting.posting import post_history


class Command(BaseCommand):
    help = (
        'Create journal entries for income/expense records that don\'t have one yet (safe to re-run; '
        'runs on every deploy). Use --rebuild after changing which accounts categories map to, to '
        're-post every record with the current mapping.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--rebuild', action='store_true', help='Re-post every record, not just missing ones.')

    def handle(self, *args, **options):
        incomes, expenses = post_history(rebuild=options['rebuild'])
        self.stdout.write(self.style.SUCCESS(f'Posted {incomes} income and {expenses} expense record(s) to the ledger.'))
