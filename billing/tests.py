import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from events.models import Event
from finance.models import IncomeRecord

from .models import Invoice, InvoiceLineItem, MobileMoneyTransaction, Payment

SECRET = 'test-webhook-secret'


@override_settings(MOBILE_MONEY_WEBHOOK_SECRET=SECRET)
class MobileMoneyWebhookTests(TestCase):
    def setUp(self):
        customer = Customer.objects.create(name='Jane Doe', phone='0772123456')
        self.event = Event.objects.create(
            customer=customer, event_type='Wedding', venue='Kampala',
            event_date=timezone.localdate() + timedelta(days=10), status=Event.Status.QUOTED,
        )
        self.invoice = Invoice.objects.create(event=self.event)
        InvoiceLineItem.objects.create(invoice=self.invoice, description='Tent', quantity=1, unit_price=Decimal('300000'))

    def deliver(self, payload, secret=SECRET, provider='generic'):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse('billing:mobile_money_webhook', args=[provider]), body,
            content_type='application/json', headers={'X-Signature': signature},
        )

    def payload(self, **overrides):
        data = {'transaction_id': 'MP261006.1015.A12345', 'amount': 100000, 'currency': 'UGX',
                'phone': '256772123456', 'name': 'JANE DOE', 'reference': self.invoice.number.lower().replace('-', ' ')}
        data.update(overrides)
        return data

    def test_payment_naming_an_invoice_is_recorded_on_it(self):
        response = self.deliver(self.payload())
        self.assertEqual(response.json(), {'status': 'matched', 'duplicate': False})
        payment = Payment.objects.get()
        self.assertEqual((payment.invoice, payment.amount, payment.method), (self.invoice, Decimal('100000'), 'mobile_money'))
        self.assertTrue(hasattr(payment, 'receipt'))
        self.assertTrue(IncomeRecord.objects.filter(payment=payment).exists())  # -> ledger journal
        self.invoice.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PARTIALLY_PAID)
        self.assertEqual(self.event.status, Event.Status.CONFIRMED)

    def test_repeat_delivery_does_not_pay_twice(self):
        self.deliver(self.payload())
        response = self.deliver(self.payload())
        self.assertEqual(response.json()['duplicate'], True)
        self.assertEqual(Payment.objects.count(), 1)

    def test_bad_or_missing_signature_is_refused(self):
        self.assertEqual(self.deliver(self.payload(), secret='wrong').status_code, 403)
        self.assertFalse(MobileMoneyTransaction.objects.exists())

    @override_settings(MOBILE_MONEY_WEBHOOK_SECRET='')
    def test_endpoint_is_off_without_a_secret(self):
        self.assertEqual(self.deliver(self.payload(), secret='x').status_code, 404)

    def test_malformed_body_gets_400(self):
        self.assertEqual(self.deliver({'amount': 'lots'}).status_code, 400)
        self.assertEqual(self.deliver(self.payload(), provider='unknown').status_code, 400)

    def test_unmatched_payment_waits_then_staff_allocate_it(self):
        self.deliver(self.payload(reference='for the tent'))
        txn = MobileMoneyTransaction.objects.get()
        self.assertEqual(txn.status, MobileMoneyTransaction.Status.UNMATCHED)
        self.assertFalse(Payment.objects.exists())

        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('billing:mobile_money')), 'for the tent')
        self.client.post(reverse('billing:mobile_money_allocate', args=[txn.pk]), {'invoice': self.invoice.pk})
        txn.refresh_from_db()
        self.assertEqual((txn.status, txn.allocated_by), (MobileMoneyTransaction.Status.MATCHED, user))
        self.assertEqual(txn.payment.invoice, self.invoice)
        # A second click can't record it again.
        self.client.post(reverse('billing:mobile_money_allocate', args=[txn.pk]), {'invoice': self.invoice.pk})
        self.assertEqual(Payment.objects.count(), 1)

    def test_cancelled_invoice_is_never_matched(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.CANCELLED)
        self.deliver(self.payload())
        self.assertEqual(MobileMoneyTransaction.objects.get().status, MobileMoneyTransaction.Status.UNMATCHED)


