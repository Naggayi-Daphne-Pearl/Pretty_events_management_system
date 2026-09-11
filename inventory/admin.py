from django.contrib import admin

from .models import EquipmentCategory, EquipmentIssue, EquipmentItem, EquipmentReturn


@admin.register(EquipmentCategory)
class EquipmentCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(EquipmentItem)
class EquipmentItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'total_quantity', 'available_quantity', 'unit')
    list_filter = ('category',)
    search_fields = ('name',)


class EquipmentReturnInline(admin.TabularInline):
    model = EquipmentReturn
    extra = 0


@admin.register(EquipmentIssue)
class EquipmentIssueAdmin(admin.ModelAdmin):
    list_display = ('equipment_item', 'event', 'quantity_issued', 'quantity_returned', 'is_fully_returned', 'issued_at')
    list_filter = ('issued_at',)
    search_fields = ('equipment_item__name', 'event__customer__name')
    inlines = [EquipmentReturnInline]
