from django.urls import path

from . import views

app_name = 'comms'

urlpatterns = [
    path('', views.CommunicationLogListView.as_view(), name='list'),
    path('log/<int:customer_pk>/', views.log_create, name='log_create'),
    path('<int:pk>/edit/', views.log_update, name='log_update'),
    path('<int:pk>/delete/', views.log_delete, name='log_delete'),
    path('contact/<int:customer_pk>/<str:channel>/', views.contact_customer, name='contact'),
]