class QuotationLineItemFormTests(TestCase):
    """What the line-item editor actually posts when rows are added and removed in the browser."""

    def setUp(self):
        from .models import Quotation, QuotationLineItem  # noqa: F401
        user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Jane Doe', phone='0772123456')
        self.event = Event.objects.create(
            customer=customer, event_type='Wedding', venue='Kampala', event_date=timezone.localdate() + timedelta(days=10),
        )

    def post_new(self, rows, total_forms):
        """`rows` maps form index -> fields; indexes the browser removed are simply absent."""
        data = {
            'status': 'draft', 'valid_until': '', 'notes': '',
            'line_items-TOTAL_FORMS': str(total_forms), 'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '1', 'line_items-MAX_NUM_FORMS': '1000',
        }
        for i, fields in rows.items():
            for name, value in fields.items():
                data[f'line_items-{i}-{name}'] = value
        return self.client.post(reverse('billing:quotation_create', args=[self.event.pk]), data)

    def line(self, desc='Tent 10x20', qty='1', price='250000'):
        return {'equipment_item': '', 'description': desc, 'quantity': qty, 'unit_price': price}

    def test_removing_the_starting_blank_row_then_adding_one_saves_just_that_line(self):
        from .models import Quotation
        # Row 0 (the starting blank row) was removed; row 1 was added and filled in.
        response = self.post_new({1: self.line()}, total_forms=2)
        quotation = Quotation.objects.get()
        self.assertRedirects(response, quotation.get_absolute_url())
        self.assertEqual([l.description for l in quotation.line_items.all()], ['Tent 10x20'])

    def test_untouched_blank_row_is_ignored(self):
        from .models import Quotation
        response = self.post_new({0: self.line(desc='', qty='1', price=''), 1: self.line()}, total_forms=2)
        quotation = Quotation.objects.get()
        self.assertRedirects(response, quotation.get_absolute_url())
        self.assertEqual(quotation.line_items.count(), 1)

    def test_no_lines_at_all_saves_nothing(self):
        from .models import Quotation
        response = self.post_new({}, total_forms=1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add at least one line')
        self.assertFalse(Quotation.objects.exists())

    def test_invalid_line_saves_no_quotation(self):
        from .models import Quotation
        response = self.post_new({0: self.line(desc='')}, total_forms=1)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Quotation.objects.exists())

    def test_removing_a_saved_line_deletes_it(self):
        from .models import Quotation, QuotationLineItem
        quotation = Quotation.objects.create(event=self.event)
        keep = QuotationLineItem.objects.create(quotation=quotation, description='Keep', quantity=1, unit_price=1)
        drop = QuotationLineItem.objects.create(quotation=quotation, description='Drop', quantity=1, unit_price=1)
        # The browser removes the row but keeps its id and the checked DELETE box; its other inputs are gone.
        data = {
            'status': 'draft', 'valid_until': '', 'notes': '',
            'line_items-TOTAL_FORMS': '2', 'line_items-INITIAL_FORMS': '2',
            'line_items-MIN_NUM_FORMS': '1', 'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-id': str(keep.pk), 'line_items-0-equipment_item': '', 'line_items-0-description': 'Keep',
            'line_items-0-quantity': '1', 'line_items-0-unit_price': '1',
            'line_items-1-id': str(drop.pk), 'line_items-1-DELETE': 'on',
        }
        response = self.client.post(reverse('billing:quotation_update', args=[quotation.pk]), data)
        self.assertRedirects(response, quotation.get_absolute_url())
        self.assertEqual(list(quotation.line_items.values_list('description', flat=True)), ['Keep'])
        self.assertFalse(QuotationLineItem.objects.filter(pk=drop.pk).exists())


