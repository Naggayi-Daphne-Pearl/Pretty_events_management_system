from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

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
        ctx['communication_logs'] = self.object.communication_logs.all()[:10]
        return ctx


class CustomerCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.add_customer'
    template_name = 'customers/customer_form.html'
    success_message = 'Customer "%(name)s" added.'

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.change_customer'
    template_name = 'customers/customer_form.html'
    success_message = 'Customer "%(name)s" updated.'
