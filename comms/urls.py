from django.urls import path

from . import views

app_name = 'comms'

urlpatterns = [
    path('', views.CommunicationLogListView.as_view(), name='list'),
    path('log/<int:customer_pk>/', views.log_create, name='log_create'),
]
