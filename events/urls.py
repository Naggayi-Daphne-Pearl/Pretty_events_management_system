from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.EventListView.as_view(), name='list'),
    path('new/', views.EventCreateView.as_view(), name='create'),
    path('<int:pk>/', views.EventDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.EventUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.event_delete, name='delete'),
]
