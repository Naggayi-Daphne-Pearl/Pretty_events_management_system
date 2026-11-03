from django.urls import path

from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('', views.subscription_list, name='list'),
    path('new/', views.subscription_create, name='create'),
    path('<int:pk>/', views.subscription_detail, name='detail'),
    path('<int:pk>/edit/', views.subscription_update, name='update'),
    path('<int:pk>/delete/', views.subscription_delete, name='delete'),
    path('<int:pk>/invoice-now/', views.subscription_invoice_now, name='invoice_now'),
]
