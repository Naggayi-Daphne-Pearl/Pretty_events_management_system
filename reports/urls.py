from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.index, name='index'),
    path('events/', views.event_summary, name='event_summary'),
    path('outstanding-payments/', views.outstanding_payments, name='outstanding_payments'),
    path('inventory/', views.inventory_summary, name='inventory_summary'),
]