class TaxTests(TestCase):
    def setUp(self):
        from django.core.management import call_command
        from .models import TaxGroup
        call_command('setup_chart_of_accounts', verbosity=0)
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)
        customer = Customer.objects.create(name='Jane Doe', phone='0772123456')
        self.event = Event.objects.create(
            customer=customer, event_type='Wedding', venue='Kampala', event_date=timezone.localdate() + timedelta(days=10),
        )
        self.vat = TaxGroup.objects.create(name='VAT', rate=Decimal('18'), is_default=True)

    def post_quotation(self, tax_pk):
        return self.client.post(reverse('billing:quotation_create', args=[self.event.pk]), {
            'status': 'draft', 'valid_until': '', 'notes': '', 'tax_group': tax_pk or '',
            'line_items-TOTAL_FORMS': '1', 'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '1', 'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-equipment_item': '', 'line_items-0-description': 'Tent',
            'line_items-0-quantity': '1', 'line_items-0-unit_price': '100000',
        })

    def test_default_tax_is_preselected_and_added_on_top(self):
        from .models import Quotation
        form = self.client.get(reverse('billing:quotation_create', args=[self.event.pk])).context['form']
        self.assertEqual(form.initial['tax_group'], self.vat.pk)
        self.post_quotation(self.vat.pk)
        quote = Quotation.objects.get()
        self.assertEqual((quote.subtotal, quote.tax_amount, quote.total), (Decimal('100000'), Decimal('18000'), Decimal('118000')))
        self.assertContains(self.client.get(quote.get_absolute_url()), 'VAT (18%)')

    def test_no_tax_when_not_chosen(self):
        from .models import Quotation
        self.post_quotation(None)
        self.assertEqual(Quotation.objects.get().total, Decimal('100000'))

    def test_issued_documents_keep_their_rate(self):
        from .models import Quotation
        self.post_quotation(self.vat.pk)
        self.vat.rate = Decimal('20')
        self.vat.save()
        quote = Quotation.objects.get()
        self.assertEqual(quote.tax_amount, Decimal('18000'))
        invoice = Invoice.create_from_quotation(quote)
        self.assertEqual((invoice.tax_rate, invoice.total), (Decimal('18'), Decimal('118000')))

    def test_payment_tax_share_goes_to_taxes_payable_not_income(self):
        from accounting.models import Account
        from accounting import reports
        from .models import Quotation
        from .services import record_payment
        self.post_quotation(self.vat.pk)
        invoice = Invoice.create_from_quotation(Quotation.objects.get())
        payment, _ = record_payment(invoice, amount=Decimal('59000'), method='cash')  # half the total
        self.assertEqual(payment.income_record.tax_amount, Decimal('9000'))
        balances = reports.balances(timezone.localdate())
        self.assertEqual(balances[Account.objects.get(system_key='tax_payable').pk], Decimal('9000'))
        self.assertEqual(balances[Account.objects.get(system_key='event_income').pk], Decimal('50000'))
        summary = self.client.get(reverse('finance:summary'))
        self.assertEqual(summary.context['total_income'], Decimal('50000'))
        self.assertEqual(summary.context['tax_collected'], Decimal('9000'))

    def test_manage_taxes_and_only_one_default(self):
        from .models import TaxGroup
        self.client.post(reverse('billing:tax_create'), {'name': 'Tourism levy', 'rate': '2', 'is_default': 'on', 'is_active': 'on'})
        self.vat.refresh_from_db()
        self.assertFalse(self.vat.is_default)
        self.assertTrue(TaxGroup.objects.get(name='Tourism levy').is_default)
        page = self.client.get(reverse('billing:tax_list'))
        self.assertEqual(page.context['nav_section'], 'finance')

    def test_existing_taxes_payable_account_is_reused(self):
        from accounting.models import Account
        self.assertEqual(Account.objects.filter(code__startswith='2100').count(), 1)
        self.assertEqual(Account.objects.get(code='2100').system_key, 'tax_payable')
