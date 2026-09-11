from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from customers.models import Customer

from .forms import EventForm
from .models import Event


class FieldStaffScopeMixin:
    """Restrict Field Staff (non-admin) to only the events they're assigned to."""

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.groups.filter(name='Field Staff').exists() and not user.is_superuser:
            qs = qs.filter(assignments__staff_member__user=user).distinct()
        return qs


class EventListView(LoginRequiredMixin, PermissionRequiredMixin, FieldStaffScopeMixin, ListView):
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


class EventDetailView(LoginRequiredMixin, PermissionRequiredMixin, FieldStaffScopeMixin, DetailView):
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


class EventCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = Event
    form_class = EventForm
    permission_required = 'events.add_event'
    template_name = 'events/event_form.html'
    success_message = 'Event created.'

    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get('customer')
        if customer_id:
            initial['customer'] = Customer.objects.filter(pk=customer_id).first()
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class EventUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Event
    form_class = EventForm
    permission_required = 'events.change_event'
    template_name = 'events/event_form.html'
    success_message = 'Event updated.'
