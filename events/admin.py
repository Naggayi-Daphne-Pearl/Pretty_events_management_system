from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'customer', 'event_date', 'venue', 'status')
    list_filter = ('status', 'event_type')
    search_fields = ('customer__name', 'venue')
    date_hierarchy = 'event_date'
