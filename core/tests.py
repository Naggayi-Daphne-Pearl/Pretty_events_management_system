from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem, Payment, Quotation, QuotationLineItem
from comms.models import CommunicationLog
from customers.models import Customer
from events.models import Event
from events.services import sync_event_statuses
from inventory.models import EquipmentIssue, EquipmentItem, EquipmentReturn
from staffing.models import EventAssignment, StaffMember

from .once import issue_token
from .phone import to_international


class PhoneTests(TestCase):
    def test_local_numbers_get_uganda_code(self):
        self.assertEqual(to_international('0772 123 456'), '256772123456')
        self.assertEqual(to_international('772123456'), '256772123456')

    def test_international_numbers_are_kept(self):
        self.assertEqual(to_international('+256 772 123456'), '256772123456')
        self.assertEqual(to_international('+44 20 7946 0958'), '442079460958')
        self.assertEqual(to_international('0044 20 7946 0958'), '442079460958')
        self.assertEqual(to_international('256772123456'), '256772123456')

    def test_empty(self):
        self.assertEqual(to_international(''), '')
        self.assertEqual(to_international(None), '')


class BaseDataMixin:
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Jane Doe', phone='0772123456', email='jane@example.com')
        self.event = Event.objects.create(
            customer=self.customer, event_type='Wedding', event_date=timezone.localdate() + timedelta(days=10),
            venue='Kampala',
        )

    def make_invoice(self, amount='100000'):
        invoice = Invoice.objects.create(event=self.event)
        InvoiceLineItem.objects.create(invoice=invoice, description='Tent', quantity=1, unit_price=Decimal(amount))
        return invoice


