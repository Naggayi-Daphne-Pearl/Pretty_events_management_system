from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('quotations/', views.QuotationListView.as_view(), name='quotation_list'),
    path('quotations/new/<int:event_pk>/', views.quotation_create, name='quotation_create'),
    path('quotations/<int:pk>/', views.QuotationDetailView.as_view(), name='quotation_detail'),
    path('quotations/<int:pk>/edit/', views.quotation_update, name='quotation_update'),
    path('quotations/<int:pk>/convert/', views.quotation_convert, name='quotation_convert'),
    path('quotations/<int:pk>/pdf/', views.quotation_pdf, name='quotation_pdf'),
    path('quotations/<int:pk>/email/', views.quotation_email, name='quotation_email'),
    path('quotations/<int:pk>/delete/', views.quotation_delete, name='quotation_delete'),

    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.invoice_update, name='invoice_update'),
    path('invoices/<int:pk>/pay/', views.invoice_add_payment, name='invoice_add_payment'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('invoices/<int:pk>/email/', views.invoice_email, name='invoice_email'),

    path('receipts/<int:pk>/', views.ReceiptDetailView.as_view(), name='receipt_detail'),
    path('receipts/<int:pk>/pdf/', views.receipt_pdf, name='receipt_pdf'),
]
