from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView

from customers.models import Customer

from .forms import CommunicationLogForm
from .models import CommunicationLog


class CommunicationLogListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = CommunicationLog
    permission_required = 'comms.view_communicationlog'
    paginate_by = 25
    template_name = 'comms/log_list.html'

    def get_queryset(self):
        return super().get_queryset().select_related('customer')


@login_required
@permission_required('comms.add_communicationlog', raise_exception=True)
def log_create(request, customer_pk):
    customer = get_object_or_404(Customer, pk=customer_pk)
    if request.method == 'POST':
        form = CommunicationLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.customer = customer
            log.logged_by = request.user
            log.save()
            messages.success(request, 'Communication logged.')
            return redirect('customers:detail', pk=customer.pk)
    else:
        form = CommunicationLogForm()
    return render(request, 'comms/log_form.html', {'form': form, 'customer': customer})
