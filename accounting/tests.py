from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem, Payment
from customers.models import Customer
from events.models import Event
from finance.models import ExpenseCategory, ExpenseRecord, IncomeRecord

from . import reports
from .chart import ensure_chart_of_accounts, system_account
from .models import Account, JournalEntry, JournalLine
from .posting import post_history
from .services import save_entry

User = get_user_model()
TODAY = timezone.localdate()


class LedgerTestMixin:
    def setUp(self):
        ensure_chart_of_accounts()
        self.user = User.objects.create_superuser('acc', 'acc@example.com', 'pw')
        self.client.force_login(self.user)
        self.cash = system_account('cash')
        self.bank = system_account('bank')
        self.momo = system_account('mobile_money')
        self.event_income = system_account('event_income')
        self.general = system_account('general_expense')
        self.equity = Account.objects.get(code='3000')
        self.loan = Account.objects.get(code='2500')
        self.tents = Account.objects.get(code='1500')

    def journal(self, lines, when=TODAY, source=JournalEntry.Source.MANUAL):
        return save_entry(JournalEntry(date=when, memo='test', source=source), [
            {'account': a, 'debit': Decimal(dr), 'credit': Decimal(cr)} for a, dr, cr in lines
        ])

    def paid_invoice(self, amount, method='mobile_money'):
        customer = Customer.objects.create(name='Client', phone='0772000000')
        event = Event.objects.create(customer=customer, event_type='Wedding', event_date=TODAY, venue='X')
        invoice = Invoice.objects.create(event=event)
        InvoiceLineItem.objects.create(invoice=invoice, description='Tent', unit_price=Decimal(amount))
        payment = Payment.objects.create(invoice=invoice, amount=Decimal(amount), method=method)
        IncomeRecord.objects.create(amount=payment.amount, source=IncomeRecord.Source.INVOICE_PAYMENT,
                                    date=payment.paid_at, event=event, payment=payment, description='Payment')
        return invoice


class ChartTests(LedgerTestMixin, TestCase):
    def test_seed_is_idempotent_and_keeps_renames(self):
        self.cash.name = 'Petty Cash Box'
        self.cash.save()
        self.assertEqual(ensure_chart_of_accounts(), 0)
        self.assertEqual(system_account('cash').name, 'Petty Cash Box')

    def test_detail_type_must_match_type(self):
        account = Account(code='9999', name='Bad', account_type='income', detail_type='cash_bank')
        with self.assertRaises(ValidationError):
            account.full_clean()

    def test_sub_account_must_share_type(self):
        account = Account(code='1501', name='Big tents', account_type='expense', detail_type='expense', parent=self.tents)
        with self.assertRaises(ValidationError):
            account.full_clean()


class BalancedEntryTests(LedgerTestMixin, TestCase):
    def test_unbalanced_entry_is_refused_and_nothing_saved(self):
        with self.assertRaises(ValidationError):
            self.journal([(self.cash, '100', '0'), (self.equity, '0', '90')])
        self.assertFalse(JournalEntry.objects.exists())

    def test_single_line_refused(self):
        with self.assertRaises(ValidationError):
            self.journal([(self.cash, '100', '0')])

    def test_db_rejects_line_with_both_sides(self):
        entry = self.journal([(self.cash, '100', '0'), (self.equity, '0', '100')])
        with self.assertRaises(IntegrityError):
            JournalLine.objects.create(entry=entry, account=self.cash, debit=5, credit=5)

    def test_inactive_account_refused_for_manual_entries(self):
        self.tents.is_active = False
        self.tents.save()
        with self.assertRaises(ValidationError):
            self.journal([(self.tents, '100', '0'), (self.equity, '0', '100')])


