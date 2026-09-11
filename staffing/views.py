from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from events.models import Event

from .forms import EventAssignmentForm, StaffMemberForm
from .models import StaffMember


class StaffMemberListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = StaffMember
    permission_required = 'staffing.view_staffmember'
    template_name = 'staffing/staff_list.html'


class StaffMemberDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = StaffMember
    permission_required = 'staffing.view_staffmember'
    template_name = 'staffing/staff_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['assignments'] = self.object.assignments.select_related('event__customer').all()
        return ctx


class StaffMemberCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = StaffMember
    form_class = StaffMemberForm
    permission_required = 'staffing.add_staffmember'
    template_name = 'staffing/staff_form.html'
    success_message = 'Staff member "%(full_name)s" added.'


class StaffMemberUpdateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    model = StaffMember
    form_class = StaffMemberForm
    permission_required = 'staffing.change_staffmember'
    template_name = 'staffing/staff_form.html'
    success_message = 'Staff member "%(full_name)s" updated.'


@login_required
@permission_required('staffing.add_eventassignment', raise_exception=True)
def assign_staff(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    if request.method == 'POST':
        form = EventAssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.event = event
            assignment.save()
            messages.success(request, f'{assignment.staff_member} assigned to this event.')
            return redirect('events:detail', pk=event.pk)
    else:
        form = EventAssignmentForm()
    return render(request, 'staffing/assign_form.html', {'form': form, 'event': event})
