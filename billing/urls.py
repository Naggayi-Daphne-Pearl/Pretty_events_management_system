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
    path('invoices/<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),

    path('receipts/', views.ReceiptListView.as_view(), name='receipt_list'),
    path('receipts/<int:pk>/', views.ReceiptDetailView.as_view(), name='receipt_detail'),
    path('receipts/<int:pk>/email/', views.receipt_email, name='receipt_email'),
    path('receipts/<int:pk>/pdf/', views.receipt_pdf, name='receipt_pdf'),

    path('shared/<str:token>/', views.shared_document, name='shared_document'),
    path('shared/<str:token>/pdf/', views.shared_document_pdf, name='shared_document_pdf'),
    path('shared/<str:token>/accept/', views.shared_quotation_accept, name='shared_quotation_accept'),

    path('taxes/', views.TaxGroupListView.as_view(), name='tax_list'),
    path('taxes/new/', views.TaxGroupCreateView.as_view(), name='tax_create'),
    path('taxes/<int:pk>/edit/', views.TaxGroupUpdateView.as_view(), name='tax_update'),

    path('mobile-money/', views.mobile_money_list, name='mobile_money'),
    path('mobile-money/<int:pk>/allocate/', views.mobile_money_allocate, name='mobile_money_allocate'),
    path('mobile-money/webhook/<slug:provider>/', views.mobile_money_webhook, name='mobile_money_webhook'),
]
