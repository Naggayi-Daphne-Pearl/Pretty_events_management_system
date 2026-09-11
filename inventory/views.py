from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from events.models import Event

from .forms import EquipmentIssueForm, EquipmentItemForm, EquipmentReturnForm
from .models import EquipmentIssue, EquipmentItem


class EquipmentItemListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = EquipmentItem
    permission_required = 'inventory.view_equipmentitem'
    template_name = 'inventory/item_list.html'

    def get_queryset(self):
        return super().get_queryset().select_related('category')


class EquipmentItemDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = EquipmentItem
    permission_required = 'inventory.view_equipmentitem'
    template_name = 'inventory/item_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['issues'] = self.object.issues.select_related('event__customer').all()
        return ctx


class EquipmentItemCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = EquipmentItem
    form_class = EquipmentItemForm
    permission_required = 'inventory.add_equipmentitem'
    template_name = 'inventory/item_form.html'
    success_message = 'Equipment item "%(name)s" added.'


class EquipmentItemUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = EquipmentItem
    form_class = EquipmentItemForm
    permission_required = 'inventory.change_equipmentitem'
    template_name = 'inventory/item_form.html'
    success_message = 'Equipment item "%(name)s" updated.'


@login_required
@permission_required('inventory.add_equipmentissue', raise_exception=True)
def issue_create(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    if request.method == 'POST':
        form = EquipmentIssueForm(request.POST)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.event = event
            issue.issued_by = request.user
            issue.save()
            messages.success(request, f'{issue.quantity_issued} x {issue.equipment_item.name} issued to this event.')
            return redirect('events:detail', pk=event.pk)
    else:
        form = EquipmentIssueForm()
    return render(request, 'inventory/issue_form.html', {'form': form, 'event': event})


@login_required
@permission_required('inventory.add_equipmentreturn', raise_exception=True)
def return_create(request, issue_pk):
    issue = get_object_or_404(EquipmentIssue, pk=issue_pk)
    if request.method == 'POST':
        form = EquipmentReturnForm(request.POST, issue=issue)
        if form.is_valid():
            equipment_return = form.save(commit=False)
            equipment_return.issue = issue
            equipment_return.received_by = request.user
            equipment_return.save()
            messages.success(request, 'Return recorded.')
            return redirect('events:detail', pk=issue.event.pk)
    else:
        form = EquipmentReturnForm(issue=issue, initial={'quantity_returned': issue.quantity_outstanding})
    return render(request, 'inventory/return_form.html', {'form': form, 'issue': issue})
