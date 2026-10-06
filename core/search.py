"""Search across the app from the topbar box: customers, events, documents and staff."""
import re

from django.db.models import Q, Value
from django.db.models.functions import Replace

from billing.models import Invoice, Quotation, Receipt
from customers.models import Customer
from events.models import Event
from staffing.models import StaffMember

from .permissions import scope_events_to_assignments

LIMIT = 10


def _digits(query):
    """Phone-number form of the query: digits only, +256/256 turned into a leading 0."""
    digits = re.sub(r'\D', '', query)
    if digits.startswith('256') and len(digits) >= 12:
        digits = '0' + digits[3:]
    return digits


def _bare(field):
    """The field with spaces and dashes stripped, so '0772 123 456' matches '0772123456'."""
    return Replace(Replace(field, Value(' '), Value('')), Value('-'), Value(''))


def search_everything(user, query):
    """
    Returns a list of {'title', 'icon', 'url_name', 'results'} sections, one per kind of
    record the user may view, each holding up to LIMIT matches. Empty sections are left out.
    """
    query = query.strip()
    if len(query) < 2:
        return []
    digits = _digits(query)
    phone_q = len(digits) >= 4
    sections = []

    if user.has_perm('customers.view_customer'):
        cond = Q(name__icontains=query) | Q(email__icontains=query)
        qs = Customer.objects.all()
        if phone_q:
            qs = qs.annotate(bare_phone=_bare('phone'), bare_alt=_bare('alt_phone'))
            cond |= Q(bare_phone__contains=digits) | Q(bare_alt__contains=digits)
        sections.append({'key': 'customers', 'title': 'Customers', 'icon': 'bi-people',
                         'results': list(qs.filter(cond).order_by('name')[:LIMIT])})

    if user.has_perm('events.view_event'):
        qs = scope_events_to_assignments(Event.objects.select_related('customer'), user)
        cond = Q(customer__name__icontains=query) | Q(event_type__icontains=query) | Q(venue__icontains=query)
        sections.append({'key': 'events', 'title': 'Events', 'icon': 'bi-calendar-event',
                         'results': list(qs.filter(cond).order_by('-event_date')[:LIMIT])})

    doc_cond = Q(number__icontains=query) | Q(event__customer__name__icontains=query)
    if user.has_perm('billing.view_quotation'):
        sections.append({'key': 'quotations', 'title': 'Quotations', 'icon': 'bi-file-earmark-text',
                         'results': list(Quotation.objects.select_related('event__customer').filter(doc_cond)[:LIMIT])})
    if user.has_perm('billing.view_invoice'):
        sections.append({'key': 'invoices', 'title': 'Invoices', 'icon': 'bi-receipt',
                         'results': list(Invoice.objects.select_related('event__customer').filter(doc_cond)[:LIMIT])})
    if user.has_perm('billing.view_receipt'):
        cond = (Q(number__icontains=query) | Q(payment__invoice__event__customer__name__icontains=query)
                | Q(payment__reference_number__icontains=query))
        sections.append({'key': 'receipts', 'title': 'Receipts', 'icon': 'bi-receipt-cutoff',
                         'results': list(Receipt.objects.select_related('payment__invoice__event__customer').filter(cond)[:LIMIT])})

    if user.has_perm('staffing.view_staffmember'):
        cond = Q(full_name__icontains=query)
        qs = StaffMember.objects.all()
        if phone_q:
            qs = qs.annotate(bare_phone=_bare('phone'))
            cond |= Q(bare_phone__contains=digits)
        sections.append({'key': 'staff', 'title': 'Staff', 'icon': 'bi-person-badge',
                         'results': list(qs.filter(cond)[:LIMIT])})

    return [s for s in sections if s['results']]
