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

    def test_staff_with_event_assignment_is_blocked(self):
        assigned = StaffMember.objects.create(full_name='Assigned')
        EventAssignment.objects.create(event=self.event, staff_member=assigned)
        response = self.client.post(reverse('staffing:delete', args=[assigned.pk]))
        self.assertContains(response, '1 event assignment')
        self.assertTrue(StaffMember.objects.filter(pk=assigned.pk).exists())

    def test_unassigned_staff_without_login_is_deleted(self):
        free = StaffMember.objects.create(full_name='Free')
        self.assertRedirects(self.client.post(reverse('staffing:delete', args=[free.pk])), reverse('staffing:list'))
        self.assertFalse(StaffMember.objects.filter(pk=free.pk).exists())

    def test_unused_login_is_deleted_with_staff(self):
        user = get_user_model().objects.create_user('never', email='never@example.com', password='x')
        staff = StaffMember.objects.create(full_name='Never Logged In', user=user)
        page = self.client.get(reverse('staffing:delete', args=[staff.pk]))
        self.assertContains(page, 'never used')
        self.client.post(reverse('staffing:delete', args=[staff.pk]))
        self.assertFalse(StaffMember.objects.filter(pk=staff.pk).exists())
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())

    def test_used_login_is_switched_off_and_kept_for_audit(self):
        from .models import ActivityLog
        user = get_user_model().objects.create_user('worked', email='worked@example.com', password='Pass-1234x')
        ActivityLog.objects.create(actor=user, action='customer.created', description='Created customer "X"')
        staff = StaffMember.objects.create(full_name='Has History', user=user)
        page = self.client.get(reverse('staffing:delete', args=[staff.pk]))
        self.assertContains(page, 'switched off')
        self.client.post(reverse('staffing:delete', args=[staff.pk]))
        self.assertFalse(StaffMember.objects.filter(pk=staff.pk).exists())
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(ActivityLog.objects.filter(actor=user).count(), 1)  # history still attributed
        self.client.logout()
        self.assertEqual(self.client.post(reverse('login'), {'username': 'worked@example.com', 'password': 'Pass-1234x'}).status_code, 200)

    def test_cannot_delete_yourself_or_a_superuser(self):
        me = StaffMember.objects.create(full_name='Me', user=self.user)
        boss = get_user_model().objects.create_superuser('boss2', 'boss2@example.com', 'x')
        other_admin = StaffMember.objects.create(full_name='Other Admin', user=boss)
        for staff, reason in ((me, 'delete yourself'), (other_admin, 'superuser login')):
            with self.subTest(staff=staff.full_name):
                self.assertContains(self.client.post(reverse('staffing:delete', args=[staff.pk])), reason)
                self.assertTrue(StaffMember.objects.filter(pk=staff.pk).exists())

    def test_only_superuser_can_remove_staff_with_login(self):
        from django.contrib.auth.models import Permission
        office = get_user_model().objects.create_user('office', email='office@example.com', password='x')
        office.user_permissions.add(*Permission.objects.filter(codename__in=['delete_staffmember', 'view_staffmember']))
        target_user = get_user_model().objects.create_user('t', email='t@example.com', password='x')
        target = StaffMember.objects.create(full_name='Target', user=target_user)
        no_login = StaffMember.objects.create(full_name='No Login')
        self.client.force_login(office)
        self.assertContains(self.client.post(reverse('staffing:delete', args=[target.pk])), 'only an administrator')
        self.assertTrue(StaffMember.objects.filter(pk=target.pk).exists())
        self.client.post(reverse('staffing:delete', args=[no_login.pk]))
        self.assertFalse(StaffMember.objects.filter(pk=no_login.pk).exists())

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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ENABLED=True)
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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_ENABLED=True)
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


@override_settings(EMAIL_ENABLED=True)
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