class AutoPostingTests(LedgerTestMixin, TestCase):
    def test_invoice_payment_posts_to_account_for_method(self):
        self.paid_invoice('250000', method='mobile_money')
        entry = JournalEntry.objects.get(source=JournalEntry.Source.INCOME)
        lines = {l.account.system_key: l for l in entry.lines.select_related('account')}
        self.assertEqual(lines['mobile_money'].debit, Decimal('250000'))
        self.assertEqual(lines['event_income'].credit, Decimal('250000'))

    def test_cash_basis_unpaid_invoice_posts_nothing(self):
        customer = Customer.objects.create(name='C', phone='1')
        event = Event.objects.create(customer=customer, event_type='X', event_date=TODAY, venue='Y')
        invoice = Invoice.objects.create(event=event)
        InvoiceLineItem.objects.create(invoice=invoice, description='Tent', unit_price=Decimal('500000'))
        self.assertFalse(JournalEntry.objects.exists())

    def test_expense_uses_category_account_and_paid_from(self):
        fuel = Account.objects.get(code='6030')
        category = ExpenseCategory.objects.create(name='Fuel', account=fuel)
        ExpenseRecord.objects.create(amount=Decimal('80000'), category=category, date=TODAY, paid_from_account=self.momo)
        entry = JournalEntry.objects.get(source=JournalEntry.Source.EXPENSE)
        self.assertEqual(entry.lines.get(account=fuel).debit, Decimal('80000'))
        self.assertEqual(entry.lines.get(account=self.momo).credit, Decimal('80000'))

    def test_expense_defaults_to_general_and_cash(self):
        category = ExpenseCategory.objects.create(name='Misc')
        ExpenseRecord.objects.create(amount=Decimal('1000'), category=category, date=TODAY)
        entry = JournalEntry.objects.get()
        self.assertEqual(entry.lines.get(account=self.general).debit, Decimal('1000'))
        self.assertEqual(entry.lines.get(account=self.cash).credit, Decimal('1000'))

    def test_editing_record_updates_entry_and_deleting_removes_it(self):
        category = ExpenseCategory.objects.create(name='Misc')
        record = ExpenseRecord.objects.create(amount=Decimal('1000'), category=category, date=TODAY)
        record.amount = Decimal('1500')
        record.save()
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.get().total, Decimal('1500'))
        record.delete()
        self.assertFalse(JournalEntry.objects.exists())

    def test_post_history_only_fills_gaps(self):
        category = ExpenseCategory.objects.create(name='Misc')
        record = ExpenseRecord.objects.create(amount=Decimal('1000'), category=category, date=TODAY)
        JournalEntry.objects.all().delete()
        self.assertEqual(post_history(), (0, 1))
        self.assertEqual(post_history(), (0, 0))
        self.assertTrue(JournalEntry.objects.filter(expense_record=record).exists())

    def test_auto_entries_cannot_be_edited_or_deleted_in_journal_ui(self):
        self.paid_invoice('1000')
        entry = JournalEntry.objects.get()
        self.assertRedirects(self.client.get(reverse('accounting:journal_update', args=[entry.pk])), entry.get_absolute_url())
        self.client.post(reverse('accounting:journal_delete', args=[entry.pk]))
        self.assertTrue(JournalEntry.objects.filter(pk=entry.pk).exists())


class ReportTests(LedgerTestMixin, TestCase):
    def build_books(self):
        # Owner puts in 5,000,000 cash; loan of 2,000,000 to bank; buy tents 3,000,000 from bank;
        # earn 1,000,000 by mobile money; spend 200,000 cash on general expenses.
        self.journal([(self.cash, '5000000', '0'), (self.equity, '0', '5000000')])
        self.journal([(self.bank, '2000000', '0'), (self.loan, '0', '2000000')])
        self.journal([(self.tents, '3000000', '0'), (self.bank, '0', '3000000')])
        self.paid_invoice('1000000')
        ExpenseRecord.objects.create(amount=Decimal('200000'), category=ExpenseCategory.objects.create(name='Misc'), date=TODAY)

    def test_trial_balance_balances(self):
        self.build_books()
        tb = reports.trial_balance(TODAY)
        self.assertTrue(tb['balanced'])
        # Debits: cash 4.8m + momo 1m + tents 3m + expenses 0.2m = 9.0m.
        # Credits: capital 5m + loan 2m + income 1m + overdrawn bank 1m = 9.0m.
        self.assertEqual(tb['total_debit'], Decimal('9000000'))
        self.assertEqual(tb['total_credit'], Decimal('9000000'))

    def test_income_statement(self):
        self.build_books()
        report = reports.income_statement(TODAY.replace(day=1), TODAY)
        self.assertEqual(report['income'].total, Decimal('1000000'))
        self.assertEqual(report['expenses'].total, Decimal('200000'))
        self.assertEqual(report['net_profit'], Decimal('800000'))

    def test_balance_sheet_balances_with_earnings_in_equity(self):
        self.build_books()
        bs = reports.balance_sheet(TODAY)
        # Assets: cash 4.8m + momo 1m + bank -1m + tents 3m = 7.8m
        self.assertEqual(bs['total_assets'], Decimal('7800000'))
        self.assertEqual(bs['total_liabilities'], Decimal('2000000'))
        self.assertEqual(bs['equity'].total, Decimal('5800000'))  # 5m capital + 0.8m current earnings
        self.assertEqual(bs['difference'], 0)

    def test_prior_year_profit_moves_to_retained_earnings(self):
        last_year = date(TODAY.year - 1, 6, 1)
        other_income = system_account('other_income')
        self.journal([(self.cash, '300000', '0'), (other_income, '0', '300000')], when=last_year)
        bs = reports.balance_sheet(TODAY)
        labels = {r.get('label', ''): r['amount'] for r in bs['equity'].rows}
        self.assertEqual(labels['Retained earnings (prior years, from profit & loss)'], Decimal('300000'))
        self.assertEqual(bs['difference'], 0)

    def test_account_ledger_running_balance(self):
        self.journal([(self.cash, '1000', '0'), (self.equity, '0', '1000')], when=TODAY - timedelta(days=10))
        self.journal([(self.general, '300', '0'), (self.cash, '0', '300')])
        ledger = reports.account_ledger(self.cash, start=TODAY - timedelta(days=5), end=TODAY)
        self.assertEqual(ledger['opening'], Decimal('1000'))
        self.assertEqual(ledger['closing'], Decimal('700'))

    def test_report_pages_and_csv_render(self):
        self.build_books()
        for name in ('accounting:chart', 'accounting:journal_list', 'accounting:banking', 'accounting:reports',
                     'accounting:trial_balance', 'accounting:income_statement', 'accounting:balance_sheet'):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        for name in ('accounting:chart', 'accounting:trial_balance', 'accounting:income_statement', 'accounting:balance_sheet'):
            with self.subTest(csv=name):
                response = self.client.get(reverse(name), {'format': 'csv'})
                self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertEqual(self.client.get(reverse('accounting:account_detail', args=[self.cash.pk])).status_code, 200)


