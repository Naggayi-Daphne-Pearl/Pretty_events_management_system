from core.forms import BootstrapModelForm

from .models import EventAssignment, StaffMember


class StaffMemberForm(BootstrapModelForm):
    """Business/HR fields only — the login (username/email/password/roles) is a
    separate, superuser-only section handled on the same page (see staffing/views.py),
    since not every staff member needs system access."""

    class Meta:
        model = StaffMember
        fields = ['full_name', 'phone', 'title', 'is_active']


class EventAssignmentForm(BootstrapModelForm):
    class Meta:
        model = EventAssignment
        fields = ['staff_member', 'role_on_event', 'notes']