@override_settings(
    EMAIL_BACKEND='anymail.backends.brevo.EmailBackend',
    ANYMAIL={'BREVO_API_KEY': 'test-key', 'REQUESTS_TIMEOUT': 15},
    DEFAULT_FROM_EMAIL='Pretty Events <info@prettyeventslimited.co.ug>',
    EMAIL_ENABLED=True,
)
class BrevoEmailTests(BaseDataMixin, TestCase):
    """Production sends through Brevo's HTTPS API (Railway blocks SMTP). No real network here."""

    def fake_response(self, status=201, body=b'{"messageId": "<abc@smtp-relay.brevo.com>"}'):
        from unittest import mock
        response = mock.Mock(status_code=status, content=body, text=body.decode(), headers={})
        response.json.return_value = __import__('json').loads(body)
        return response

    def send_invoice(self):
        invoice = self.make_invoice('300000')
        url = reverse('billing:invoice_email', args=[invoice.pk])
        return invoice, self.client.post(url, {'to_email': 'jane@example.com', 'message': 'Hi Jane',
                                               'once_token': issue_token(self.user)})

    def call_parts(self, request):
        call = request.call_args
        args, kwargs = call.args, call.kwargs
        method = kwargs.get('method', args[0] if args else '')
        url = kwargs.get('url', args[1] if len(args) > 1 else '')
        return method.upper(), url, __import__('json').loads(kwargs['data']), kwargs['headers']

    def test_invoice_goes_to_brevo_api(self):
        from unittest import mock
        with mock.patch('requests.Session.request', return_value=self.fake_response()) as request:
            invoice, response = self.send_invoice()
        self.assertRedirects(response, reverse('billing:invoice_detail', args=[invoice.pk]))
        method, url, payload, headers = self.call_parts(request)
        self.assertEqual((method, url), ('POST', 'https://api.brevo.com/v3/smtp/email'))
        self.assertEqual(payload['to'], [{'email': 'jane@example.com'}])
        self.assertEqual(payload['sender']['email'], 'info@prettyeventslimited.co.ug')
        self.assertEqual(headers['api-key'], 'test-key')
        self.assertTrue(CommunicationLog.objects.filter(channel='email').exists())

    def test_pdf_attachment_is_included(self):
        from unittest import mock
        from core.emailing import send_pdf_email
        with mock.patch('requests.Session.request', return_value=self.fake_response()) as request:
            self.assertTrue(send_pdf_email(to_email='jane@example.com', subject='Invoice', body='Hi',
                                           pdf_bytes=b'%PDF-1.4 test', filename='INV-1.pdf'))
        payload = self.call_parts(request)[2]
        self.assertEqual(payload['attachment'][0]['name'], 'INV-1.pdf')

    def test_brevo_rejection_shows_friendly_error(self):
        from unittest import mock
        rejected = self.fake_response(400, b'{"code": "invalid_parameter", "message": "sender not valid"}')
        with mock.patch('requests.Session.request', return_value=rejected), \
                self.assertLogs('core.emailing', level='ERROR'):
            _, response = self.send_invoice()
        self.assertContains(response, 'could not be reached')
        self.assertFalse(CommunicationLog.objects.exists())

    def test_brevo_timeout_shows_friendly_error(self):
        import requests
        from unittest import mock
        with mock.patch('requests.Session.request', side_effect=requests.Timeout('slow')), \
                self.assertLogs('core.emailing', level='ERROR'):
            _, response = self.send_invoice()
        self.assertContains(response, 'could not be reached')

    def test_setting_api_key_switches_backend(self):
        import os, subprocess, sys
        code = 'import django; django.setup(); from django.conf import settings; print(settings.EMAIL_BACKEND)'
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings.dev', 'BREVO_API_KEY': 'k'}
        out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, 'anymail.backends.brevo.EmailBackend')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailSwitchedOffTests(BaseDataMixin, TestCase):
    """EMAIL_ENABLED defaults to off: nothing offers to send email, and nothing sends it."""

    def setUp(self):
        super().setUp()
        from django.conf import settings
        self.assertFalse(settings.EMAIL_ENABLED)
        self.invoice = self.make_invoice('300000')
        self.receipt = Payment.objects.create(invoice=self.invoice, amount=Decimal('1000')).receipt

    def test_email_buttons_hidden(self):
        for url, email_url in (
            (self.invoice.get_absolute_url(), reverse('billing:invoice_email', args=[self.invoice.pk])),
            (reverse('billing:receipt_detail', args=[self.receipt.pk]), reverse('billing:receipt_email', args=[self.receipt.pk])),
            (reverse('billing:receipt_list'), reverse('billing:receipt_email', args=[self.receipt.pk])),
        ):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertNotContains(page, email_url)
                self.assertNotContains(page, 'Email to Client')

    def test_mail_app_button_shown_instead(self):
        page = self.client.get(self.invoice.get_absolute_url())
        self.assertContains(page, reverse('comms:contact', args=[self.customer.pk, 'email']))

    def test_direct_url_redirects_and_sends_nothing(self):
        from django.core import mail
        url = reverse('billing:invoice_email', args=[self.invoice.pk])
        response = self.client.post(url, {'to_email': 'jane@example.com', 'message': 'Hi',
                                          'once_token': issue_token(self.user)}, HTTP_REFERER='http://testserver' + self.invoice.get_absolute_url())
        self.assertRedirects(response, 'http://testserver' + self.invoice.get_absolute_url())  # back where they came from
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(CommunicationLog.objects.exists())

    def test_forgot_password_hidden_and_blocked(self):
        from django.core import mail
        self.client.logout()
        login = self.client.get(reverse('login'))
        self.assertNotContains(login, reverse('password_reset'))
        self.assertContains(login, 'Ask your administrator')
        response = self.client.post(reverse('password_reset'), {'email': self.user.email})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_new_staff_login_requires_admin_set_password(self):
        from django.core import mail
        data = {'full_name': 'New Person', 'phone': '', 'title': '', 'is_active': 'on', 'create_login': '1',
                'login-email': 'new.person@example.com'}
        response = self.client.post(reverse('staffing:create'), data)
        self.assertEqual(response.status_code, 200)  # form re-shown: password required
        self.assertFalse(get_user_model().objects.filter(email='new.person@example.com').exists())
        data.update({'login-password1': 'Temp-Pass-4567', 'login-password2': 'Temp-Pass-4567'})
        self.client.post(reverse('staffing:create'), data)
        user = get_user_model().objects.get(email='new.person@example.com')
        self.assertTrue(user.check_password('Temp-Pass-4567'))
        self.assertEqual(len(mail.outbox), 0)
        page = self.client.get(reverse('staffing:detail', args=[user.staff_profile.pk]))
        self.assertNotContains(page, reverse('user_send_reset', args=[user.pk]))



