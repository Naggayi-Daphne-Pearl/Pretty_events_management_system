from django.urls import path

from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.EquipmentItemListView.as_view(), name='item_list'),
    path('new/', views.EquipmentItemCreateView.as_view(), name='item_create'),
    path('categories/', views.EquipmentCategoryListView.as_view(), name='category_list'),
    path('categories/new/', views.EquipmentCategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.EquipmentCategoryUpdateView.as_view(), name='category_update'),
    path('<int:pk>/', views.EquipmentItemDetailView.as_view(), name='item_detail'),
    path('<int:pk>/edit/', views.EquipmentItemUpdateView.as_view(), name='item_update'),
    path('<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('issue/<int:event_pk>/', views.issue_create, name='issue_create'),
    path('return/<int:issue_pk>/', views.return_create, name='return_create'),
]
