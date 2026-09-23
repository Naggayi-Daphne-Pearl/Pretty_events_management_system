from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounting.models import Account, JournalEntry
from billing.models import Invoice, InvoiceLineItem, Payment, Quotation, QuotationLineItem, Receipt
from comms.models import CommunicationLog
from customers.models import Customer
from events.models import Event
from finance.models import ExpenseCategory, ExpenseRecord, IncomeRecord
from inventory.models import EquipmentCategory, EquipmentIssue, EquipmentItem, EquipmentReturn
from staffing.models import EventAssignment, StaffMember

ALL_ACTIONS = ('add', 'change', 'delete', 'view')
VIEW_ONLY = ('view',)


def perms_for(model, actions=ALL_ACTIONS):
    codenames = [f'{action}_{model._meta.model_name}' for action in actions]
    return Permission.objects.filter(
        content_type__app_label=model._meta.app_label,
        codename__in=codenames,
    )


class Command(BaseCommand):
    help = (
        'Seed three starter role groups (Admin, Office Staff, Field Staff) with sensible '
        'permission checkboxes ticked. Roles themselves are fully dynamic afterwards — a '
        'superuser can rename these, delete them, or create entirely new ones (with any '
        'permission combination) from Django admin under Users > Groups. This command is '
        'just a convenience so the app isn\'t empty on first setup.'
    )

    def handle(self, *args, **options):
        # Admin/Owner: full access to every model. Superusers already bypass permission
        # checks, but this group lets a non-superuser be granted the same access explicitly.
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        admin_perms = Permission.objects.filter(
            content_type__app_label__in=[
                'customers', 'events', 'billing', 'inventory', 'finance', 'staffing', 'comms', 'accounting',
            ]
        )
        admin_group.permissions.set(admin_perms)

        # Office Staff: full CRUD on customers/events/billing/inventory/staffing/comms,
        # view-only on finance (income/expense summaries are an owner-level concern).
        office_group, _ = Group.objects.get_or_create(name='Office Staff')
        office_perms = list(perms_for(Customer)) + list(perms_for(Event))
        for model in (Quotation, QuotationLineItem, Invoice, InvoiceLineItem, Payment, Receipt):
            office_perms += list(perms_for(model))
        for model in (EquipmentCategory, EquipmentItem, EquipmentIssue, EquipmentReturn):
            office_perms += list(perms_for(model))
        for model in (StaffMember, EventAssignment):
            office_perms += list(perms_for(model))
        office_perms += list(perms_for(CommunicationLog))
        for model in (IncomeRecord, ExpenseRecord, ExpenseCategory):
            office_perms += list(perms_for(model, VIEW_ONLY))
        office_group.permissions.set(office_perms)

        # Field Staff: view-only, and further scoped to "their" assigned events by the
        # 'view_assigned_events_only' permission — ticking that same checkbox on ANY group
        # (not just one literally named "Field Staff") gets the same row-level restriction,
        # since the views check the permission, not the group name.
        field_group, _ = Group.objects.get_or_create(name='Field Staff')
        field_perms = list(perms_for(Event, VIEW_ONLY)) + list(perms_for(EventAssignment, VIEW_ONLY))
        field_perms += list(perms_for(EquipmentIssue, VIEW_ONLY))
        field_perms += list(Permission.objects.filter(
            content_type__app_label='events', codename='view_assigned_events_only',
        ))
        field_group.permissions.set(field_perms)

        # Accountant: runs the books. Full accounting + income/expense records, and
        # read-only access to the operational records the books are built from.
        accountant_group, _ = Group.objects.get_or_create(name='Accountant')
        accountant_perms = list(perms_for(Account)) + list(perms_for(JournalEntry))
        for model in (IncomeRecord, ExpenseRecord, ExpenseCategory):
            accountant_perms += list(perms_for(model))
        for model in (Customer, Event, Quotation, Invoice, Payment, Receipt):
            accountant_perms += list(perms_for(model, VIEW_ONLY))
        accountant_group.permissions.set(accountant_perms)

        self.stdout.write(self.style.SUCCESS(
            'Groups ready: Admin, Office Staff, Field Staff, Accountant. '
            'Assign users to a group in Django admin (Users > edit > Groups). '
            'To add a new role, create a Group there and tick whichever permissions it needs — '
            'no code changes required.'
        ))
