from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.activity import log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.pagination import paginate
from core.permissions import scope_events_to_assignments
from customers.models import Customer

from .forms import EventForm
from .models import Event
from .services import sync_event_status, sync_event_statuses


class AssignedEventsScopeMixin:
    """
    Restrict the queryset to events the current user is personally assigned
    to, for any role that has been granted the 'view_assigned_events_only'
    permission (see core.permissions.restricted_to_own_events).
    """

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_events_to_assignments(qs, self.request.user)


class EventListView(LoginRequiredMixin, PermissionRequiredMixin, AssignedEventsScopeMixin, ListView):
    model = Event
    permission_required = 'events.view_event'
    paginate_by = 25
    template_name = 'events/event_list.html'

    def get(self, request, *args, **kwargs):
        sync_event_statuses()
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset().select_related('customer')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(customer__name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        ctx['statuses'] = Event.Status.choices
        return ctx


class EventDetailView(LoginRequiredMixin, PermissionRequiredMixin, AssignedEventsScopeMixin, DetailView):
    model = Event
    permission_required = 'events.view_event'
    template_name = 'events/event_detail.html'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if sync_event_status(event):
            messages.info(self.request, f'Status moved to "{event.get_status_display()}" based on the event date.')
        return event

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        event = self.object
        ctx['quotations'] = list(event.quotations.prefetch_related('line_items').select_related('invoice'))
        ctx['invoices'] = list(event.invoices.prefetch_related('line_items', 'payments__receipt'))
        ctx['equipment_issues'] = list(event.equipment_issues.select_related('equipment_item').all())
        ctx['assignments'] = event.assignments.select_related('staff_member').all()
        ctx['comms_page'] = paginate(
            self.request, event.communication_logs.select_related('logged_by'), per_page=10, param='comms_page',
        )
        ctx['next_step'] = next_step_for(event, ctx, self.request.user)
        return ctx


def next_step_for(event, ctx, user):
    """
    The single most useful thing to do next on this event, shown as a banner at
    the top of the event page so staff don't have to work out where the booking
    is up to. Returns {'text', 'url', 'button'} or None.
    """
    if event.status in (Event.Status.CANCELLED, Event.Status.COMPLETED):
        return None
    quotations, invoices = ctx['quotations'], ctx['invoices']
    open_invoices = [i for i in invoices if i.status != i.Status.CANCELLED]

    if not quotations and not invoices:
        if user.has_perm('billing.add_quotation'):
            return {'text': 'No quotation yet. Price this event for the client.',
                    'url': reverse('billing:quotation_create', args=[event.pk]), 'button': 'Create quotation'}
        return None
    for q in quotations:
        if q.has_invoice:
            continue
        if q.status == q.Status.DRAFT and user.has_perm('billing.change_quotation'):
            return {'text': f'Quotation {q.number} is still a draft. Send it to the client.',
                    'url': q.get_absolute_url(), 'button': 'Open quotation'}
        if q.status in (q.Status.SENT, q.Status.APPROVED) and not open_invoices and user.has_perm('billing.add_invoice'):
            return {'text': f'Quotation {q.number} has been sent. Once the client accepts, convert it to an invoice.',
                    'url': q.get_absolute_url(), 'button': 'Open quotation'}
    for inv in open_invoices:
        if inv.balance_due > 0 and user.has_perm('billing.add_payment'):
            return {'text': f'Invoice {inv.number} has {settings.CURRENCY} {inv.balance_due:,.0f} outstanding.',
                    'url': inv.get_absolute_url() + '#record-payment', 'button': 'Record payment'}
    if event.status in (Event.Status.CONFIRMED, Event.Status.IN_PROGRESS):
        if not ctx['assignments'] and user.has_perm('staffing.add_eventassignment'):
            return {'text': 'Nobody is assigned to this event yet.',
                    'url': reverse('staffing:assign', args=[event.pk]), 'button': 'Assign staff'}
        if not ctx['equipment_issues'] and user.has_perm('inventory.add_equipmentissue'):
            return {'text': 'No equipment has been issued for this event yet.',
                    'url': reverse('inventory:issue_create', args=[event.pk]), 'button': 'Issue equipment'}
        if event.last_day < timezone.localdate() and any(i.quantity_outstanding > 0 for i in ctx['equipment_issues']):
            return {'text': 'The event is over but some equipment has not come back.',
                    'url': '#equipment', 'button': 'See equipment'}
    return None


class CustomerSearchDataMixin:
    """Feeds the event form's JS-driven customer search box — see event_form.html.
    A plain <select> is fine for a handful of customers, painful for hundreds."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['customers'] = list(Customer.objects.order_by('name').values('id', 'name', 'phone'))
        return ctx


class EventCreateView(
    LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CustomerSearchDataMixin, CreateView,
):
    model = Event
    form_class = EventForm
    permission_required = 'events.add_event'
    template_name = 'events/event_form.html'
    success_message = 'Event created.'

    def get_prefill_customer(self):
        customer_id = self.request.GET.get('customer')
        return Customer.objects.filter(pk=customer_id).first() if customer_id else None

    def get_initial(self):
        initial = super().get_initial()
        prefill_customer = self.get_prefill_customer()
        if prefill_customer:
            initial['customer'] = prefill_customer
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['allow_new_customer'] = self.request.user.has_perm('customers.add_customer')
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['prefill_customer'] = self.get_prefill_customer()
        return ctx

    def form_valid(self, form):
        with transaction.atomic():
            new_customer = form.save_new_customer(created_by=self.request.user)
            form.instance.created_by = self.request.user
            response = super().form_valid(form)
        if new_customer:
            log_model_activity(self.request, new_customer, 'created')
        log_model_activity(self.request, self.object, 'created')
        return response

    def get_success_url(self):
        # "Save & create quotation": the usual next step for a new booking.
        if self.request.POST.get('then') == 'quotation' and self.request.user.has_perm('billing.add_quotation'):
            return reverse('billing:quotation_create', args=[self.object.pk])
        return super().get_success_url()


class EventUpdateView(
    LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CustomerSearchDataMixin, UpdateView,
):
    model = Event
    form_class = EventForm
    permission_required = 'events.change_event'
    template_name = 'events/event_form.html'
    success_message = 'Event updated.'

    def form_valid(self, form):
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'updated')
        return response


@login_required
@permission_required('events.delete_event', raise_exception=True)
def event_delete(request, pk):
    event = get_object_or_404(scope_events_to_assignments(Event.objects.all(), request.user), pk=pk)
    return confirm_and_delete(
        request, event,
        cancel_url=event.get_absolute_url(),
        success_url=reverse('events:list'),
        blockers=[
            count_label(event.quotations.count(), 'quotation'),
            count_label(event.invoices.count(), 'invoice'),
            count_label(event.equipment_issues.count(), 'equipment issue record'),
            count_label(event.income_records.count(), 'income record'),
            count_label(event.expense_records.count(), 'expense record'),
        ],
        also_deleted=[count_label(event.assignments.count(), 'staff assignment')],
        hint='If the booking fell through, set the event status to Cancelled instead; that keeps its history.',
    )
