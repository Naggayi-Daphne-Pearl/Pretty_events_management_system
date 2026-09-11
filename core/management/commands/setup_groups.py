from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

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
    help = 'Create the Phase 1 role groups (Admin, Office Staff, Field Staff) and assign permissions.'

    def handle(self, *args, **options):
        # Admin/Owner: full access to every model. Superusers already bypass permission
        # checks, but this group lets a non-superuser be granted the same access explicitly.
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        admin_perms = Permission.objects.filter(
            content_type__app_label__in=[
                'customers', 'events', 'billing', 'inventory', 'finance', 'staffing', 'comms',
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

        # Field Staff: view-only, scoped further to "their" events in the views themselves
        # (Django group permissions alone can't express row-level "my assigned events").
        field_group, _ = Group.objects.get_or_create(name='Field Staff')
        field_perms = list(perms_for(Event, VIEW_ONLY)) + list(perms_for(EventAssignment, VIEW_ONLY))
        field_perms += list(perms_for(EquipmentIssue, VIEW_ONLY))
        field_group.permissions.set(field_perms)

        self.stdout.write(self.style.SUCCESS(
            'Groups ready: Admin, Office Staff, Field Staff. '
            'Assign users to a group in Django admin (Users > edit > Groups).'
        ))