class DeleteTests(BaseDataMixin, TestCase):
    def test_customer_with_events_cannot_be_deleted(self):
        response = self.client.post(reverse('customers:delete', args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "can't be deleted")
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())

    def test_customer_without_events_is_deleted_with_their_logs(self):
        lonely = Customer.objects.create(name='Walk In', phone='0700000000')
        CommunicationLog.objects.create(customer=lonely, message='hi')
        response = self.client.post(reverse('customers:delete', args=[lonely.pk]))
        self.assertRedirects(response, reverse('customers:list'))
        self.assertFalse(Customer.objects.filter(pk=lonely.pk).exists())
        self.assertFalse(CommunicationLog.objects.filter(customer_id=lonely.pk).exists())

    def test_event_with_quotation_is_blocked_but_bare_event_is_deleted(self):
        Quotation.objects.create(event=self.event)
        self.client.post(reverse('events:delete', args=[self.event.pk]))
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())

        bare = Event.objects.create(customer=self.customer, event_type='Party', event_date=timezone.localdate(), venue='X')
        self.client.post(reverse('events:delete', args=[bare.pk]))
        self.assertFalse(Event.objects.filter(pk=bare.pk).exists())

    def test_invoice_with_payment_cannot_be_deleted(self):
        invoice = self.make_invoice()
        Payment.objects.create(invoice=invoice, amount=Decimal('1000'))
        self.client.post(reverse('billing:invoice_delete', args=[invoice.pk]))
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_unpaid_invoice_is_deleted(self):
        invoice = self.make_invoice()
        self.client.post(reverse('billing:invoice_delete', args=[invoice.pk]))
        self.assertFalse(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_staff_with_assignment_or_login_is_blocked(self):
        assigned = StaffMember.objects.create(full_name='Assigned')
        EventAssignment.objects.create(event=self.event, staff_member=assigned)
        with_login = StaffMember.objects.create(full_name='Has Login', user=self.user)
        free = StaffMember.objects.create(full_name='Free')
        for staff in (assigned, with_login, free):
            self.client.post(reverse('staffing:delete', args=[staff.pk]))
        self.assertTrue(StaffMember.objects.filter(pk=assigned.pk).exists())
        self.assertTrue(StaffMember.objects.filter(pk=with_login.pk).exists())
        self.assertFalse(StaffMember.objects.filter(pk=free.pk).exists())

    def test_equipment_used_on_a_quotation_is_blocked(self):
        quoted = EquipmentItem.objects.create(name='Chair', total_quantity=10)
        q = Quotation.objects.create(event=self.event)
        QuotationLineItem.objects.create(quotation=q, equipment_item=quoted, description='Chair', unit_price=1)
        unused = EquipmentItem.objects.create(name='Table', total_quantity=2)
        self.client.post(reverse('inventory:item_delete', args=[quoted.pk]))
        self.client.post(reverse('inventory:item_delete', args=[unused.pk]))
        self.assertTrue(EquipmentItem.objects.filter(pk=quoted.pk).exists())
        self.assertFalse(EquipmentItem.objects.filter(pk=unused.pk).exists())

    def test_get_only_shows_confirmation(self):
        lonely = Customer.objects.create(name='Walk In', phone='0700000000')
        response = self.client.get(reverse('customers:delete', args=[lonely.pk]))
        self.assertContains(response, 'Are you sure')
        self.assertTrue(Customer.objects.filter(pk=lonely.pk).exists())


@override_settings(COMPANY_LEGAL_NAME='PRETTY EVENTS LTD.')
class ContactTests(BaseDataMixin, TestCase):
    def test_whatsapp_logs_and_redirects_with_invoice_message(self):
        invoice = self.make_invoice('250000')
        response = self.client.post(
            reverse('comms:contact', args=[self.customer.pk, 'whatsapp']), {'document': f'invoice:{invoice.pk}'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('https://wa.me/256772123456?text='))
        self.assertIn(invoice.number, response['Location'])
        log = CommunicationLog.objects.get()
        self.assertEqual(log.channel, 'whatsapp')
        self.assertEqual(log.event, self.event)
        self.assertIn('250,000', log.message)

    def test_call_redirects_to_dialer(self):
        response = self.client.post(reverse('comms:contact', args=[self.customer.pk, 'call']), {'event': self.event.pk})
        self.assertEqual(response['Location'], 'tel:+256772123456')
        self.assertEqual(CommunicationLog.objects.get().event, self.event)

    def test_get_is_rejected_and_logs_nothing(self):
        response = self.client.get(reverse('comms:contact', args=[self.customer.pk, 'whatsapp']))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(CommunicationLog.objects.exists())

    def test_other_customers_document_is_ignored(self):
        other = Customer.objects.create(name='Other', phone='0700111222')
        other_event = Event.objects.create(customer=other, event_type='X', event_date=timezone.localdate(), venue='Y')
        invoice = Invoice.objects.create(event=other_event)
        response = self.client.post(
            reverse('comms:contact', args=[self.customer.pk, 'whatsapp']),
            {'document': f'invoice:{invoice.pk}', 'event': 'junk'},
        )
        self.assertNotIn(invoice.number, response['Location'])
        self.assertIsNone(CommunicationLog.objects.get().event)

    def test_missing_phone_shows_error(self):
        self.customer.phone = ''
        self.customer.save()
        self.client.post(reverse('comms:contact', args=[self.customer.pk, 'call']))
        self.assertFalse(CommunicationLog.objects.exists())

    def test_unknown_channel_404s(self):
        response = self.client.post(reverse('comms:contact', args=[self.customer.pk, 'fax']))
        self.assertEqual(response.status_code, 404)


class QuickAddEventTests(BaseDataMixin, TestCase):
    def event_data(self, **extra):
        data = {
            'customer': '', 'event_type': 'Introduction', 'status': 'inquiry',
            'event_date': (timezone.localdate() + timedelta(days=30)).isoformat(), 'venue': 'Mukono',
        }
        data.update(extra)
        return data

    def test_new_customer_created_with_event(self):
        response = self.client.post(reverse('events:create'), self.event_data(
            new_customer_name='New Client', new_customer_phone='0701 555 666',
        ))
        event = Event.objects.get(event_type='Introduction')
        self.assertRedirects(response, event.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(event.customer.name, 'New Client')
        self.assertEqual(event.customer.created_by, self.user)

    def test_duplicate_phone_is_rejected(self):
        response = self.client.post(reverse('events:create'), self.event_data(
            new_customer_name='Jane Again', new_customer_phone='+256 772 123456',
        ))
        self.assertContains(response, 'already has this phone number')
        self.assertEqual(Customer.objects.count(), 1)

    def test_customer_or_new_details_required(self):
        response = self.client.post(reverse('events:create'), self.event_data())
        self.assertContains(response, 'Pick an existing customer')

    def test_save_and_create_quotation(self):
        response = self.client.post(reverse('events:create'), self.event_data(
            customer=self.customer.pk, then='quotation',
        ))
        event = Event.objects.get(event_type='Introduction')
        self.assertRedirects(response, reverse('billing:quotation_create', args=[event.pk]), fetch_redirect_response=False)


class AutoStatusTests(BaseDataMixin, TestCase):
    def test_payment_confirms_event(self):
        invoice = self.make_invoice()
        self.client.post(reverse('billing:invoice_add_payment', args=[invoice.pk]), {
            'amount': '50000', 'method': 'cash', 'paid_at': timezone.localdate().isoformat(),
            'once_token': issue_token(self.user),
        })
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CONFIRMED)

    def test_calendar_moves_confirmed_events_only(self):
        today = timezone.localdate()
        self.event.event_date = today
        self.event.status = Event.Status.CONFIRMED
        self.event.save()
        inquiry = Event.objects.create(customer=self.customer, event_type='Old inquiry', event_date=today - timedelta(days=5), venue='X')
        sync_event_statuses(today)
        self.event.refresh_from_db()
        inquiry.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.IN_PROGRESS)
        self.assertEqual(inquiry.status, Event.Status.INQUIRY)

    def test_completion_waits_for_equipment_return(self):
        today = timezone.localdate()
        self.event.event_date = today - timedelta(days=2)
        self.event.status = Event.Status.CONFIRMED
        self.event.save()
        item = EquipmentItem.objects.create(name='Tent', total_quantity=3)
        issue = EquipmentIssue.objects.create(event=self.event, equipment_item=item, quantity_issued=2, issued_at=today)

        sync_event_statuses(today)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.IN_PROGRESS)

        EquipmentReturn.objects.create(issue=issue, quantity_returned=2, returned_at=today)
        sync_event_statuses(today)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.COMPLETED)


