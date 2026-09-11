from django.contrib import admin

from .models import Invoice, InvoiceLineItem, Payment, Quotation, QuotationLineItem, Receipt


class QuotationLineItemInline(admin.TabularInline):
    model = QuotationLineItem
    extra = 1


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 1


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ('number', 'event', 'status', 'total', 'created_at')
    list_filter = ('status',)
    search_fields = ('number', 'event__customer__name')
    inlines = [QuotationLineItemInline]
    readonly_fields = ('number',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'event', 'status', 'total', 'amount_paid', 'balance_due', 'issue_date')
    list_filter = ('status',)
    search_fields = ('number', 'event__customer__name')
    inlines = [InvoiceLineItemInline]
    readonly_fields = ('number',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'amount', 'method', 'reference_number', 'paid_at', 'received_by')
    list_filter = ('method', 'paid_at')
    search_fields = ('invoice__number', 'reference_number')


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('number', 'payment', 'issued_at')
    readonly_fields = ('number',)