class DocumentPdfTests(BaseDataMixin, TestCase):
    """The PDF templates render for every document, including edge cases in old data."""

    def test_all_documents_render(self):
        from billing.models import Quotation, QuotationLineItem
        from billing.views import generate_pdf_bytes, receipt_pdf_context
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        quotation = Quotation.objects.create(event=self.event)
        QuotationLineItem.objects.create(quotation=quotation, description='Pagoda tent (10m x 10m)', quantity=Decimal('1.00'), unit_price=Decimal('600000'))
        invoice = self.make_invoice('600000')
        with_user = Payment.objects.create(invoice=invoice, amount=Decimal('100000'), received_by=self.user)
        without_user = Payment.objects.create(invoice=invoice, amount=Decimal('50000'))  # e.g. entered via admin
        request = RequestFactory().get('/')
        request.user = self.user
        quote_html = render_to_string('pdf/quotation_pdf.html', {'quotation': quotation}, request=request)
        self.assertIn('QUOTATION', quote_html.upper())
        self.assertIn('600,000', quote_html)
        self.assertIn('CLIENT DETAILS', quote_html.upper())
        invoice.created_by = self.user
        invoice.save()
        StaffMember.objects.create(full_name='Rukiah', user=self.user)
        self.user.refresh_from_db()
        invoice_html = render_to_string('pdf/invoice_pdf.html', {'invoice': invoice}, request=request)
        self.assertIn('Balance due', invoice_html)
        self.assertIn('Prepared by: <b>Rukiah</b>', invoice_html)  # staff name, not the login's username
        for name, phone in (('James', '0772 682 448'), ('Rukiah', '0704 316 745'), ('Office line', '0393 254 159')):
            self.assertIn(f'<span class="contact-name">{name}</span> - {phone}', invoice_html)
        self.assertIn('450,000', invoice_html)
        for payment in (with_user, without_user):
            with self.subTest(received_by=payment.received_by):
                html = render_to_string('pdf/receipt_pdf.html', receipt_pdf_context(payment.receipt), request=request)
                self.assertIn(payment.receipt.number, html)
                if payment.received_by:
                    self.assertIn('Received by: <b>Rukiah</b>', html)
        # Real PDFs where WeasyPrint's native libraries are available (always in the Docker image).
        pdf = generate_pdf_bytes(request, 'pdf/invoice_pdf.html', {'invoice': invoice})
        if pdf is not None:
            self.assertTrue(pdf.startswith(b'%PDF'))

    def test_pdf_views_respond(self):
        invoice = self.make_invoice()
        payment = Payment.objects.create(invoice=invoice, amount=Decimal('1000'))
        for url in (reverse('billing:invoice_pdf', args=[invoice.pk]), reverse('billing:receipt_pdf', args=[payment.receipt.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class ConvertedQuotationFlowTests(BaseDataMixin, TestCase):
    """Once a quotation becomes an invoice, the invoice is the working document."""

    def setUp(self):
        super().setUp()
        from billing.models import Quotation, QuotationLineItem
        self.quotation = Quotation.objects.create(event=self.event)
        QuotationLineItem.objects.create(quotation=self.quotation, description='Tent', quantity=1, unit_price=Decimal('500000'))

    def convert(self):
        self.client.get(reverse('billing:quotation_convert', args=[self.quotation.pk]))
        self.quotation.refresh_from_db()
        return self.quotation.invoice

    def formset_post(self, url, rows, **fields):
        data = {'line_items-TOTAL_FORMS': str(len(rows)), 'line_items-INITIAL_FORMS': str(sum(1 for r in rows if r.get('id'))),
                'line_items-MIN_NUM_FORMS': '1', 'line_items-MAX_NUM_FORMS': '1000', **fields}
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f'line_items-{i}-{key}'] = value
        return self.client.post(url, data)

    def test_quotation_editable_before_conversion(self):
        self.assertEqual(self.client.get(reverse('billing:quotation_update', args=[self.quotation.pk])).status_code, 200)

    def test_converted_quotation_is_locked(self):
        invoice = self.convert()
        response = self.client.get(reverse('billing:quotation_update', args=[self.quotation.pk]))
        self.assertRedirects(response, reverse('billing:quotation_detail', args=[self.quotation.pk]))
        line = self.quotation.line_items.get()
        self.formset_post(reverse('billing:quotation_update', args=[self.quotation.pk]),
                          [{'id': line.pk, 'description': 'Tent', 'quantity': '5', 'unit_price': '500000'}],
                          status='approved', valid_until='', notes='')
        line.refresh_from_db()
        self.assertEqual(line.quantity, 1)  # POST can't sneak an edit through either
        page = self.client.get(reverse('billing:quotation_detail', args=[self.quotation.pk]))
        self.assertContains(page, f'Converted to invoice')
        self.assertContains(page, reverse('billing:invoice_update', args=[invoice.pk]))
        self.assertNotContains(page, reverse('billing:quotation_update', args=[self.quotation.pk]))

    def test_invoice_edit_is_the_way_to_change_items(self):
        invoice = self.convert()
        line = invoice.line_items.get()
        self.formset_post(reverse('billing:invoice_update', args=[invoice.pk]),
                          [{'id': line.pk, 'description': 'Tent', 'quantity': '2', 'unit_price': '500000'}],
                          status='unpaid', issue_date=timezone.localdate().isoformat(), due_date='', notes='')
        self.assertEqual(Invoice.objects.get(pk=invoice.pk).total, Decimal('1000000'))
        self.assertEqual(self.quotation.total, Decimal('500000'))  # original offer kept as sent

    def test_invoice_total_cannot_drop_below_amount_paid(self):
        invoice = self.convert()
        Payment.objects.create(invoice=invoice, amount=Decimal('400000'))
        line = invoice.line_items.get()
        response = self.formset_post(reverse('billing:invoice_update', args=[invoice.pk]),
                                     [{'id': line.pk, 'description': 'Tent', 'quantity': '1', 'unit_price': '300000'}],
                                     status='partially_paid', issue_date=timezone.localdate().isoformat(), due_date='', notes='')
        self.assertContains(response, 'less than the 400,000 already paid')
        self.assertEqual(Invoice.objects.get(pk=invoice.pk).total, Decimal('500000'))
        # Equal to the amount paid is fine.
        self.formset_post(reverse('billing:invoice_update', args=[invoice.pk]),
                          [{'id': line.pk, 'description': 'Tent', 'quantity': '1', 'unit_price': '400000'}],
                          status='partially_paid', issue_date=timezone.localdate().isoformat(), due_date='', notes='')
        invoice = Invoice.objects.get(pk=invoice.pk)
        self.assertEqual(invoice.total, Decimal('400000'))
        self.assertEqual(invoice.status, Invoice.Status.PAID)


class OverdueInvoiceTests(BaseDataMixin, TestCase):
    def test_past_due_unpaid_invoice_becomes_overdue(self):
        from billing.services import sync_invoice_statuses
        invoice = self.make_invoice()
        invoice.due_date = timezone.localdate() - timedelta(days=1)
        invoice.save()
        self.assertEqual(sync_invoice_statuses(), 1)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.OVERDUE)

    def test_paying_in_full_clears_overdue(self):
        invoice = self.make_invoice('50000')
        invoice.due_date = timezone.localdate() - timedelta(days=1)
        invoice.save()
        invoice.refresh_status()
        self.assertEqual(invoice.status, Invoice.Status.OVERDUE)
        Payment.objects.create(invoice=invoice, amount=Decimal('50000'))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_moving_due_date_forward_clears_overdue(self):
        invoice = self.make_invoice()
        invoice.due_date = timezone.localdate() - timedelta(days=1)
        invoice.save()
        invoice.refresh_status()
        invoice.due_date = timezone.localdate() + timedelta(days=7)
        invoice.save()
        invoice.refresh_status()
        self.assertEqual(invoice.status, Invoice.Status.UNPAID)

    def test_invoice_list_shows_overdue(self):
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(due_date=timezone.localdate() - timedelta(days=3))
        response = self.client.get(reverse('billing:invoice_list'), {'status': 'overdue'})
        self.assertContains(response, invoice.number)


class AvailabilityQueryTests(BaseDataMixin, TestCase):
    def test_annotated_availability_matches_property(self):
        today = timezone.localdate()
        item = EquipmentItem.objects.create(name='Chair', total_quantity=8)
        issue = EquipmentIssue.objects.create(event=self.event, equipment_item=item, quantity_issued=7, issued_at=today)
        EquipmentReturn.objects.create(issue=issue, quantity_returned=3, returned_at=today)
        EquipmentItem.objects.create(name='Tent', total_quantity=20)

        annotated = EquipmentItem.objects.with_availability().get(pk=item.pk)
        plain = EquipmentItem.objects.get(pk=item.pk)
        self.assertEqual(annotated.available_quantity, 4)
        self.assertEqual(plain.available_quantity, 4)
        self.assertEqual([i.name for i in EquipmentItem.objects.low_stock()], ['Chair'])

    def test_dashboard_query_count_does_not_grow_with_items(self):
        today = timezone.localdate()
        for n in range(3):
            item = EquipmentItem.objects.create(name=f'Item {n}', total_quantity=2)
            EquipmentIssue.objects.create(event=self.event, equipment_item=item, quantity_issued=1, issued_at=today)
        self.client.get(reverse('dashboard'))  # warm up session/permission caches
        with self.assertNumQueries(self._dashboard_queries()):
            for n in range(3, 8):
                item = EquipmentItem.objects.create(name=f'Item {n}', total_quantity=2)
            self.client.get(reverse('dashboard'))

    def _dashboard_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('dashboard'))
        return len(ctx.captured_queries) + 5  # + the 5 creates inside the block


