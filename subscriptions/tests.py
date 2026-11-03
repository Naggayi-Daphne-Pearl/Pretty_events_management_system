from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from config import clients
from customers.models import Customer
from events.models import Event

from .forms import SubscriptionForm
from .models import Subscription, add_months
from .services import MAX_CATCH_UP, invoice_due_subscriptions, invoice_next_period

HARRAH = clients.settings_for(clients.load('harrah_designs'))


class AddMonthsTests(TestCase):
    def test_short_months_clamp_to_last_day(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 30), 3), date(2027, 2, 28))


@override_settings(**HARRAH)
class RenewalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        customer = Customer.objects.create(name='Acme', phone='0772000001')
        self.event = Event.objects.create(customer=customer, event_type='Business website', event_date=self.today)

    def make(self, start, interval=Subscription.Interval.YEARLY, **extra):
        return Subscription.objects.create(event=self.event, name='Hosting', amount=Decimal('350000'),
                                           interval=interval, start_date=start, **extra)

    def form_data(self, **overrides):
        data = {'event': self.event.pk, 'name': 'Hosting', 'amount': '350000', 'interval': 'yearly',
                'start_date': self.today + timedelta(days=30), 'invoice_days_before': 14, 'is_active': 'on'}
        data.update(overrides)
        return data

    def test_daily_job_invoices_only_renewals_inside_their_window(self):
        due = self.make(self.today + timedelta(days=5))
        later = self.make(self.today + timedelta(days=60))
        self.assertEqual(invoice_due_subscriptions(self.today), 1)
        due.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(due.invoices.count(), 1)
        self.assertEqual(due.next_due_date, add_months(due.start_date, 12))
        self.assertEqual(later.invoices.count(), 0)
        self.assertEqual(invoice_due_subscriptions(self.today), 0, 'a second run the same day raises nothing new')

    def test_stopped_renewal_is_not_invoiced(self):
        self.make(self.today + timedelta(days=5), is_active=False)
        self.assertEqual(invoice_due_subscriptions(self.today), 0)

    def test_catch_up_is_capped_per_run(self):
        sub = self.make(self.today - timedelta(days=800), interval=Subscription.Interval.MONTHLY)
        invoice_due_subscriptions(self.today)
        self.assertEqual(sub.invoices.count(), MAX_CATCH_UP)

    def test_invoice_lists_the_period(self):
        sub = self.make(date(2027, 1, 15))
        invoice = invoice_next_period(sub, today=date(2027, 1, 1))
        line = invoice.line_items.get()
        self.assertIn('15 Jan 2027', line.description)
        self.assertIn('14 Jan 2028', line.description)
        self.assertEqual(invoice.due_date, date(2027, 1, 15))

    def test_new_renewal_cannot_start_in_the_past(self):
        form = SubscriptionForm(data=self.form_data(start_date=self.today - timedelta(days=1)))
        self.assertFalse(form.is_valid())
        self.assertIn('start_date', form.errors)
        self.assertTrue(SubscriptionForm(data=self.form_data(start_date=self.today)).is_valid())

    def test_existing_renewal_with_past_start_can_still_be_edited(self):
        sub = self.make(self.today + timedelta(days=200))
        Subscription.objects.filter(pk=sub.pk).update(start_date=self.today - timedelta(days=10))
        sub.refresh_from_db()
        form = SubscriptionForm(data=self.form_data(start_date=sub.start_date, amount='400000'), instance=sub)
        self.assertTrue(form.is_valid(), form.errors)

    def test_invoice_now_and_pages(self):
        sub = self.make(self.today + timedelta(days=60))
        self.client.post(reverse('subscriptions:invoice_now', args=[sub.pk]))
        self.assertEqual(sub.invoices.count(), 1)
        for url in (reverse('subscriptions:list'), reverse('subscriptions:detail', args=[sub.pk]),
                    reverse('subscriptions:create'), reverse('subscriptions:update', args=[sub.pk])):
            self.assertEqual(self.client.get(url).status_code, 200, url)


@override_settings(**HARRAH)
class HarrahWordingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)

    def test_reword_keeps_case(self):
        from core.client import reword
        self.assertEqual(reword('Can view customer'), 'Can view client')
        self.assertEqual(reword('Events this week'), 'Projects this week')
        self.assertEqual(reword('EVENT DATE'), 'PROJECT DATE')

    def test_pages_use_the_business_words(self):
        for name in ('customers:list', 'customers:create', 'dashboard', 'reports:index', 'role_create'):
            body = self.client.get(reverse(name)).content.decode()
            for word in ('New Customer', 'Events this week', 'Event Summary', 'Can view customer'):
                self.assertNotIn(word, body, f'{name} says "{word}"')

    def test_staff_without_login_has_no_required_hidden_fields(self):
        body = self.client.get(reverse('staffing:create')).content.decode()
        self.assertNotIn('name="login-email" required', body)
        response = self.client.post(reverse('staffing:create'), {'full_name': 'Dev', 'phone': '0772000002', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
