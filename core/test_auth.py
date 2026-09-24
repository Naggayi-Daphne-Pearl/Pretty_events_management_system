import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from staffing.models import StaffMember

from .auth import SESSION_STARTED_KEY
from .models import FailedLoginAttempt

User = get_user_model()


def link_from(email_body):
    return re.search(r'https?://\S+', email_body).group(0)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jane', email='Jane@Example.com', password='Correct-Horse-9')

    def login(self, identifier, password='Correct-Horse-9'):
        return self.client.post(reverse('login'), {'username': identifier, 'password': password})

    def test_login_with_email_any_case(self):
        response = self.login('jane@example.COM')
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

    def test_username_still_works_for_old_admin_accounts(self):
        self.assertEqual(self.login('jane').status_code, 302)

    def test_wrong_password(self):
        response = self.login('jane@example.com', 'nope')
        self.assertContains(response, 'Incorrect email or password')

    def test_duplicate_emails_cannot_log_in_by_email(self):
        User.objects.create_user('jane2', email='jane@example.com', password='Correct-Horse-9')
        self.assertEqual(self.login('jane@example.com').status_code, 200)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login('jane@example.com').status_code, 200)

    def test_lockout_after_repeated_failures_even_with_right_password(self):
        for _ in range(5):
            self.login('jane@example.com', 'wrong')
        response = self.login('jane@example.com')
        self.assertContains(response, 'Too many failed attempts')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_lockout_expires(self):
        for _ in range(5):
            self.login('jane@example.com', 'wrong')
        FailedLoginAttempt.objects.update(created_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(self.login('jane@example.com').status_code, 302)

    def test_success_clears_failures(self):
        for _ in range(4):
            self.login('jane@example.com', 'wrong')
        self.login('jane@example.com')
        self.assertFalse(FailedLoginAttempt.objects.exists())

    @override_settings(EMAIL_ENABLED=True)
    def test_login_page_links_forgot_password(self):
        self.assertContains(self.client.get(reverse('login')), reverse('password_reset'))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ENABLED=True)
class ForgotPasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jane', email='jane@example.com', password='Old-Password-9')

    def test_full_reset_flow(self):
        response = self.client.post(reverse('password_reset'), {'email': 'JANE@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        link = link_from(mail.outbox[0].body)
        response = self.client.get(link, follow=True)
        self.assertContains(response, 'Choose a new password')
        response = self.client.post(response.redirect_chain[-1][0], {
            'new_password1': 'Brand-New-Pass-77', 'new_password2': 'Brand-New-Pass-77',
        })
        self.assertRedirects(response, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-New-Pass-77'))
        # The link is single-use.
        self.assertContains(self.client.get(link, follow=True), 'no longer works')

    def test_unknown_email_gets_same_page_and_no_mail(self):
        response = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_failure_does_not_crash_or_leak(self):
        from unittest import mock
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=TimeoutError), \
                self.assertLogs('django.contrib.auth', level='ERROR'):
            response = self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))

    def test_reset_clears_lockout(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'jane@example.com', 'password': 'bad'})
        self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        response = self.client.get(link_from(mail.outbox[0].body), follow=True)
        self.client.post(response.redirect_chain[-1][0], {'new_password1': 'Brand-New-Pass-77', 'new_password2': 'Brand-New-Pass-77'})
        response = self.client.post(reverse('login'), {'username': 'jane@example.com', 'password': 'Brand-New-Pass-77'})
        self.assertEqual(response.status_code, 302)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ENABLED=True)
class StaffInviteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'Admin-Pass-99')
        self.client.force_login(self.admin)

    def create_staff(self, **login):
        data = {'full_name': 'New Person', 'phone': '', 'title': '', 'is_active': 'on', 'create_login': '1',
                'login-email': 'new.person@example.com'}
        data.update({f'login-{k}': v for k, v in login.items()})
        return self.client.post(reverse('staffing:create'), data)

    def test_invite_is_emailed_and_sets_password(self):
        self.create_staff()
        user = User.objects.get(email='new.person@example.com')
        self.assertFalse(user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('invited', mail.outbox[0].subject)
        link = link_from(mail.outbox[0].body)
        self.assertIn('/welcome/', link)

        self.client.logout()
        response = self.client.get(link, follow=True)
        self.assertContains(response, 'Welcome to')
        self.client.post(response.redirect_chain[-1][0], {'new_password1': 'Chosen-Pass-123', 'new_password2': 'Chosen-Pass-123'})
        response = self.client.post(reverse('login'), {'username': 'new.person@example.com', 'password': 'Chosen-Pass-123'})
        self.assertEqual(response.status_code, 302)

    def test_admin_can_set_password_instead(self):
        self.create_staff(set_password_now='on', password1='Temp-Pass-4567', password2='Temp-Pass-4567')
        user = User.objects.get(email='new.person@example.com')
        self.assertTrue(user.check_password('Temp-Pass-4567'))
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_email_rejected(self):
        User.objects.create_user('someone', email='NEW.person@example.com')
        response = self.create_staff()
        self.assertContains(response, 'already uses this email')

    def test_invite_failure_still_creates_login_with_warning(self):
        from unittest import mock
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=TimeoutError), \
                self.assertLogs('core.emailing', level='ERROR'):
            response = self.create_staff()
        self.assertTrue(User.objects.filter(email='new.person@example.com').exists())
        self.assertIn('could not be sent', ' '.join(str(m) for m in response.wsgi_request._messages))

    def test_resend_invite_and_reset_from_staff_page(self):
        self.create_staff()
        staff = StaffMember.objects.get(full_name='New Person')
        mail.outbox.clear()
        self.client.post(reverse('user_send_reset', args=[staff.user.pk]))
        self.assertIn('/welcome/', mail.outbox[0].body)  # never set a password -> invite again
        staff.user.set_password('Now-Has-One-1')
        staff.user.save()
        self.client.post(reverse('user_send_reset', args=[staff.user.pk]))
        self.assertIn('/password-reset/', mail.outbox[1].body)

    def test_send_reset_is_superuser_only_and_post_only(self):
        target = User.objects.create_user('t', email='t@example.com')
        self.assertEqual(self.client.get(reverse('user_send_reset', args=[target.pk])).status_code, 405)
        other = User.objects.create_user('staffer', email='s@example.com', password='x')
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('user_send_reset', args=[target.pk])).status_code, 403)


class SessionLifetimeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'boss@example.com', 'Admin-Pass-99')

    def test_login_stamps_session_start(self):
        self.client.post(reverse('login'), {'username': 'boss@example.com', 'password': 'Admin-Pass-99'})
        self.assertIn(SESSION_STARTED_KEY, self.client.session)

    @override_settings(SESSION_MAX_AGE_HOURS=12)
    def test_session_older_than_max_is_logged_out(self):
        self.client.post(reverse('login'), {'username': 'boss@example.com', 'password': 'Admin-Pass-99'})
        session = self.client.session
        session[SESSION_STARTED_KEY] = (timezone.now() - timedelta(hours=13)).timestamp()
        session.save()
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactivity_and_browser_close_settings(self):
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_AGE, 30 * 60)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)


class StaffPasswordRulesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'Admin-Pass-99')
        self.client.force_login(self.admin)

    def create(self, password):
        return self.client.post(reverse('staffing:create'), {
            'full_name': 'New Person', 'is_active': 'on', 'create_login': '1',
            'login-email': 'new.person@example.com', 'login-password1': password, 'login-password2': password,
        })

    def test_rules_are_shown_on_the_form(self):
        self.assertContains(self.client.get(reverse('staffing:create')), 'At least 8 characters')

    def test_weak_password_explains_why(self):
        response = self.create('12345678')
        self.assertContains(response, 'entirely numeric')
        self.assertFalse(User.objects.filter(email='new.person@example.com').exists())

    def test_admin_set_password_logs_in_by_email(self):
        self.create('Kampala-Tent-2026')
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': 'New.Person@example.com', 'password': 'Kampala-Tent-2026'})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
