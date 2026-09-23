from django.contrib import admin

from .models import Account, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'detail_type', 'parent', 'is_active', 'system_key')
    list_filter = ('account_type', 'detail_type', 'is_active')
    search_fields = ('code', 'name')
    readonly_fields = ('system_key',)


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    """Read-only here: entries must go through the app so they're validated as balanced."""
    list_display = ('number', 'date', 'source', 'memo', 'reference')
    list_filter = ('source',)
    search_fields = ('number', 'memo', 'reference')
    date_hierarchy = 'date'
    list_per_page = 50
    inlines = [JournalLineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
