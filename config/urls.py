from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.forms import EmailAuthenticationForm, EmailPasswordResetForm, EmailSetPasswordForm
from core.views import (
    activity_log, activity_log_export, dashboard, profile, role_delete, role_form, role_list, user_send_reset,
    user_set_password,
)

# Auth pages render in the centred login-style layout even for a logged-in visitor
# (e.g. opening a reset link in a browser that's still signed in).
AUTH_PAGE = {'auth_page': True}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html', authentication_form=EmailAuthenticationForm,
        redirect_authenticated_user=True,
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Forgot password: request link -> "check your email" -> set new password -> done.
    path('password-reset/', auth_views.PasswordResetView.as_view(
        form_class=EmailPasswordResetForm,
        template_name='registration/password_reset_form.html', extra_context=AUTH_PAGE,
        email_template_name='registration/password_reset_email.txt',
        subject_template_name='registration/password_reset_subject.txt',
    ), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html', extra_context=AUTH_PAGE,
    ), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        form_class=EmailSetPasswordForm, template_name='registration/password_reset_confirm.html', extra_context=AUTH_PAGE,
    ), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html', extra_context=AUTH_PAGE,
    ), name='password_reset_complete'),
    # New staff: the invite email links here to choose a first password (same secure token).
    path('welcome/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        form_class=EmailSetPasswordForm, template_name='registration/invite_accept.html', extra_context=AUTH_PAGE,
    ), name='invite_accept'),
    path('accounts/<int:pk>/send-reset/', user_send_reset, name='user_send_reset'),
    path('profile/', profile, name='profile'),
    path('roles/', role_list, name='role_list'),
    path('roles/new/', role_form, name='role_create'),
    path('roles/<int:pk>/edit/', role_form, name='role_update'),
    path('roles/<int:pk>/delete/', role_delete, name='role_delete'),
    path('accounts/<int:pk>/password/', user_set_password, name='user_set_password'),
    path('activity/', activity_log, name='activity_log'),
    path('activity/export/', activity_log_export, name='activity_log_export'),
    path('customers/', include('customers.urls')),
    path('events/', include('events.urls')),
    path('billing/', include('billing.urls')),
    path('inventory/', include('inventory.urls')),
    path('finance/', include('finance.urls')),
    path('staff/', include('staffing.urls')),
    path('communication/', include('comms.urls')),
    path('reports/', include('reports.urls')),
    path('accounting/', include('accounting.urls')),
]