class SearchTests(BaseDataMixin, TestCase):
    def test_finds_customer_by_phone_in_any_format(self):
        Customer.objects.create(name='Other Person', phone='0700 000 001')
        for query in ['0772123456', '+256 772 123456', '772-123']:
            response = self.client.get(reverse('search'), {'q': query})
            self.assertRedirects(response, self.customer.get_absolute_url(), msg_prefix=query)

    def test_document_number_jumps_straight_to_it(self):
        invoice = self.make_invoice()
        response = self.client.get(reverse('search'), {'q': invoice.number})
        self.assertRedirects(response, invoice.get_absolute_url())

    def test_lists_several_kinds_of_match(self):
        self.make_invoice()
        response = self.client.get(reverse('search'), {'q': 'Jane'})
        self.assertEqual(response.status_code, 200)
        titles = [s['title'] for s in response.context['sections']]
        self.assertEqual(titles, ['Customers', 'Events', 'Invoices'])

    def test_field_staff_only_find_their_own_events(self):
        from django.contrib.auth.models import Group, Permission
        user = get_user_model().objects.create_user('field', 'field@example.com', 'pw')
        group = Group.objects.create(name='Field')
        group.permissions.set(Permission.objects.filter(codename__in=['view_event', 'view_assigned_events_only']))
        user.groups.add(group)
        self.client.force_login(user)
        response = self.client.get(reverse('search'), {'q': 'Wedding'})
        self.assertEqual(response.context['sections'], [])