class PagesRenderTests(BaseDataMixin, TestCase):
    """Smoke test: the reworked pages render for a fully populated event."""

    def test_hub_and_timeline_render(self):
        invoice = self.make_invoice()
        Payment.objects.create(invoice=invoice, amount=Decimal('1000'))
        CommunicationLog.objects.create(customer=self.customer, event=self.event, message='Called about tents')
        for url in (
            reverse('events:detail', args=[self.event.pk]),
            reverse('customers:detail', args=[self.customer.pk]),
            reverse('comms:list') + '?channel=call',
            reverse('events:create'),
            reverse('billing:invoice_detail', args=[invoice.pk]),
            reverse('dashboard'),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_event_hub_suggests_payment(self):
        self.make_invoice('300000')
        response = self.client.get(reverse('events:detail', args=[self.event.pk]))
        self.assertContains(response, 'Next step')
        self.assertContains(response, 'Record payment')

    def test_timeline_shows_billing_balance(self):
        invoice = self.make_invoice('300000')
        Payment.objects.create(invoice=invoice, amount=Decimal('100000'))
        response = self.client.get(reverse('customers:detail', args=[self.customer.pk]))
        self.assertContains(response, '200,000')
        self.assertContains(response, f'Invoice {invoice.number}')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReceiptTests(BaseDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.invoice = self.make_invoice('300000')
        self.payment = Payment.objects.create(invoice=self.invoice, amount=Decimal('100000'), paid_at=timezone.localdate())
        self.receipt = self.payment.receipt

    def test_receipt_list_and_search(self):
        response = self.client.get(reverse('billing:receipt_list'))
        self.assertContains(response, self.receipt.number)
        response = self.client.get(reverse('billing:receipt_list'), {'q': 'nobody-matches'})
        self.assertNotContains(response, self.receipt.number)
        response = self.client.get(reverse('billing:receipt_list'), {'q': 'Jane'})
        self.assertContains(response, self.receipt.number)

    def test_receipt_page_offers_sending(self):
        response = self.client.get(reverse('billing:receipt_detail', args=[self.receipt.pk]))
        self.assertContains(response, 'Send receipt to client')
        self.assertContains(response, reverse('billing:receipt_email', args=[self.receipt.pk]))
        self.assertContains(response, reverse('comms:contact', args=[self.customer.pk, 'whatsapp']))

    def test_email_receipt_sends_and_logs(self):
        from django.core import mail
        url = reverse('billing:receipt_email', args=[self.receipt.pk])
        form = self.client.get(url).context['form']
        self.assertIn('200,000', form.initial['message'])
        response = self.client.post(url, {'to_email': 'jane@example.com', 'message': form.initial['message'],
                                          'once_token': issue_token(self.user)})
        self.assertRedirects(response, reverse('billing:receipt_detail', args=[self.receipt.pk]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.receipt.number, mail.outbox[0].subject)
        log = CommunicationLog.objects.get()
        self.assertEqual(log.event, self.event)
        self.assertIn(self.receipt.number, log.message)

    def test_whatsapp_receipt_message(self):
        response = self.client.post(
            reverse('comms:contact', args=[self.customer.pk, 'whatsapp']), {'document': f'receipt:{self.receipt.pk}'},
        )
        self.assertIn(self.receipt.number, response['Location'])
        self.assertEqual(CommunicationLog.objects.get().event, self.event)

    def test_event_page_links_receipt(self):
        response = self.client.get(reverse('events:detail', args=[self.event.pk]))
        self.assertContains(response, self.receipt.number)


class ListStateTests(TestCase):
    """The empty, filtered-to-nothing and populated states of list pages."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)

    def test_empty_list_explains_and_offers_next_action(self):
        response = self.client.get(reverse('customers:list'))
        self.assertContains(response, 'No customers yet')
        self.assertContains(response, 'Add your first customer')
        self.assertNotContains(response, 'Clear filters')

    def test_filtered_to_nothing_is_distinct_and_offers_clear(self):
        Customer.objects.create(name='Jane', phone='0772000000')
        response = self.client.get(reverse('customers:list'), {'q': 'zzz'})
        self.assertContains(response, 'No customers match your filters')
        self.assertContains(response, 'Clear filters')
        self.assertNotContains(response, 'No customers yet')

    def test_populated_list_shows_count_and_filter_indicator(self):
        for i in range(3):
            Customer.objects.create(name=f'Jane {i}', phone=f'077200000{i}')
        response = self.client.get(reverse('customers:list'))
        self.assertContains(response, 'Showing 1–3 of 3')
        response = self.client.get(reverse('customers:list'), {'q': 'Jane 1'})
        self.assertContains(response, 'Showing 1–1 of 1')
        self.assertContains(response, 'Filtered')

    def test_every_list_page_renders_empty(self):
        for name in ('customers:list', 'events:list', 'billing:quotation_list', 'billing:invoice_list',
                     'billing:receipt_list', 'comms:list', 'inventory:item_list', 'inventory:category_list',
                     'staffing:list', 'finance:income_list', 'finance:expense_list', 'finance:category_list',
                     'activity_log'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'yet')

    def test_status_filter_to_nothing(self):
        response = self.client.get(reverse('billing:invoice_list'), {'status': 'paid'})
        self.assertContains(response, 'No invoices match your filters')


class ErrorLoggingTests(TestCase):
    def test_server_errors_are_logged_to_console(self):
        from django.conf import settings
        self.assertIn('console', settings.LOGGING['loggers']['django']['handlers'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DuplicateSubmitTests(BaseDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.invoice = self.make_invoice('300000')

    def pay(self, token):
        return self.client.post(reverse('billing:invoice_add_payment', args=[self.invoice.pk]), {
            'amount': '1000', 'method': 'cash', 'paid_at': timezone.localdate().isoformat(), 'once_token': token,
        })

    def test_same_payment_form_submitted_twice_records_once(self):
        token = issue_token(self.user)
        self.pay(token)
        response = self.pay(token)
        self.assertEqual(self.invoice.payments.count(), 1)
        self.assertRedirects(response, self.invoice.get_absolute_url())

    def test_missing_token_is_refused(self):
        self.pay('')
        self.assertEqual(self.invoice.payments.count(), 0)

    def test_another_users_token_is_refused(self):
        other = get_user_model().objects.create_user('other', password='x')
        self.pay(issue_token(other))
        self.assertEqual(self.invoice.payments.count(), 0)

    def test_same_email_form_submitted_twice_sends_once(self):
        from django.core import mail
        token = issue_token(self.user)
        url = reverse('billing:invoice_email', args=[self.invoice.pk])
        for _ in range(3):
            self.client.post(url, {'to_email': 'jane@example.com', 'message': 'Hi', 'once_token': token})
        self.assertEqual(len(mail.outbox), 1)

    def test_forms_carry_a_token(self):
        for url in (reverse('billing:invoice_email', args=[self.invoice.pk]), self.invoice.get_absolute_url()):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'name="once_token"')


class LogPaginationTests(BaseDataMixin, TestCase):
    def make_logs(self, n, **extra):
        CommunicationLog.objects.bulk_create([
            CommunicationLog(customer=self.customer, message=f'note {i}', **extra) for i in range(n)
        ])

    def test_comms_list_pages_and_keeps_filters(self):
        self.make_logs(30, channel='call')
        response = self.client.get(reverse('comms:list'), {'channel': 'call'})
        self.assertEqual(len(response.context['object_list']), 25)
        self.assertContains(response, 'Showing 1–25 of 30')
        self.assertContains(response, '?channel=call&amp;page=2')
        response = self.client.get(reverse('comms:list'), {'channel': 'call', 'page': 2})
        self.assertEqual(len(response.context['object_list']), 5)

    def test_per_page_is_limited_to_allowed_sizes(self):
        self.make_logs(60)
        self.assertEqual(len(self.client.get(reverse('comms:list'), {'per_page': 50}).context['object_list']), 50)
        self.assertEqual(len(self.client.get(reverse('comms:list'), {'per_page': 100000}).context['object_list']), 25)
        self.assertEqual(len(self.client.get(reverse('comms:list'), {'per_page': 'x'}).context['object_list']), 25)

    def test_per_page_alone_is_not_a_filter(self):
        self.make_logs(3)
        self.assertNotContains(self.client.get(reverse('comms:list'), {'per_page': 50}), 'Filtered')

    def test_comms_search(self):
        self.make_logs(3)
        CommunicationLog.objects.create(customer=self.customer, message='asked about tents')
        response = self.client.get(reverse('comms:list'), {'q': 'tents'})
        self.assertEqual(len(response.context['object_list']), 1)

    def test_activity_log_pages_with_search(self):
        from .models import ActivityLog
        ActivityLog.objects.bulk_create([ActivityLog(action='x.created', description=f'Created thing {i}') for i in range(120)])
        response = self.client.get(reverse('activity_log'))
        self.assertEqual(len(response.context['entries']), 50)
        self.assertContains(response, 'Showing 1–50 of 120')
        response = self.client.get(reverse('activity_log'), {'page': 3})
        self.assertEqual(len(response.context['entries']), 20)
        response = self.client.get(reverse('activity_log'), {'q': 'thing 7'})
        self.assertEqual(response.context['page_obj'].paginator.count, 11)  # 7, 70-79

    def test_junk_page_number_falls_back(self):
        self.make_logs(3)
        self.assertEqual(self.client.get(reverse('comms:list'), {'page': 'abc'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('comms:list'), {'page': 999}).status_code, 200)

    def test_event_comms_card_pages_instead_of_truncating(self):
        self.make_logs(14, event=self.event)
        url = reverse('events:detail', args=[self.event.pk])
        self.assertEqual(len(self.client.get(url).context['comms_page']), 10)
        self.assertEqual(len(self.client.get(url, {'comms_page': 2}).context['comms_page']), 4)

    def test_customer_timeline_pages(self):
        self.make_logs(40)
        url = reverse('customers:detail', args=[self.customer.pk])
        response = self.client.get(url)
        self.assertEqual(len(response.context['timeline_page']), 15)
        self.assertContains(response, 'timeline_page=2')

    def test_admin_changelists_render(self):
        self.make_logs(3)
        for name in ('admin:comms_communicationlog_changelist', 'admin:core_activitylog_changelist'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class EmailFailureTests(BaseDataMixin, TestCase):
    def test_unreachable_mail_server_fails_fast_and_allows_retry(self):
        from unittest import mock
        from django.conf import settings
        self.assertLess(settings.EMAIL_TIMEOUT, 30)  # must beat gunicorn's worker timeout
        invoice = self.make_invoice()
        url = reverse('billing:invoice_email', args=[invoice.pk])
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=TimeoutError('timed out')), \
                self.assertLogs('core.emailing', level='ERROR'):
            response = self.client.post(url, {'to_email': 'jane@example.com', 'message': 'Hi',
                                              'once_token': issue_token(self.user)})
        self.assertContains(response, 'could not be reached')
        self.assertContains(response, 'name="once_token"')  # fresh token so a retry is accepted
        self.assertFalse(CommunicationLog.objects.exists())
