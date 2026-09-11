from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.summary, name='summary'),
    path('income/', views.IncomeListView.as_view(), name='income_list'),
    path('income/new/', views.IncomeCreateView.as_view(), name='income_create'),
    path('expenses/', views.ExpenseListView.as_view(), name='expense_list'),
    path('expenses/new/', views.ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/categories/', views.ExpenseCategoryListView.as_view(), name='category_list'),
    path('expenses/categories/new/', views.ExpenseCategoryCreateView.as_view(), name='category_create'),
    path('expenses/categories/<int:pk>/edit/', views.ExpenseCategoryUpdateView.as_view(), name='category_update'),
]