class EventProgressTests(BaseDataMixin, TestCase):
    def test_checklist_ticks_follow_the_records(self):
        invoice = self.make_invoice('100000')
        Payment.objects.create(invoice=invoice, amount=Decimal('40000'))
        response = self.client.get(reverse('events:detail', args=[self.event.pk]))
        steps = {s['label']: s for s in response.context['progress']}
        self.assertTrue(steps['Quoted']['done'])
        self.assertTrue(steps['Deposit']['done'])
        self.assertFalse(steps['Paid in full']['done'])
        self.assertIn('60,000', steps['Paid in full']['detail'])
        self.assertFalse(steps['Equipment back']['done'])

    def test_packing_list_renders_booked_items(self):
        item = EquipmentItem.objects.create(name='Chiavari chair', total_quantity=100)
        invoice = self.make_invoice()
        InvoiceLineItem.objects.create(invoice=invoice, equipment_item=item, description='Chairs', quantity=80, unit_price=Decimal('1000'))
        from unittest import mock
        # Render the HTML fallback instead of a PDF so the content can be checked.
        with mock.patch('billing.views.generate_pdf_bytes', return_value=None):
            response = self.client.get(reverse('events:packing_list', args=[self.event.pk]))
        self.assertContains(response, 'Packing list')
        self.assertContains(response, 'Chiavari chair')
        self.assertContains(response, '80 pieces')


class DashboardRoleTests(BaseDataMixin, TestCase):
    def test_staff_see_their_own_upcoming_jobs(self):
        self.event.event_date = timezone.localdate() + timedelta(days=3)
        self.event.save()
        later = Event.objects.create(customer=self.customer, event_type='Far off', venue='X',
                                     event_date=timezone.localdate() + timedelta(days=40))
        staff = StaffMember.objects.create(full_name='Field Worker', user=self.user)
        EventAssignment.objects.create(event=self.event, staff_member=staff, role_on_event='Driver')
        EventAssignment.objects.create(event=later, staff_member=staff)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual([a.event for a in response.context['my_assignments']], [self.event])
        self.assertContains(response, 'My jobs')

    def test_overdue_shortcut(self):
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '1 overdue invoice')


class ShareLinkTests(BaseDataMixin, TestCase):
    def test_whatsapp_message_carries_a_working_pdf_link(self):
        from unittest import mock
        from urllib.parse import unquote
        invoice = self.make_invoice()
        response = self.client.post(
            reverse('comms:contact', args=[self.customer.pk, 'whatsapp']), {'document': f'invoice:{invoice.pk}'},
        )
        target = unquote(response['Location'])
        self.assertIn('/billing/shared/', target)
        path = '/billing/shared/' + target.split('/billing/shared/')[1].split()[0]

        self.client.logout()
        with mock.patch('billing.views.generate_pdf_bytes', return_value=None):
            response = self.client.get(path)
        self.assertContains(response, invoice.number)

    def test_tampered_or_expired_links_are_refused(self):
        from billing.sharing import share_token
        invoice = self.make_invoice()
        token = share_token(invoice)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('billing:shared_document', args=[token[:-2] + 'xx'])).status_code, 404)
        with override_settings(SHARE_LINK_DAYS=-1):
            self.assertEqual(self.client.get(reverse('billing:shared_document', args=[token])).status_code, 404)


