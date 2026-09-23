"""
Starter chart of accounts for an events & tent-hire company. Seeded once
(`manage.py setup_chart_of_accounts`, also run on deploy); accountants can then
add, rename, re-code and deactivate accounts freely. Accounts with a system_key
are the ones the app posts to automatically, found by key, not by code or name,
so renaming or re-coding them is safe.
"""
from .models import Account

A, L, E, I, X = (Account.Type.ASSET, Account.Type.LIABILITY, Account.Type.EQUITY,
                 Account.Type.INCOME, Account.Type.EXPENSE)
D = Account.Detail

# (code, name, type, detail, system_key)
DEFAULT_CHART = [
    ('1000', 'Cash on Hand', A, D.CASH_BANK, 'cash'),
    ('1010', 'Mobile Money', A, D.CASH_BANK, 'mobile_money'),
    ('1020', 'Bank Account', A, D.CASH_BANK, 'bank'),
    ('1200', 'Staff Advances', A, D.CURRENT_ASSET, None),
    ('1300', 'Prepaid Expenses', A, D.CURRENT_ASSET, None),
    ('1500', 'Tents & Event Equipment', A, D.FIXED_ASSET, None),
    ('1510', 'Furniture & Decor', A, D.FIXED_ASSET, None),
    ('1520', 'Motor Vehicles', A, D.FIXED_ASSET, None),
    ('1590', 'Accumulated Depreciation', A, D.FIXED_ASSET, None),
    ('2000', 'Accounts Payable', L, D.CURRENT_LIABILITY, None),
    ('2100', 'Taxes Payable (VAT / PAYE / WHT)', L, D.CURRENT_LIABILITY, None),
    ('2200', 'Salaries Payable', L, D.CURRENT_LIABILITY, None),
    ('2300', 'Client Deposits Held', L, D.CURRENT_LIABILITY, None),
    ('2500', 'Loans Payable', L, D.LONG_TERM_LIABILITY, None),
    ('3000', "Owner's Capital", E, D.EQUITY, None),
    ('3100', "Owner's Drawings", E, D.EQUITY, None),
    ('3200', 'Retained Earnings', E, D.EQUITY, 'retained_earnings'),
    ('3900', 'Opening Balance Equity', E, D.EQUITY, 'opening_balance_equity'),
    ('4000', 'Event Services Income', I, D.INCOME, 'event_income'),
    ('4100', 'Equipment Hire Income', I, D.INCOME, None),
    ('4900', 'Other Income', I, D.OTHER_INCOME, 'other_income'),
    ('5000', 'Event Labour', X, D.COST_OF_SALES, None),
    ('5010', 'Transport & Delivery', X, D.COST_OF_SALES, None),
    ('5020', 'Equipment Repairs & Cleaning', X, D.COST_OF_SALES, None),
    ('5030', 'Equipment Hired In', X, D.COST_OF_SALES, None),
    ('6000', 'Salaries & Wages', X, D.EXPENSE, None),
    ('6010', 'Rent', X, D.EXPENSE, None),
    ('6020', 'Utilities & Internet', X, D.EXPENSE, None),
    ('6030', 'Fuel', X, D.EXPENSE, None),
    ('6040', 'Marketing & Advertising', X, D.EXPENSE, None),
    ('6050', 'Bank & Mobile Money Charges', X, D.EXPENSE, None),
    ('6060', 'Depreciation', X, D.EXPENSE, None),
    ('6070', 'Office & Stationery', X, D.EXPENSE, None),
    ('6900', 'General Expenses', X, D.EXPENSE, 'general_expense'),
]


def ensure_chart_of_accounts():
    """Create any missing default accounts. Never modifies accounts that already exist
    (an accountant may have renamed them), so it's safe to run on every deploy."""
    created = 0
    for code, name, account_type, detail, key in DEFAULT_CHART:
        if key and Account.objects.filter(system_key=key).exists():
            continue
        if not key and Account.objects.filter(code=code).exists():
            continue
        if key and Account.objects.filter(code=code).exists():
            # Someone already used this code for something else; give the system account a free one.
            code = next(f'{code}-{n}' for n in range(1, 100) if not Account.objects.filter(code=f'{code}-{n}').exists())
        Account.objects.create(code=code, name=name, account_type=account_type, detail_type=detail, system_key=key)
        created += 1
    return created


def system_account(key):
    """The account the app auto-posts to for `key` (e.g. 'cash'), creating the chart if needed."""
    account = Account.objects.filter(system_key=key).first()
    if account is None:
        ensure_chart_of_accounts()
        account = Account.objects.get(system_key=key)
    return account
