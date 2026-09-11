from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from billing.models import Invoice
from events.models import Event
from inventory.models import EquipmentItem

from .activity import log_activity
from .forms import SelfPasswordChangeForm, StaffSetPasswordForm
from .models import ActivityLog
from .permissions import grouped_permissions, scope_events_to_assignments


def superuser_required(view_func):
    """
    Managing roles/permissions is a meta-capability — letting a non-superuser
    grant permissions (even their own) would be a privilege-escalation hole, so
    this is deliberately superuser-only rather than gated by a regular
    permission checkbox. Gives a clean 403 rather than bouncing an already
    logged-in user back to the login page.
    """
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


@login_required
def dashboard(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    context = {}

    if request.user.has_perm('events.view_event'):
        events_qs = scope_events_to_assignments(Event.objects.select_related('customer'), request.user)
        upcoming_week = events_qs.filter(
            event_date__gte=today, event_date__lte=week_end,
        ).exclude(status__in=[Event.Status.COMPLETED, Event.Status.CANCELLED])
        upcoming_month = events_qs.filter(
            event_date__gte=today, event_date__lte=month_end,
        ).exclude(status__in=[Event.Status.COMPLETED, Event.Status.CANCELLED])
        context['upcoming_week'] = upcoming_week.order_by('event_date')[:10]
        context['upcoming_week_count'] = upcoming_week.count()
        context['upcoming_month_count'] = upcoming_month.count()

    if request.user.has_perm('billing.view_invoice'):
        unpaid_invoices = Invoice.objects.exclude(
            status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED],
        ).select_related('event__customer')
        context['unpaid_invoices'] = unpaid_invoices.order_by('due_date')[:10]
        context['unpaid_count'] = unpaid_invoices.count()
        context['unpaid_total'] = sum((inv.balance_due for inv in unpaid_invoices), 0)

    if request.user.has_perm('inventory.view_equipmentitem'):
        low_stock = [item for item in EquipmentItem.objects.all() if item.available_quantity <= 5]
        context['low_stock_items'] = low_stock[:10]

    return render(request, 'core/dashboard.html', context)


# ---------- Roles & Permissions (superuser-only) ----------
#
# Permissions are the source of truth for what a role can do; roles (Groups)
# themselves are fully dynamic — a superuser can create, rename, or delete any
# number of them here, and tick whichever permission checkboxes that role needs.
# No code change is ever required to add a new role.

@superuser_required
def role_list(request):
    roles = Group.objects.annotate(
        member_count=Count('user', distinct=True),
        permission_count=Count('permissions', distinct=True),
    ).order_by('name')
    return render(request, 'core/role_list.html', {'roles': roles})


@superuser_required
def role_form(request, pk=None):
    role = get_object_or_404(Group, pk=pk) if pk else None
    is_new = role is None

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        permission_ids = request.POST.getlist('permissions')

        if not name:
            messages.error(request, 'Role name is required.')
        else:
            if role is None:
                role = Group(name=name)
            else:
                role.name = name
            role.save()
            role.permissions.set(Permission.objects.filter(pk__in=permission_ids))
            log_activity(
                request, 'role.created' if is_new else 'role.updated',
                f'{"Created" if is_new else "Updated"} role "{role.name}" ({len(permission_ids)} permissions)',
            )
            messages.success(request, f'Role "{role.name}" saved.')
            return redirect('role_list')

    selected_permission_ids = set(
        str(pk) for pk in (role.permissions.values_list('pk', flat=True) if role else [])
    )

    return render(request, 'core/role_form.html', {
        'role': role,
        'permission_groups': grouped_permissions(),
        'selected_permission_ids': selected_permission_ids,
    })


@superuser_required
def role_delete(request, pk):
    role = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        name = role.name
        role.delete()
        log_activity(request, 'role.deleted', f'Deleted role "{name}"')
        messages.success(request, f'Role "{name}" deleted.')
        return redirect('role_list')
    return render(request, 'core/role_confirm_delete.html', {'role': role})


# ---------- Password reset for a staff login (superuser-only) ----------
# Creating/editing a login itself now happens on the Staff page (see
# staffing/views.py) alongside that person's business record — this is just
# the focused "set a new password" action, reachable from there.

@superuser_required
def user_set_password(request, pk):
    User = get_user_model()
    staff_user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = StaffSetPasswordForm(staff_user, request.POST)
        if form.is_valid():
            form.save()
            log_activity(request, 'staff_account.password_reset', f'Reset password for "{staff_user.username}"')
            messages.success(request, f'Password updated for "{staff_user.username}".')
            if hasattr(staff_user, 'staff_profile'):
                return redirect('staffing:detail', pk=staff_user.staff_profile.pk)
            return redirect('dashboard')
    else:
        form = StaffSetPasswordForm(staff_user)
    return render(request, 'core/user_set_password.html', {'form': form, 'staff_user': staff_user})


# ---------- Activity Log (superuser-only) ----------

@superuser_required
def activity_log(request):
    entries = ActivityLog.objects.select_related('actor').all()[:200]
    return render(request, 'core/activity_log.html', {'entries': entries})


# ---------- My Profile (any logged-in user) ----------

@login_required
def profile(request):
    if request.method == 'POST':
        form = SelfPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # keep them logged in after changing their own password
            messages.success(request, 'Password changed.')
            return redirect('profile')
    else:
        form = SelfPasswordChangeForm(request.user)
    return render(request, 'core/profile.html', {'form': form})
