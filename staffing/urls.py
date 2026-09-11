from django.urls import path

from . import views

app_name = 'staffing'

urlpatterns = [
    path('', views.StaffMemberListView.as_view(), name='list'),
    path('new/', views.StaffMemberCreateView.as_view(), name='create'),
    path('<int:pk>/', views.StaffMemberDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.StaffMemberUpdateView.as_view(), name='update'),
    path('assign/<int:event_pk>/', views.assign_staff, name='assign'),
]
