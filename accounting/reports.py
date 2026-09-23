"""
All figures come straight from journal lines, so every report ties back to the
same entries. There is no year-end closing entry: profit is carried to equity
on the balance sheet by calculation (prior-year earnings + current-year
earnings), which is how Zoho Books presents it too.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.db.models.functions import Coalesce

from .models import Account, JournalLine

ZERO = Decimal('0')
D = Account.Detail
T = Account.Type


def _totals(start=None, end=None):
    """{account_id: (debit, credit)} for lines dated within [start, end]."""
    qs = JournalLine.objects.all()
    if start:
        qs = qs.filter(entry__date__gte=start)
    if end:
        qs = qs.filter(entry__date__lte=end)
    rows = qs.values('account').annotate(
        dr=Coalesce(Sum('debit'), ZERO), cr=Coalesce(Sum('credit'), ZERO),
    )
    return {r['account']: (r['dr'], r['cr']) for r in rows}


def _accounts():
    return list(Account.objects.select_related('parent').order_by('code'))


def fiscal_year_start(as_of):
    month = getattr(settings, 'FISCAL_YEAR_START_MONTH', 1)
    year = as_of.year if as_of.month >= month else as_of.year - 1
    return date(year, month, 1)


def balances(as_of=None):
    """{account_id: natural-sign balance} of every account up to as_of (inclusive)."""
    totals = _totals(end=as_of)
    return {a.pk: a.signed_balance(*totals.get(a.pk, (ZERO, ZERO))) for a in _accounts()}


# ---------- Trial balance ----------

def trial_balance(as_of):
    totals = _totals(end=as_of)
    rows, total_dr, total_cr = [], ZERO, ZERO
    for account in _accounts():
        dr, cr = totals.get(account.pk, (ZERO, ZERO))
        net = dr - cr
        if not net:
            continue
        debit, credit = (net, ZERO) if net > 0 else (ZERO, -net)
        rows.append({'account': account, 'debit': debit, 'credit': credit})
        total_dr += debit
        total_cr += credit
    return {'rows': rows, 'total_debit': total_dr, 'total_credit': total_cr, 'balanced': total_dr == total_cr}


# ---------- Income statement ----------

@dataclass
class Section:
    title: str
    rows: list = field(default_factory=list)
    total: Decimal = ZERO


def _section(title, accounts, totals, detail_types):
    section = Section(title)
    for account in accounts:
        if account.detail_type not in detail_types:
            continue
        amount = account.signed_balance(*totals.get(account.pk, (ZERO, ZERO)))
        if amount:
            section.rows.append({'account': account, 'amount': amount})
            section.total += amount
    return section


def income_statement(start, end):
    totals = _totals(start=start, end=end)
    accounts = _accounts()
    income = _section('Operating income', accounts, totals, {D.INCOME})
    cost_of_sales = _section('Cost of sales', accounts, totals, {D.COST_OF_SALES})
    expenses = _section('Operating expenses', accounts, totals, {D.EXPENSE})
    other_income = _section('Other income', accounts, totals, {D.OTHER_INCOME})
    other_expenses = _section('Other expenses', accounts, totals, {D.OTHER_EXPENSE})
    gross_profit = income.total - cost_of_sales.total
    operating_profit = gross_profit - expenses.total
    net_profit = operating_profit + other_income.total - other_expenses.total
    return {
        'income': income, 'cost_of_sales': cost_of_sales, 'expenses': expenses,
        'other_income': other_income, 'other_expenses': other_expenses,
        'gross_profit': gross_profit, 'operating_profit': operating_profit, 'net_profit': net_profit,
    }


def net_profit(start=None, end=None):
    totals = _totals(start=start, end=end)
    result = ZERO
    for account in _accounts():
        if account.account_type in (T.INCOME, T.EXPENSE):
            dr, cr = totals.get(account.pk, (ZERO, ZERO))
            result += cr - dr  # income is credit-normal, expense debit-normal
    return result


# ---------- Balance sheet ----------

def balance_sheet(as_of):
    totals = _totals(end=as_of)
    accounts = _accounts()
    fy_start = fiscal_year_start(as_of)

    cash = _section('Cash & bank', accounts, totals, {D.CASH_BANK})
    current_assets = _section('Current assets', accounts, totals, {D.CURRENT_ASSET})
    fixed_assets = _section('Fixed assets', accounts, totals, {D.FIXED_ASSET})
    other_assets = _section('Other assets', accounts, totals, {D.OTHER_ASSET})
    total_assets = cash.total + current_assets.total + fixed_assets.total + other_assets.total

    current_liabilities = _section('Current liabilities', accounts, totals, {D.CURRENT_LIABILITY})
    long_term_liabilities = _section('Long-term liabilities', accounts, totals, {D.LONG_TERM_LIABILITY})
    total_liabilities = current_liabilities.total + long_term_liabilities.total

    equity = _section('Equity', accounts, totals, {D.EQUITY})
    prior_earnings = net_profit(end=date.fromordinal(fy_start.toordinal() - 1))
    current_earnings = net_profit(start=fy_start, end=as_of)
    if prior_earnings:
        equity.rows.append({'label': 'Retained earnings (prior years, from profit & loss)', 'amount': prior_earnings})
    equity.rows.append({'label': f'Current year earnings (since {fy_start:%d %b %Y})', 'amount': current_earnings})
    equity.total += prior_earnings + current_earnings

    liabilities_and_equity = total_liabilities + equity.total
    return {
        'asset_sections': [cash, current_assets, fixed_assets, other_assets],
        'liability_sections': [current_liabilities, long_term_liabilities],
        'equity': equity,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'liabilities_and_equity': liabilities_and_equity,
        'difference': total_assets - liabilities_and_equity,
        'fiscal_year_start': fy_start,
    }


# ---------- Account ledger ----------

def account_ledger(account, start=None, end=None):
    """Opening balance before `start`, then each line in range with a running balance."""
    opening = ZERO
    if start:
        dr, cr = _totals(end=date.fromordinal(start.toordinal() - 1)).get(account.pk, (ZERO, ZERO))
        opening = account.signed_balance(dr, cr)
    lines = account.lines.select_related('entry').order_by('entry__date', 'entry__pk', 'pk')
    if start:
        lines = lines.filter(entry__date__gte=start)
    if end:
        lines = lines.filter(entry__date__lte=end)
    running, rows = opening, []
    for line in lines:
        running += account.signed_balance(line.debit, line.credit)
        rows.append({'line': line, 'balance': running})
    return {'opening': opening, 'rows': rows, 'closing': running}