class JournalUITests(LedgerTestMixin, TestCase):
    def post_journal(self, lines):
        data = {'date': TODAY.isoformat(), 'source': 'manual', 'reference': '', 'memo': 'Capital',
                'lines-TOTAL_FORMS': str(len(lines)), 'lines-INITIAL_FORMS': '0',
                'lines-MIN_NUM_FORMS': '2', 'lines-MAX_NUM_FORMS': '1000'}
        for i, (account, dr, cr) in enumerate(lines):
            data.update({f'lines-{i}-account': account.pk, f'lines-{i}-debit': dr, f'lines-{i}-credit': cr, f'lines-{i}-description': ''})
        return self.client.post(reverse('accounting:journal_create'), data)

    def test_new_journal_defaults_to_today(self):
        response = self.client.get(reverse('accounting:journal_create'))
        self.assertContains(response, f'value="{TODAY.isoformat()}"')

    def test_create_balanced_journal(self):
        response = self.post_journal([(self.cash, '100000', ''), (self.equity, '', '100000')])
        entry = JournalEntry.objects.get()
        self.assertRedirects(response, entry.get_absolute_url())
        self.assertEqual(entry.created_by, self.user)

    def test_unbalanced_journal_shows_error(self):
        response = self.post_journal([(self.cash, '100000', ''), (self.equity, '', '90000')])
        self.assertContains(response, 'must be equal')
        self.assertFalse(JournalEntry.objects.exists())

    def test_transfer_between_bank_accounts(self):
        self.client.post(reverse('accounting:transfer_create'), {
            'from_account': self.cash.pk, 'to_account': self.bank.pk, 'amount': '50000', 'date': TODAY.isoformat(),
        })
        entry = JournalEntry.objects.get(source=JournalEntry.Source.TRANSFER)
        self.assertEqual(entry.lines.get(account=self.bank).debit, Decimal('50000'))
        self.assertEqual(entry.lines.get(account=self.cash).credit, Decimal('50000'))

    def test_account_with_history_cannot_be_deleted_or_retyped(self):
        self.journal([(self.tents, '100', '0'), (self.equity, '0', '100')])
        self.client.post(reverse('accounting:account_delete', args=[self.tents.pk]))
        self.assertTrue(Account.objects.filter(pk=self.tents.pk).exists())
        self.client.post(reverse('accounting:account_update', args=[self.tents.pk]), {
            'code': '1500', 'name': 'Tents', 'account_type': 'expense', 'detail_type': 'fixed_asset', 'is_active': 'on',
        })
        self.tents.refresh_from_db()
        self.assertEqual(self.tents.account_type, 'asset')

    def test_system_account_cannot_be_deleted(self):
        self.client.post(reverse('accounting:account_delete', args=[self.cash.pk]))
        self.assertTrue(Account.objects.filter(pk=self.cash.pk).exists())


class AccountingPermissionTests(LedgerTestMixin, TestCase):
    def test_accountant_role_and_office_staff_access(self):
        from django.contrib.auth.models import Group
        from django.core.management import call_command
        call_command('setup_groups', stdout=open('/dev/null', 'w'))
        accountant = User.objects.create_user('a', email='a@example.com', password='x')
        accountant.groups.add(Group.objects.get(name='Accountant'))
        office = User.objects.create_user('o', email='o@example.com', password='x')
        office.groups.add(Group.objects.get(name='Office Staff'))
        self.client.force_login(accountant)
        self.assertEqual(self.client.get(reverse('accounting:balance_sheet')).status_code, 200)
        self.client.force_login(office)
        self.assertEqual(self.client.get(reverse('accounting:balance_sheet')).status_code, 403)


