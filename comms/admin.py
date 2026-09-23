from django.contrib import admin

from .models import CommunicationLog


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):
    list_display = ('customer', 'event', 'channel', 'direction', 'created_at', 'logged_by')
    list_filter = ('channel', 'direction')
    search_fields = ('customer__name', 'message')
    list_select_related = ('customer', 'event__customer', 'logged_by')
    list_per_page = 50
    date_hierarchy = 'created_at'
    raw_id_fields = ('customer', 'event')