@override_settings(EMAIL_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DocumentEmailTaskTests(BaseDataMixin, TestCase):
    def post_email(self, invoice):
        from .once import FIELD_NAME
        token = issue_token(self.user)
        return self.client.post(reverse('billing:invoice_email', args=[invoice.pk]), {
            'to_email': 'client@example.com', 'message': 'Here it is', FIELD_NAME: token,
        }, follow=True)

    def test_sends_immediately_by_default_and_logs_it(self):
        from django.core import mail
        invoice = self.make_invoice()
        response = self.post_email(invoice)
        self.assertContains(response, f'Invoice {invoice.number} emailed to client@example.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, f'Invoice {invoice.number} from PRETTY EVENTS LTD.')
        self.assertTrue(CommunicationLog.objects.filter(message__contains=invoice.number).exists())

    def test_with_a_worker_the_email_is_queued_then_sent_by_it(self):
        from django.core import mail
        from django.core.management import call_command
        invoice = self.make_invoice()
        with override_settings(TASKS={'default': {'BACKEND': 'django_tasks_db.DatabaseBackend'}}):
            response = self.post_email(invoice)
            self.assertContains(response, 'is being emailed to client@example.com')
            self.assertEqual(len(mail.outbox), 0)
            call_command('db_worker', '--batch', '--no-startup-delay', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(CommunicationLog.objects.filter(message__contains=invoice.number).exists())

    def test_failure_is_reported_and_recorded(self):
        from unittest import mock
        from .models import ActivityLog
        invoice = self.make_invoice()
        with mock.patch('billing.tasks.send_pdf_email', return_value=False):
            response = self.post_email(invoice)
        self.assertContains(response, 'Could not send the email')
        self.assertTrue(ActivityLog.objects.filter(action='invoice.email_failed').exists())


class DocumentNumberTests(BaseDataMixin, TestCase):
    def test_numbers_run_in_order_per_type(self):
        year = timezone.localdate().year
        first, second = self.make_invoice(), self.make_invoice()
        quote = Quotation.objects.create(event=self.event)
        self.assertEqual(first.number, f'INV-{year}-00001')
        self.assertEqual(second.number, f'INV-{year}-00002')
        self.assertEqual(quote.number, f'QUO-{year}-00001')

    def test_numbering_restarts_each_year(self):
        from datetime import date
        from unittest import mock
        self.make_invoice()
        with mock.patch('billing.models.timezone.localdate', return_value=date(2099, 1, 1)):
            self.assertEqual(self.make_invoice().number, 'INV-2099-00001')

    def test_continues_after_numbers_from_the_old_scheme(self):
        year = timezone.localdate().year
        Invoice.objects.create(event=self.event, number=f'INV-{year}-00042')
        self.assertEqual(self.make_invoice().number, f'INV-{year}-00043')

    def test_a_failed_save_does_not_use_up_a_number(self):
        from django.db import transaction
        year = timezone.localdate().year
        try:
            with transaction.atomic():
                self.make_invoice()
                raise RuntimeError('save failed after numbering')
        except RuntimeError:
            pass
        self.assertEqual(self.make_invoice().number, f'INV-{year}-00001')


class ResetBusinessDataTests(BaseDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from datetime import date
        from django.core.management import call_command
        from accounting.models import Account, JournalEntry, PeriodClose
        from accounting.services import reverse_entry, save_entry
        from billing.models import MobileMoneyTransaction
        from billing.services import record_payment
        from finance.models import ExpenseCategory, ExpenseRecord
        call_command('setup_chart_of_accounts', verbosity=0)

        self.item = EquipmentItem.objects.create(name='Tent', total_quantity=5)
        quote = Quotation.objects.create(event=self.event)
        QuotationLineItem.objects.create(quotation=quote, equipment_item=self.item, description='Tent', quantity=2, unit_price=Decimal('1000'))
        invoice = Invoice.create_from_quotation(quote)
        record_payment(invoice, amount=Decimal('1000'), method='cash')
        self.category = ExpenseCategory.objects.create(name='Transport')
        ExpenseRecord.objects.create(amount=Decimal('500'), category=self.category, date=timezone.localdate())
        issue = EquipmentIssue.objects.create(event=self.event, equipment_item=self.item, quantity_issued=2, issued_at=timezone.localdate())
        EquipmentReturn.objects.create(issue=issue, quantity_returned=1, returned_at=timezone.localdate())
        self.staff = StaffMember.objects.create(full_name='Crew Member')
        EventAssignment.objects.create(event=self.event, staff_member=self.staff)
        CommunicationLog.objects.create(customer=self.customer, channel='call', direction='outbound', message='hi')
        cash = Account.objects.get(system_key='cash')
        other = Account.objects.filter(account_type='equity').first()
        old = save_entry(JournalEntry(date=date(2026, 1, 5)), [{'account': cash, 'debit': 10}, {'account': other, 'credit': 10}])
        reverse_entry(old, date=date(2026, 1, 6), user=self.user)
        PeriodClose.objects.create(closed_through=date(2026, 1, 31))
        MobileMoneyTransaction.objects.create(provider='generic', transaction_id='T1', amount=Decimal('5'))

    def run_reset(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('reset_business_data', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self.run_reset()
        self.assertIn('Nothing was deleted', output)
        self.assertTrue(Customer.objects.exists())
        self.assertTrue(Invoice.objects.exists())

    def test_clears_business_data_keeps_setup_and_restarts_numbers(self):
        from accounting.models import Account, JournalEntry, PeriodClose
        from billing.models import MobileMoneyTransaction
        from finance.models import ExpenseCategory, ExpenseRecord, IncomeRecord
        from .models import ActivityLog
        accounts_before = Account.objects.count()

        self.run_reset('--confirm')

        for model in (Customer, Event, Quotation, Invoice, Payment, IncomeRecord, ExpenseRecord, JournalEntry,
                      PeriodClose, EquipmentIssue, EquipmentReturn, EventAssignment, CommunicationLog,
                      MobileMoneyTransaction):
            self.assertFalse(model.objects.exists(), model.__name__)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertEqual(Account.objects.count(), accounts_before)
        self.assertTrue(ExpenseCategory.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(EquipmentItem.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(StaffMember.objects.filter(pk=self.staff.pk).exists())
        self.assertEqual(list(ActivityLog.objects.values_list('action', flat=True)), ['system.reset'])

        # Fresh numbering for documents and journals.
        year = timezone.localdate().year
        customer = Customer.objects.create(name='Real Client', phone='0700000000')
        event = Event.objects.create(customer=customer, event_type='Wedding', venue='X', event_date=timezone.localdate())
        invoice = Invoice.objects.create(event=event)
        self.assertEqual(invoice.number, f'INV-{year}-00001')
        self.assertEqual(Quotation.objects.create(event=event).number, f'QUO-{year}-00001')
        from accounting.services import save_entry
        cash = Account.objects.get(system_key='cash')
        entry = save_entry(JournalEntry(date=timezone.localdate()), [
            {'account': cash, 'debit': 1}, {'account': Account.objects.filter(account_type='equity').first(), 'credit': 1},
        ])
        self.assertEqual(entry.number, f'JE-{year}-00001')

    def test_optional_equipment_and_staff(self):
        self.run_reset('--confirm', '--include-equipment', '--include-staff')
        self.assertFalse(EquipmentItem.objects.exists())
        self.assertFalse(StaffMember.objects.exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())


class NavigationTests(BaseDataMixin, TestCase):
    def nav(self, user, path='/'):
        self.client.force_login(user)
        return self.client.get(path).context

    def role_user(self, codenames, email='role@example.com'):
        from django.contrib.auth.models import Permission
        user = get_user_model().objects.create_user(email.split('@')[0], email, 'pw')
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        return user

    def test_owner_sees_eight_flat_items(self):
        labels = [i['label'] for i in self.nav(self.user)['nav_items']]
        self.assertEqual(labels, ['Dashboard', 'Events', 'Customers', 'Billing', 'Inventory', 'Staff', 'Finance', 'Reports',
                                  'Administration'])

    def test_field_staff_see_only_what_they_use(self):
        user = self.role_user(['view_event', 'view_assigned_events_only', 'view_eventassignment'])
        ctx = self.nav(user)
        self.assertEqual([i['label'] for i in ctx['nav_items']], ['Dashboard', 'Events'])
        # And the event report itself only counts their own events.
        Event.objects.create(customer=self.customer, event_type='Not mine', venue='X', event_date=timezone.localdate())
        response = self.client.get(reverse('reports:event_summary'))
        self.assertEqual(response.context['total'], 0)
        self.assertEqual(ctx['nav_new'], [])

    def test_accountant_lands_on_money_sections(self):
        user = self.role_user(['view_account', 'view_journalentry', 'view_incomerecord', 'view_expenserecord',
                               'view_invoice', 'view_payment', 'view_periodclose'])
        labels = [i['label'] for i in self.nav(user)['nav_items']]
        self.assertEqual(labels, ['Dashboard', 'Billing', 'Finance', 'Reports'])

    def test_tabs_show_on_section_pages_with_the_right_one_active(self):
        ctx = self.nav(self.user, reverse('billing:quotation_list'))
        self.assertEqual([(t['label'], t['active']) for t in ctx['nav_tabs']],
                         [('Invoices', False), ('Quotations', True), ('Receipts', False), ('Mobile money', False)])
        self.assertEqual([i['key'] for i in ctx['nav_items'] if i['active']], ['billing'])
        # Journals live under Finance now; financial statements under Reports.
        self.assertEqual(self.nav(self.user, reverse('accounting:journal_list'))['nav_section'], 'finance')
        self.assertEqual(self.nav(self.user, reverse('accounting:balance_sheet'))['nav_section'], 'reports')
        # Detail pages keep breadcrumbs, not the tab row.
        self.assertEqual(self.nav(self.user, reverse('events:detail', args=[self.event.pk]))['nav_tabs'], [])

    def test_badges_flag_overdue_invoices_and_low_stock(self):
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.OVERDUE)
        EquipmentItem.objects.create(name='Chair', total_quantity=2)
        badges = {i['key']: i['badge'] for i in self.nav(self.user)['nav_items'] if i['badge']}
        self.assertEqual(badges, {'billing': 1, 'inventory': 1})

    def test_administration_section_with_tabs_for_owners_only(self):
        ctx = self.nav(self.user, reverse('activity_log'))
        self.assertEqual(ctx['nav_section'], 'admin')
        self.assertEqual([(t['label'], t['active']) for t in ctx['nav_tabs']],
                         [('Roles & permissions', False), ('Activity log', True)])
        self.assertEqual(self.nav(self.user, reverse('role_create'))['nav_section'], 'admin')
        staff = self.role_user(['view_event', 'view_customer'], email='plain@example.com')
        self.assertNotIn('Administration', [i['label'] for i in self.nav(staff)['nav_items']])


class ThemeAndLoginPageTests(TestCase):
    def test_login_page_has_no_theme_switch(self):
        response = self.client.get(reverse('login'))
        self.assertNotContains(response, 'data-theme-choice="')  # the Auto/Light/Dark buttons
        self.assertContains(response, 'prefers-color-scheme')  # follows the device instead
        self.assertContains(response, 'password-toggle')        # show/hide button script

    def test_signed_in_users_can_pick_auto_light_or_dark(self):
        user = get_user_model().objects.create_user('u', 'u@example.com', 'pw')
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))
        for choice in ('auto', 'light', 'dark'):
            self.assertContains(response, f'data-theme-choice="{choice}"')


class SetupGroupsTests(TestCase):
    def run_setup(self, *args):
        from io import StringIO
        from django.core.management import call_command
        call_command('setup_groups', *args, stdout=StringIO())

    def test_client_changes_survive_the_next_deploy(self):
        from django.contrib.auth.models import Group, Permission
        self.run_setup()
        office = Group.objects.get(name='Office Staff')
        removed = Permission.objects.get(codename='delete_customer')
        extra = Permission.objects.get(codename='add_expenserecord')
        office.permissions.remove(removed)
        office.permissions.add(extra)
        Group.objects.get(name='Field Staff').delete()

        self.run_setup()  # what every deploy does
        office.refresh_from_db()
        self.assertNotIn(removed, office.permissions.all())
        self.assertIn(extra, office.permissions.all())
        self.assertFalse(Group.objects.filter(name='Field Staff').exists())

    def test_defaults_for_new_features_still_arrive_once(self):
        from django.contrib.auth.models import Group, Permission
        from .models import RoleDefault
        self.run_setup()
        perm = Permission.objects.get(codename='view_periodclose')
        accountant = Group.objects.get(name='Accountant')
        # Pretend this permission is new: never applied before.
        accountant.permissions.remove(perm)
        RoleDefault.objects.filter(group_name='Accountant', permission='accounting.view_periodclose').delete()
        self.run_setup()
        self.assertIn(perm, accountant.permissions.all())

    def test_reset_restores_the_starters(self):
        from django.contrib.auth.models import Group, Permission
        self.run_setup()
        Group.objects.get(name='Field Staff').delete()
        office = Group.objects.get(name='Office Staff')
        office.permissions.remove(Permission.objects.get(codename='delete_customer'))
        self.run_setup('--reset')
        self.assertTrue(Group.objects.filter(name='Field Staff').exists())
        self.assertTrue(office.permissions.filter(codename='delete_customer').exists())


class DailyJobsTests(BaseDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from . import daily
        daily._last_checked = None

    def test_first_request_of_the_day_runs_jobs_once(self):
        from . import daily
        from .models import DailyJobRun
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(due_date=timezone.localdate() - timedelta(days=2))
        self.client.get(reverse('customers:list'))  # a page that doesn't sync on its own
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.OVERDUE)
        self.assertEqual(DailyJobRun.objects.count(), 1)
        daily._last_checked = None  # another worker process
        self.assertIsNone(daily.run_if_due())
        self.assertEqual(DailyJobRun.objects.count(), 1)

    def test_a_failing_job_never_breaks_the_page(self):
        from unittest import mock
        with mock.patch('core.daily.run_daily_jobs', side_effect=RuntimeError('boom')):
            response = self.client.get(reverse('customers:list'))
        self.assertEqual(response.status_code, 200)


class NotificationTests(BaseDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()

    def bell(self, user=None):
        from .notifications import collect
        return [n['text'] for n in collect(user or self.user)]

    def test_lists_what_needs_attention(self):
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.OVERDUE)
        item = EquipmentItem.objects.create(name='Tent', total_quantity=3)
        past = Event.objects.create(customer=self.customer, event_type='Party', venue='X',
                                    event_date=timezone.localdate() - timedelta(days=3), status=Event.Status.COMPLETED)
        EquipmentIssue.objects.create(event=past, equipment_item=item, quantity_issued=2, issued_at=past.event_date)
        texts = self.bell()
        self.assertIn('1 overdue invoice', texts)
        self.assertIn('Equipment not back from 1 finished event', texts)
        self.assertIn('1 item low on stock', texts)

    def test_double_booking_shows_up(self):
        item = EquipmentItem.objects.create(name='Round table', total_quantity=10)
        for _ in range(2):
            event = Event.objects.create(customer=self.customer, event_type='Wedding', venue='X',
                                         event_date=timezone.localdate() + timedelta(days=5), status=Event.Status.CONFIRMED)
            invoice = Invoice.objects.create(event=event)
            InvoiceLineItem.objects.create(invoice=invoice, equipment_item=item, description='t', quantity=8, unit_price=1)
        self.assertTrue(any(t.startswith('Double-booked: Round table') for t in self.bell()))

    def test_bell_respects_roles_and_renders(self):
        invoice = self.make_invoice()
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.OVERDUE)
        field = get_user_model().objects.create_user('f', 'f@example.com', 'pw')
        self.assertEqual(self.bell(field), [])
        self.assertContains(self.client.get('/'), '1 overdue invoice')


class PaymentReminderTests(BaseDataMixin, TestCase):
    def test_reminder_states_balance_and_links_the_invoice(self):
        from urllib.parse import unquote
        invoice = self.make_invoice('300000')
        Invoice.objects.filter(pk=invoice.pk).update(due_date=timezone.localdate() - timedelta(days=4), status=Invoice.Status.OVERDUE)
        page = self.client.get(reverse('billing:invoice_detail', args=[invoice.pk]))
        self.assertContains(page, 'Send payment reminder')
        response = self.client.post(reverse('comms:contact', args=[self.customer.pk, 'whatsapp']),
                                    {'document': f'invoice:{invoice.pk}', 'purpose': 'reminder'})
        text = unquote(response['Location'])
        self.assertIn('friendly reminder', text)
        self.assertIn('was due on', text)
        self.assertIn('UGX 300,000', text)
        self.assertIn('/billing/shared/', text)
        self.assertTrue(CommunicationLog.objects.filter(message__startswith='Sent a payment reminder').exists())

    def test_no_reminder_button_when_paid(self):
        invoice = self.make_invoice('1000')
        Payment.objects.create(invoice=invoice, amount=Decimal('1000'))
        self.assertNotContains(self.client.get(reverse('billing:invoice_detail', args=[invoice.pk])), 'Send payment reminder')