class AccountEntryTests(LedgerTestMixin, TestCase):
    def post_entry(self, account, **data):
        payload = {'side': 'debit', 'amount': '750000', 'offset_account': self.equity.pk,
                   'date': TODAY.isoformat(), 'source': 'manual', 'reference': 'R1', 'memo': ''}
        payload.update(data)
        return self.client.post(reverse('accounting:account_entry', args=[account.pk]), payload)

    def test_debit_entry_on_asset_account(self):
        response = self.post_entry(self.tents)
        self.assertRedirects(response, self.tents.get_absolute_url())
        entry = JournalEntry.objects.get()
        self.assertEqual(entry.lines.get(account=self.tents).debit, Decimal('750000'))
        self.assertEqual(entry.lines.get(account=self.equity).credit, Decimal('750000'))
        self.assertEqual(entry.source, 'manual')
        self.assertEqual(entry.created_by, self.user)

    def test_credit_entry_and_opening_balance_type(self):
        obe = system_account('opening_balance_equity')
        self.post_entry(self.loan, side='credit', offset_account=obe.pk, source='opening')
        entry = JournalEntry.objects.get()
        self.assertEqual(entry.source, 'opening')
        self.assertEqual(entry.lines.get(account=self.loan).credit, Decimal('750000'))
        self.assertEqual(reports.balances(TODAY)[self.loan.pk], Decimal('750000'))  # liability increased

    def test_same_account_on_both_sides_not_offered(self):
        response = self.post_entry(self.tents, offset_account=self.tents.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JournalEntry.objects.exists())

    def test_inactive_account_blocked(self):
        self.tents.is_active = False
        self.tents.save()
        self.assertRedirects(self.post_entry(self.tents), self.tents.get_absolute_url())
        self.assertFalse(JournalEntry.objects.exists())

    def test_labels_explain_effect_on_account(self):
        page = self.client.get(reverse('accounting:account_entry', args=[self.loan.pk]))
        self.assertContains(page, 'Credited (increases Loans Payable)')
        self.assertContains(page, 'Debited (decreases Loans Payable)')

    def test_multi_line_journal_prefills_account(self):
        page = self.client.get(reverse('accounting:journal_create'), {'account': self.tents.pk})
        self.assertContains(page, f'<option value="{self.tents.pk}" selected>')

    def test_requires_add_journal_permission(self):
        viewer = User.objects.create_user('v', email='v@example.com', password='x')
        self.client.force_login(viewer)
        self.assertEqual(self.post_entry(self.tents).status_code, 403)


class ExpenseFormAccountTests(LedgerTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fuel = Account.objects.get(code='6030')
        self.rent = Account.objects.get(code='6010')
        self.category = ExpenseCategory.objects.create(name='Fuel', account=self.fuel)

    def add_expense(self, **extra):
        data = {'amount': '120000', 'category': self.category.pk, 'date': TODAY.isoformat(),
                'expense_account': '', 'paid_from_account': '', 'event': '', 'description': 'Generator fuel'}
        data.update(extra)
        return self.client.post(reverse('finance:expense_create'), data)

    def test_form_lists_expense_ledger_accounts_only(self):
        page = self.client.get(reverse('finance:expense_create')).content.decode()
        self.assertIn('6030 · Fuel (Operating expense)', page)
        self.assertIn('5000 · Event Labour (Cost of sales)', page)
        self.assertNotIn('1000 · Cash on Hand (', page)  # assets aren't expense accounts
        self.assertIn(f'"{self.category.pk}": {self.fuel.pk}', page)  # category -> account prefill map

    def test_chosen_account_is_posted(self):
        self.add_expense(expense_account=self.rent.pk, paid_from_account=self.bank.pk)
        record = ExpenseRecord.objects.get()
        self.assertEqual(record.expense_account, self.rent)
        entry = record.journal_entry
        self.assertEqual(entry.lines.get(account=self.rent).debit, Decimal('120000'))
        self.assertEqual(entry.lines.get(account=self.bank).credit, Decimal('120000'))

    def test_blank_account_falls_back_to_category(self):
        self.add_expense()
        self.assertEqual(ExpenseRecord.objects.get().journal_entry.lines.get(debit__gt=0).account, self.fuel)

    def test_account_used_by_expenses_cannot_be_deleted(self):
        self.add_expense(expense_account=self.rent.pk)
        self.client.post(reverse('accounting:account_delete', args=[self.rent.pk]))
        self.assertTrue(Account.objects.filter(pk=self.rent.pk).exists())
