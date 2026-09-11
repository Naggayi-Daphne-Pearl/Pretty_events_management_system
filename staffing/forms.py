from core.forms import BootstrapModelForm

from .models import EventAssignment, StaffMember


class StaffMemberForm(BootstrapModelForm):
    class Meta:
        model = StaffMember
        fields = ['full_name', 'phone', 'title', 'user', 'is_active']


class EventAssignmentForm(BootstrapModelForm):
    class Meta:
        model = EventAssignment
        fields = ['staff_member', 'role_on_event', 'notes']
