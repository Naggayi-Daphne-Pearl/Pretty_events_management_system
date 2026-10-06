from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounting.models import Account, JournalEntry, PeriodClose
from billing.models import Invoice, InvoiceLineItem, Payment, Quotation, QuotationLineItem, Receipt
from comms.models import CommunicationLog
from customers.models import Customer
from events.models import Event
from finance.models import ExpenseCategory, ExpenseRecord, IncomeRecord
from inventory.models import EquipmentCategory, EquipmentIssue, EquipmentItem, EquipmentReturn
from staffing.models import EventAssignment, StaffMember

from core.models import RoleDefault

ALL_ACTIONS = ('add', 'change', 'delete', 'view')
VIEW_ONLY = ('view',)


def perms_for(model, actions=ALL_ACTIONS):
    codenames = [f'{action}_{model._meta.model_name}' for action in actions]
    return Permission.objects.select_related('content_type').filter(
        content_type__app_label=model._meta.app_label,
        codename__in=codenames,
    )


def starter_roles():
    """The four starter roles and the permissions each gets by default."""
    office = list(perms_for(Customer)) + list(perms_for(Event))
    for model in (Quotation, QuotationLineItem, Invoice, InvoiceLineItem, Payment, Receipt):
        office += list(perms_for(model))
    for model in (EquipmentCategory, EquipmentItem, EquipmentIssue, EquipmentReturn):
        office += list(perms_for(model))
    for model in (StaffMember, EventAssignment):
        office += list(perms_for(model))
    office += list(perms_for(CommunicationLog))
    for model in (IncomeRecord, ExpenseRecord, ExpenseCategory):
        office += list(perms_for(model, VIEW_ONLY))

    # Field Staff are further scoped to "their" assigned events by the
    # 'view_assigned_events_only' permission; ticking it on any role does the same.
    field = list(perms_for(Event, VIEW_ONLY)) + list(perms_for(EventAssignment, VIEW_ONLY))
    field += list(perms_for(EquipmentIssue, VIEW_ONLY))
    field += list(Permission.objects.select_related('content_type').filter(
        content_type__app_label='events', codename='view_assigned_events_only',
    ))

    # Accountant: full accounting + income/expense records, read-only operational records.
    accountant = list(perms_for(Account)) + list(perms_for(JournalEntry)) + list(perms_for(PeriodClose))
    for model in (IncomeRecord, ExpenseRecord, ExpenseCategory):
        accountant += list(perms_for(model))
    for model in (Customer, Event, Quotation, Invoice, Payment, Receipt):
        accountant += list(perms_for(model, VIEW_ONLY))

    return {
        # Admin/Owner: everything in the business apps.
        'Admin': list(Permission.objects.select_related('content_type').filter(content_type__app_label__in=[
            'customers', 'events', 'billing', 'inventory', 'finance', 'staffing', 'comms', 'accounting',
        ])),
        'Office Staff': office,
        'Field Staff': field,
        'Accountant': accountant,
    }


class Command(BaseCommand):
    help = (
        'Create the starter roles (Admin, Office Staff, Field Staff, Accountant) with sensible '
        'permissions. Runs on every deploy but applies each default only once: roles and '
        'permissions the client changes in Roles & permissions are left alone, and only defaults '
        'for new features are added. Use --reset to put the starter roles back to their defaults.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Recreate the starter roles and set their permissions to the defaults exactly.')

    def handle(self, *args, reset=False, **options):
        added = 0
        for name, perms in starter_roles().items():
            if reset:
                group, _ = Group.objects.get_or_create(name=name)
                group.permissions.set(perms)
                RoleDefault.objects.get_or_create(group_name=name, permission='')
                RoleDefault.objects.bulk_create(
                    [RoleDefault(group_name=name, permission=self.key(p)) for p in perms], ignore_conflicts=True,
                )
                continue

            group = Group.objects.filter(name=name).first()
            if group is None:
                if RoleDefault.objects.filter(group_name=name, permission='').exists():
                    continue  # created before and since deleted by the client: leave it deleted
                group = Group.objects.create(name=name)
            RoleDefault.objects.get_or_create(group_name=name, permission='')

            applied = set(RoleDefault.objects.filter(group_name=name).values_list('permission', flat=True))
            new = [p for p in perms if self.key(p) not in applied]
            if new:
                group.permissions.add(*new)
                RoleDefault.objects.bulk_create(
                    [RoleDefault(group_name=name, permission=self.key(p)) for p in new], ignore_conflicts=True,
                )
                added += len(new)

        self.stdout.write(self.style.SUCCESS(
            'Starter roles reset to their defaults.' if reset else
            f'Starter roles checked; {added} new default permission(s) applied. '
            'Changes made in Roles & permissions are kept.'
        ))

    @staticmethod
    def key(permission):
        return f'{permission.content_type.app_label}.{permission.codename}'
