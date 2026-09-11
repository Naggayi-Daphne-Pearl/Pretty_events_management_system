from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.EquipmentItemListView.as_view(), name='item_list'),
    path('new/', views.EquipmentItemCreateView.as_view(), name='item_create'),
    path('<int:pk>/', views.EquipmentItemDetailView.as_view(), name='item_detail'),
    path('<int:pk>/edit/', views.EquipmentItemUpdateView.as_view(), name='item_update'),
    path('issue/<int:event_pk>/', views.issue_create, name='issue_create'),
    path('return/<int:issue_pk>/', views.return_create, name='return_create'),
]
