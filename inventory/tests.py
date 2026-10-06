from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem, Quotation, QuotationLineItem
from customers.models import Customer
from events.models import Event

from .models import EquipmentIssue, EquipmentItem, EquipmentReturn
from .services import availability, availability_for_event, event_shortages


class ReservationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Jane Doe', phone='0772123456')
        self.saturday = timezone.localdate() + timedelta(days=12)
        self.tables = EquipmentItem.objects.create(name='Round table', total_quantity=24)

    def booked_event(self, qty, date=None, status=Event.Status.CONFIRMED, end_date=None):
        event = Event.objects.create(
            customer=self.customer, event_type='Wedding', venue='Kampala', status=status,
            event_date=date or self.saturday, end_date=end_date,
        )
        invoice = Invoice.objects.create(event=event)
        InvoiceLineItem.objects.create(
            invoice=invoice, equipment_item=self.tables, description='Round table',
            quantity=qty, unit_price=Decimal('5000'),
        )
        return event

    def test_same_day_bookings_reduce_availability(self):
        first = self.booked_event(20)
        second = self.booked_event(20)
        self.assertEqual(availability_for_event(second)[self.tables.pk], 4)
        [shortage] = event_shortages(second)
        self.assertEqual((shortage['needed'], shortage['available']), (20, 4))
        self.assertEqual(shortage['clashes'], [first])

    def test_different_days_do_not_clash(self):
        self.booked_event(20)
        other = self.booked_event(20, date=self.saturday + timedelta(days=1))
        self.assertEqual(event_shortages(other), [])

    def test_multi_day_window_uses_busiest_day_not_the_sum(self):
        self.booked_event(10, date=self.saturday)
        self.booked_event(12, date=self.saturday + timedelta(days=1))
        free = availability(self.saturday, self.saturday + timedelta(days=1))
        self.assertEqual(free[self.tables.pk], 12)

    def test_inquiries_and_cancelled_events_reserve_nothing(self):
        self.booked_event(20, status=Event.Status.INQUIRY)
        self.booked_event(20, status=Event.Status.CANCELLED)
        self.assertEqual(availability(self.saturday)[self.tables.pk], 24)

    def test_approved_quotation_reserves_when_there_is_no_invoice(self):
        event = Event.objects.create(
            customer=self.customer, event_type='Party', venue='X', status=Event.Status.CONFIRMED,
            event_date=self.saturday,
        )
        quote = Quotation.objects.create(event=event, status=Quotation.Status.APPROVED)
        QuotationLineItem.objects.create(
            quotation=quote, equipment_item=self.tables, description='t', quantity=9, unit_price=Decimal('1'),
        )
        self.assertEqual(availability(self.saturday)[self.tables.pk], 15)

    def test_equipment_not_back_from_an_earlier_event_is_unavailable(self):
        past = self.booked_event(5, date=timezone.localdate() - timedelta(days=3))
        issue = EquipmentIssue.objects.create(
            event=past, equipment_item=self.tables, quantity_issued=5, issued_at=past.event_date,
        )
        self.assertEqual(availability(self.saturday)[self.tables.pk], 19)
        EquipmentReturn.objects.create(issue=issue, quantity_returned=5, returned_at=timezone.localdate())
        self.assertEqual(availability(self.saturday)[self.tables.pk], 24)

    def test_out_but_due_back_before_the_date_counts_as_free(self):
        past = self.booked_event(5, date=timezone.localdate())
        EquipmentIssue.objects.create(
            event=past, equipment_item=self.tables, quantity_issued=5, issued_at=past.event_date,
            expected_return_date=timezone.localdate() + timedelta(days=2),
        )
        self.assertEqual(availability(self.saturday)[self.tables.pk], 24)

    def test_event_page_lists_the_shortage(self):
        self.booked_event(20)
        second = self.booked_event(20)
        response = self.client.get(reverse('events:detail', args=[second.pk]))
        self.assertContains(response, 'Not enough equipment on these dates')
        self.assertContains(response, '20 booked, 4 free')

    def test_quotation_form_checks_stock_for_the_event_dates(self):
        self.booked_event(20)
        new = Event.objects.create(customer=self.customer, event_type='Party', venue='X', event_date=self.saturday)
        response = self.client.get(reverse('billing:quotation_create', args=[new.pk]))
        info = response.context['equipment_items'][str(self.tables.pk)]
        self.assertEqual(info['available'], 4)

    def test_item_page_lists_upcoming_bookings(self):
        self.booked_event(20)
        response = self.client.get(reverse('inventory:item_detail', args=[self.tables.pk]))
        self.assertContains(response, 'Booked for upcoming events')
        self.assertEqual(response.context['bookings'][0]['free'], 4)
