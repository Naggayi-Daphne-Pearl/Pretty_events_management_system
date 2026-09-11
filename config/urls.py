from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.views import activity_log, dashboard, profile, role_delete, role_form, role_list, user_set_password

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', profile, name='profile'),
    path('roles/', role_list, name='role_list'),
    path('roles/new/', role_form, name='role_create'),
    path('roles/<int:pk>/edit/', role_form, name='role_update'),
    path('roles/<int:pk>/delete/', role_delete, name='role_delete'),
    path('accounts/<int:pk>/password/', user_set_password, name='user_set_password'),
    path('activity/', activity_log, name='activity_log'),
    path('customers/', include('customers.urls')),
    path('events/', include('events.urls')),
    path('billing/', include('billing.urls')),
    path('inventory/', include('inventory.urls')),
    path('finance/', include('finance.urls')),
    path('staff/', include('staffing.urls')),
    path('communication/', include('comms.urls')),
    path('reports/', include('reports.urls')),
]
