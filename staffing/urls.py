from django.urls import path

from . import views

app_name = 'staffing'

urlpatterns = [
    path('', views.StaffMemberListView.as_view(), name='list'),
    path('new/', views.staff_create, name='create'),
    path('<int:pk>/', views.StaffMemberDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.staff_update, name='update'),
    path('assign/<int:event_pk>/', views.assign_staff, name='assign'),
]
