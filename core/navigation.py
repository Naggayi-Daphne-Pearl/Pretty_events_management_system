"""
The app's navigation in one place: the sidebar's sections, the tab row shown at the
top of a section's main pages, the "+ New" menu and the phone bottom bar. Exposed to
every template by core.context_processors.navigation.

A section shows for a user when they can see at least one of its tabs (or its page,
for sections without tabs), so each role gets only the parts it works in.
"""
from dataclasses import dataclass, field

from django.urls import reverse

from .permissions import restricted_to_own_events


@dataclass(frozen=True)
class Tab:
    label: str
    url_name: str
    perms: tuple = ()          # any one of these is enough; empty = everyone
    also: tuple = ()           # other url names that count as being on this tab


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    icon: str
    url_name: str = ''         # where a section without tabs goes
    perms: tuple = ()
    apps: tuple = ()           # pages of these apps belong to the section...
    pages: tuple = ()          # ...and these extra 'app:url_name' pages
    exclude: tuple = ()        # ...except these 'app:url_name' pages
    tabs: tuple = field(default_factory=tuple)
    superuser_only: bool = False


SECTIONS = (
    Section('dashboard', 'Dashboard', 'bi-speedometer2', url_name='dashboard', pages=(':dashboard', ':search')),
    Section('events', 'Events', 'bi-calendar-event', apps=('events',), tabs=(
        Tab('Calendar', 'events:calendar', ('events.view_event',)),
        Tab('List', 'events:list', ('events.view_event',)),
    )),
    Section('customers', 'Customers', 'bi-people', apps=('customers', 'comms'), tabs=(
        Tab('Customers', 'customers:list', ('customers.view_customer',)),
        Tab('Contact log', 'comms:list', ('comms.view_communicationlog',)),
    )),
    Section('billing', 'Billing', 'bi-receipt', apps=('billing',), tabs=(
        Tab('Invoices', 'billing:invoice_list', ('billing.view_invoice',)),
        Tab('Quotations', 'billing:quotation_list', ('billing.view_quotation',)),
        Tab('Receipts', 'billing:receipt_list', ('billing.view_receipt',)),
        Tab('Mobile money', 'billing:mobile_money', ('billing.view_payment',)),
    )),
    Section('inventory', 'Inventory', 'bi-box-seam', apps=('inventory',), tabs=(
        Tab('Items', 'inventory:item_list', ('inventory.view_equipmentitem',)),
        Tab('Categories', 'inventory:category_list', ('inventory.view_equipmentcategory',)),
    )),
    Section('staff', 'Staff', 'bi-person-badge', url_name='staffing:list', perms=('staffing.view_staffmember',),
            apps=('staffing',)),
    Section('finance', 'Finance', 'bi-cash-coin', apps=('finance', 'accounting'),
            exclude=('accounting:reports', 'accounting:trial_balance', 'accounting:income_statement',
                     'accounting:balance_sheet'),
            tabs=(
                Tab('Overview', 'finance:summary', ('finance.view_incomerecord', 'finance.view_expenserecord')),
                Tab('Income', 'finance:income_list', ('finance.view_incomerecord',)),
                Tab('Expenses', 'finance:expense_list', ('finance.view_expenserecord',), also=('finance:category_list',)),
                Tab('Banking', 'accounting:banking', ('accounting.view_account',)),
                Tab('Journals', 'accounting:journal_list', ('accounting.view_journalentry',)),
                Tab('Accounts', 'accounting:chart', ('accounting.view_account',)),
                Tab('Close books', 'accounting:period_close', ('accounting.view_periodclose',)),
            )),
    Section('reports', 'Reports', 'bi-bar-chart-line', url_name='reports:index', apps=('reports',),
            pages=('accounting:reports', 'accounting:trial_balance', 'accounting:income_statement',
                   'accounting:balance_sheet'),
            perms=('events.view_event', 'billing.view_invoice', 'inventory.view_equipmentitem',
                   'finance.view_incomerecord', 'finance.view_expenserecord', 'accounting.view_journalentry')),
    Section('admin', 'Administration', 'bi-shield-lock', superuser_only=True,
            pages=(':role_list', ':role_create', ':role_update', ':role_delete', ':activity_log'),
            tabs=(
                Tab('Roles & permissions', 'role_list', also=('role_create', 'role_update', 'role_delete')),
                Tab('Activity log', 'activity_log'),
            )),
)

