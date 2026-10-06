from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction

from core.models import ActivityLog

# Deleted in this order: each step only removes rows nothing left over still points
# at (several links are PROTECT). Labels are app_label.ModelName.
BUSINESS_DATA = [
    'accounting.PeriodClose',  # first: a closed period blocks deleting its journals
    'accounting.JournalLine',
    'accounting.JournalEntry',
    'billing.MobileMoneyTransaction',
    'finance.IncomeRecord',
    'finance.ExpenseRecord',
    'billing.Receipt',
    'billing.Payment',
    'billing.InvoiceLineItem',
    'billing.Invoice',
    'billing.QuotationLineItem',
    'billing.Quotation',
    'billing.DocumentSequence',
    'inventory.EquipmentReturn',
    'inventory.EquipmentIssue',
    'staffing.EventAssignment',
    'comms.CommunicationLog',
    'events.Event',
    'customers.Customer',
    'core.ActivityLog',
    'core.FormSubmissionToken',
    'core.FailedLoginAttempt',
    'admin.LogEntry',
    'django_tasks_database.DBTaskResult',
]
EQUIPMENT = ['inventory.EquipmentItem', 'inventory.EquipmentCategory']
STAFF = ['staffing.StaffMember']


class Command(BaseCommand):
    help = (
        'Delete all business records (customers, events, quotations, invoices, payments, receipts, '
        'income, expenses, journals, equipment issues, communication and activity logs) to start '
        'afresh after testing. Keeps logins, roles, the chart of accounts, expense categories and, '
        'unless asked, the equipment list and staff records. Document and journal numbers restart '
        'at 00001. Without --confirm it only shows what would be deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Actually delete. Without it, nothing changes.')
        parser.add_argument('--include-equipment', action='store_true',
                            help='Also delete equipment items and categories.')
        parser.add_argument('--include-staff', action='store_true',
                            help='Also delete staff records (their logins are kept).')

    def handle(self, *args, confirm, include_equipment, include_staff, **options):
        labels = BUSINESS_DATA + (EQUIPMENT if include_equipment else []) + (STAFF if include_staff else [])
        models = [apps.get_model(label) for label in labels]

        self.stdout.write('Will delete:' if confirm else 'Dry run. These would be deleted:')
        for model in models:
            self.stdout.write(f'  {model._meta.verbose_name_plural:<32} {model._default_manager.count():>6}')
        kept = ['logins and roles', 'chart of accounts', 'expense categories']
        if not include_equipment:
            kept.append('equipment items and categories')
        if not include_staff:
            kept.append('staff records')
        self.stdout.write('Kept: ' + ', '.join(kept) + '.')

        if not confirm:
            self.stdout.write(self.style.WARNING('Nothing was deleted. Run again with --confirm to delete.'))
            return

        with transaction.atomic():
            for model in models:
                if model._meta.label == 'accounting.JournalEntry':
                    # Reversals point at the entries they reverse (PROTECT), so they go first.
                    model.objects.filter(reverses__isnull=False).delete()
                model._default_manager.all().delete()
            self._restart_ids(models)
            ActivityLog.objects.create(
                actor=None, action='system.reset',
                description='Test data cleared with reset_business_data; numbering restarted',
            )
        self.stdout.write(self.style.SUCCESS('Done. Business data cleared; numbering starts again at 00001.'))

    def _restart_ids(self, models):
        """Start ids at 1 again on the emptied tables (journal numbers are built from the id)."""
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                tables = [m._meta.db_table for m in models]
                cursor.execute(
                    f'DELETE FROM sqlite_sequence WHERE name IN ({", ".join(["%s"] * len(tables))})', tables,
                )
            else:
                for sql in connection.ops.sequence_reset_sql(no_style(), models):
                    cursor.execute(sql)
