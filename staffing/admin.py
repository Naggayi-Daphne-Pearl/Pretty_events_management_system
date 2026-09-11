from django.contrib import admin

from .models import EventAssignment, StaffMember


class EventAssignmentInline(admin.TabularInline):
    model = EventAssignment
    extra = 1


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'title', 'phone', 'is_active', 'user')
    list_filter = ('is_active', 'title')
    search_fields = ('full_name', 'phone')
    inlines = [EventAssignmentInline]


@admin.register(EventAssignment)
class EventAssignmentAdmin(admin.ModelAdmin):
    list_display = ('event', 'staff_member', 'role_on_event')
    search_fields = ('event__customer__name', 'staff_member__full_name')
