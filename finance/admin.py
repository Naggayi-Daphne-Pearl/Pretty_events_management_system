from django.contrib import admin

from .models import ExpenseCategory, ExpenseRecord, IncomeRecord


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(IncomeRecord)
class IncomeRecordAdmin(admin.ModelAdmin):
    list_display = ('date', 'amount', 'source', 'event', 'recorded_by')
    list_filter = ('source', 'date')
    search_fields = ('description',)


@admin.register(ExpenseRecord)
class ExpenseRecordAdmin(admin.ModelAdmin):
    list_display = ('date', 'amount', 'category', 'event', 'recorded_by')
    list_filter = ('category', 'date')
    search_fields = ('description',)
