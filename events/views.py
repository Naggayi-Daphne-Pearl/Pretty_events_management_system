from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.permissions import scope_events_to_assignments
from customers.models import Customer

from .forms import EventForm
from .models import Event


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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['quotations'] = self.object.quotations.all()
        ctx['invoices'] = self.object.invoices.all()
        ctx['equipment_issues'] = self.object.equipment_issues.select_related('equipment_item').all()
        ctx['assignments'] = self.object.assignments.select_related('staff_member').all()
        return ctx


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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['prefill_customer'] = self.get_prefill_customer()
        return ctx

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class EventUpdateView(
    LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CustomerSearchDataMixin, UpdateView,
):
    model = Event
    form_class = EventForm
    permission_required = 'events.change_event'
    template_name = 'events/event_form.html'
    success_message = 'Event updated.'
