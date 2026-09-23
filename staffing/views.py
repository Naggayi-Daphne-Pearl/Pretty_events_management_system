from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, ListView

from core.activity import log_activity
from core.accounts import send_staff_invite
from core.deletion import confirm_and_delete, count_label
from core.forms import StaffAccountCreationForm, StaffAccountUpdateForm
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


def _create_login(request, staff_member, login_form):
    user = login_form.save()
    staff_member.user = user
    staff_member.save(update_fields=['user'])
    log_activity(request, 'staff_account.created', f'Created login "{user.email}" for staff member "{staff_member.full_name}"')
    if not login_form.sends_invite:
        return
    if send_staff_invite(request, user):
        log_activity(request, 'staff_account.invite_sent', f'Sent invite to "{user.email}"')
        messages.info(request, f'An invite was emailed to {user.email} so they can set their own password.')
    else:
        messages.warning(
            request,
            f'The login was created, but the invite email to {user.email} could not be sent. '
            'Use "Send invite" on their page once email is working, or set a password for them.',
        )


@login_required
@permission_required('staffing.add_staffmember', raise_exception=True)
def staff_create(request):
    can_manage_login = request.user.is_superuser
    if request.method == 'POST':
        form = StaffMemberForm(request.POST)
        login_form = StaffAccountCreationForm(request.POST, prefix='login') if can_manage_login else None
        wants_login = can_manage_login and request.POST.get('create_login')

        if form.is_valid() and (not wants_login or (login_form and login_form.is_valid())):
            staff_member = form.save()
            log_activity(request, 'staff.created', f'Created staff member "{staff_member.full_name}"')
            if wants_login:
                _create_login(request, staff_member, login_form)
            messages.success(request, f'Staff member "{staff_member.full_name}" added.')
            return redirect('staffing:detail', pk=staff_member.pk)
    else:
        form = StaffMemberForm()
        login_form = StaffAccountCreationForm(prefix='login') if can_manage_login else None

    return render(request, 'staffing/staff_form.html', {
        'form': form, 'login_form': login_form, 'can_manage_login': can_manage_login,
        'staff_member': None, 'linked_user': None,
        'wants_login': request.method == 'POST' and bool(request.POST.get('create_login')),
    })


@login_required
@permission_required('staffing.change_staffmember', raise_exception=True)
def staff_update(request, pk):
    staff_member = get_object_or_404(StaffMember, pk=pk)
    can_manage_login = request.user.is_superuser
    linked_user = staff_member.user

    if request.method == 'POST':
        form = StaffMemberForm(request.POST, instance=staff_member)
        login_form = None
        wants_login = can_manage_login and request.POST.get('create_login')

        if can_manage_login:
            if linked_user:
                login_form = StaffAccountUpdateForm(request.POST, instance=linked_user, prefix='login')
            elif wants_login:
                login_form = StaffAccountCreationForm(request.POST, prefix='login')

        if form.is_valid() and (login_form is None or login_form.is_valid()):
            staff_member = form.save()
            log_activity(request, 'staff.updated', f'Updated staff member "{staff_member.full_name}"')
            if login_form and not linked_user:
                _create_login(request, staff_member, login_form)
            elif login_form and linked_user:
                login_form.save()
                log_activity(
                    request, 'staff_account.updated',
                    f'Updated login "{linked_user.username}" for staff member "{staff_member.full_name}"',
                )
            messages.success(request, f'Staff member "{staff_member.full_name}" updated.')
            return redirect('staffing:detail', pk=staff_member.pk)
    else:
        form = StaffMemberForm(instance=staff_member)
        login_form = None
        if can_manage_login:
            login_form = (
                StaffAccountUpdateForm(instance=linked_user, prefix='login') if linked_user
                else StaffAccountCreationForm(prefix='login')
            )

    return render(request, 'staffing/staff_form.html', {
        'form': form, 'login_form': login_form, 'can_manage_login': can_manage_login,
        'staff_member': staff_member, 'linked_user': linked_user,
        'wants_login': request.method == 'POST' and bool(request.POST.get('create_login')),
    })


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
            log_activity(
                request, 'event_assignment.created',
                f'Assigned "{assignment.staff_member}" to event "{event}"',
            )
            messages.success(request, f'{assignment.staff_member} assigned to this event.')
            return redirect('events:detail', pk=event.pk)
    else:
        form = EventAssignmentForm()
    return render(request, 'staffing/assign_form.html', {'form': form, 'event': event})


@login_required
@permission_required('staffing.delete_staffmember', raise_exception=True)
def staff_delete(request, pk):
    staff_member = get_object_or_404(StaffMember, pk=pk)
    blockers = [count_label(staff_member.assignments.count(), 'event assignment')]
    if staff_member.user_id:
        # Deleting the profile would leave the login working with no staff record
        # behind it, so make someone deal with the account deliberately.
        blockers.append(f'the login account "{staff_member.user.username}"')
    return confirm_and_delete(
        request, staff_member,
        cancel_url=staff_member.get_absolute_url(),
        success_url=reverse('staffing:list'),
        blockers=blockers,
        hint='To take someone off the team without losing their event history, edit them and untick "Is active" (and deactivate their login).',
    )
