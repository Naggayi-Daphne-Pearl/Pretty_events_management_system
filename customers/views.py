from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from billing.models import Invoice, Quotation
from core.activity import log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.pagination import paginate

from .forms import CustomerForm
from .models import Customer


class CustomerListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Customer
    permission_required = 'customers.view_customer'
    paginate_by = 25
    template_name = 'customers/customer_list.html'

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        return ctx


class CustomerDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Customer
    permission_required = 'customers.view_customer'
    template_name = 'customers/customer_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['events'] = self.object.events.all()
        history = customer_history(self.object, self.request.user)
        ctx['billing_totals'] = history['billing_totals']
        ctx['timeline_page'] = paginate(self.request, history['timeline'], per_page=15, param='timeline_page')
        return ctx


def customer_history(customer, user):
    """
    Everything that has happened with this customer (events booked, quotations,
    invoices, payments, communication) merged into one newest-first timeline,
    plus billing totals. Each section only appears if the user may view it.
    """
    entries = []
    totals = None

    def add(when, kind, icon, title, url='', detail=''):
        # Mix of dates (payments) and datetimes; compare on the local date, then time for ties.
        if isinstance(when, datetime):
            local = timezone.localtime(when)
            sort_key = (local.date(), local.time())
        else:
            sort_key = (when, time.min)
        entries.append({'when': when, 'sort_key': sort_key, 'kind': kind, 'icon': icon,
                        'title': title, 'url': url, 'detail': detail})

    if user.has_perm('events.view_event'):
        for event in customer.events.all():
            add(event.created_at, 'Event', 'bi-calendar-event', f'Booked {event.event_type} for {event.event_date:%d %b %Y}',
                event.get_absolute_url(), event.get_status_display())

    if user.has_perm('billing.view_quotation'):
        for q in Quotation.objects.filter(event__customer=customer).prefetch_related('line_items'):
            add(q.created_at, 'Quotation', 'bi-file-earmark-text', f'Quotation {q.number}', q.get_absolute_url(),
                f'{q.get_status_display()} · {settings.CURRENCY} {q.total:,.0f}')

    if user.has_perm('billing.view_invoice'):
        invoices = list(Invoice.objects.filter(event__customer=customer).prefetch_related('line_items', 'payments__receipt'))
        billed = sum((i.total for i in invoices if i.status != Invoice.Status.CANCELLED), Decimal('0'))
        paid = sum((i.amount_paid for i in invoices if i.status != Invoice.Status.CANCELLED), Decimal('0'))
        totals = {'billed': billed, 'paid': paid, 'balance': billed - paid}
        for inv in invoices:
            add(inv.created_at, 'Invoice', 'bi-receipt', f'Invoice {inv.number}', inv.get_absolute_url(),
                f'{inv.get_status_display()} · {settings.CURRENCY} {inv.total:,.0f}')
            for p in inv.payments.all():
                receipt = getattr(p, 'receipt', None)
                add(p.paid_at, 'Payment', 'bi-cash-coin', f'Paid {settings.CURRENCY} {p.amount:,.0f} on {inv.number}',
                    receipt.get_absolute_url() if receipt else inv.get_absolute_url(), p.get_method_display())

    if user.has_perm('comms.view_communicationlog'):
        for log in customer.communication_logs.select_related('logged_by'):
            who = f' by {log.logged_by.username}' if log.logged_by else ''
            add(log.created_at, 'Contact', 'bi-chat-dots',
                f'{log.get_channel_display()} ({log.get_direction_display().lower()}){who}', '', log.message)
            entries[-1]['log'] = log

    entries.sort(key=lambda e: e['sort_key'], reverse=True)
    return {'timeline': entries, 'billing_totals': totals}


class CustomerCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.add_customer'
    template_name = 'customers/customer_form.html'
    success_message = 'Customer "%(name)s" added.'

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'created')
        return response

    def get_success_url(self):
        # The common case is "new inquiry": capture the customer, then immediately
        # capture the event they're calling about. Send straight into a pre-filled
        # New Event form rather than the customer detail page — that form offers a
        # "skip for now" link back to the detail page for the walk-in-contact-only case.
        if self.request.user.has_perm('events.add_event'):
            return reverse('events:create') + f'?customer={self.object.pk}'
        return self.object.get_absolute_url()


class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.change_customer'
    template_name = 'customers/customer_form.html'
    success_message = 'Customer "%(name)s" updated.'

    def form_valid(self, form):
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'updated')
        return response


@login_required
@permission_required('customers.delete_customer', raise_exception=True)
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return confirm_and_delete(
        request, customer,
        cancel_url=customer.get_absolute_url(),
        success_url=reverse('customers:list'),
        blockers=[count_label(customer.events.count(), 'event')],
        also_deleted=[count_label(customer.communication_logs.count(), 'communication log entry', 'communication log entries')],
        hint='Delete or reassign their events first. Events with quotations or invoices are kept for the financial record.',
    )
