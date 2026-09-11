from django.contrib import admin

from .models import CommunicationLog


@admin.register(CommunicationLog)
class CommunicationLogAdmin(admin.ModelAdmin):
    list_display = ('customer', 'channel', 'direction', 'created_at', 'logged_by')
    list_filter = ('channel', 'direction')
    search_fields = ('customer__name', 'message')
