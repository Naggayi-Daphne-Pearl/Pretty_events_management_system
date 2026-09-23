from django.urls import path

from . import views

app_name = 'accounting'

urlpatterns = [
    path('', views.chart_of_accounts, name='chart'),
    path('accounts/new/', views.account_create, name='account_create'),
    path('accounts/<int:pk>/', views.account_detail, name='account_detail'),
    path('accounts/<int:pk>/edit/', views.account_update, name='account_update'),
    path('accounts/<int:pk>/entry/', views.account_entry, name='account_entry'),
    path('accounts/<int:pk>/delete/', views.account_delete, name='account_delete'),
    path('journals/', views.journal_list, name='journal_list'),
    path('journals/new/', views.journal_create, name='journal_create'),
    path('journals/<int:pk>/', views.journal_detail, name='journal_detail'),
    path('journals/<int:pk>/edit/', views.journal_update, name='journal_update'),
    path('journals/<int:pk>/delete/', views.journal_delete, name='journal_delete'),
    path('banking/', views.banking, name='banking'),
    path('banking/transfer/', views.transfer_create, name='transfer_create'),
    path('reports/', views.reports_index, name='reports'),
    path('reports/trial-balance/', views.trial_balance, name='trial_balance'),
    path('reports/income-statement/', views.income_statement, name='income_statement'),
    path('reports/balance-sheet/', views.balance_sheet, name='balance_sheet'),
]