# "+ New": the most common things to create, from anywhere.
NEW_MENU = (
    ('Event', 'bi-calendar-plus', 'events:create', 'events.add_event'),
    ('Customer', 'bi-person-plus', 'customers:create', 'customers.add_customer'),
    ('Expense', 'bi-wallet2', 'finance:expense_create', 'finance.add_expenserecord'),
    ('Income', 'bi-cash-stack', 'finance:income_create', 'finance.add_incomerecord'),
    ('Journal entry', 'bi-journal-plus', 'accounting:journal_create', 'accounting.add_journalentry'),
)

# Phone bottom bar: these sections (when visible), then Search and More.
BOTTOM_BAR = ('dashboard', 'events', 'billing')


def _allowed(user, perms):
    return not perms or any(user.has_perm(p) for p in perms)


def _key(url_name):
    """'billing:invoice_list' stays as is; a url name without a namespace becomes ':role_list'."""
    return url_name if ':' in url_name else f':{url_name}'


def _page_key(match):
    return f'{match.app_name}:{match.url_name}' if match else ''


def _in_section(section, match):
    if match is None:
        return False
    key = _page_key(match)
    if key in section.exclude:
        return False
    return key in section.pages or (bool(match.app_name) and match.app_name in section.apps)


def _badges(user):
    """Counts that need attention, shown next to their section in the sidebar."""
    from billing.models import Invoice
    from inventory.models import EquipmentItem

    badges = {}
    if user.has_perm('billing.view_invoice'):
        badges['billing'] = Invoice.objects.filter(status=Invoice.Status.OVERDUE).count()
    if user.has_perm('inventory.view_equipmentitem'):
        badges['inventory'] = EquipmentItem.objects.low_stock().count()
    return {key: count for key, count in badges.items() if count}


def build(request):
    user = request.user
    match = request.resolver_match
    current_key = _page_key(match)
    badges = _badges(user)

    items, active_tabs = [], []
    for section in SECTIONS:
        if section.superuser_only and not user.is_superuser:
            continue
        tabs = [t for t in section.tabs if _allowed(user, t.perms)]
        if section.tabs and not tabs:
            continue
        if not section.tabs and not _allowed(user, section.perms):
            continue
        if section.key == 'reports' and restricted_to_own_events(user):
            continue  # business-wide reports aren't for roles that only see their own events
        active = _in_section(section, match)
        items.append({
            'key': section.key, 'label': section.label, 'icon': section.icon, 'active': active,
            'url': reverse(tabs[0].url_name if tabs else section.url_name), 'badge': badges.get(section.key),
        })
        if active and len(tabs) > 1:
            on_tab = [t for t in tabs if current_key in {_key(n) for n in (t.url_name, *t.also)}]
            # The tab row belongs on a section's main pages, not on every detail/form page.
            if on_tab:
                active_tabs = [
                    {'label': t.label, 'url': reverse(t.url_name), 'active': t is on_tab[0]} for t in tabs
                ]

    by_key = {item['key']: item for item in items}
    return {
        'nav_items': items,
        'nav_tabs': active_tabs,
        'nav_section': next((i['key'] for i in items if i['active']), ''),
        'nav_new': [
            {'label': label, 'icon': icon, 'url': reverse(url_name)}
            for label, icon, url_name, perm in NEW_MENU if user.has_perm(perm)
        ],
        'nav_bottom': [by_key[key] for key in BOTTOM_BAR if key in by_key],
    }
