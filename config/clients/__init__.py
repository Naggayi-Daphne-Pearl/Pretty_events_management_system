"""
One codebase, one deployment per client.

Everything that differs between businesses running this system lives in a client
profile: config/clients/<slug>.py defines PROFILE = Client(...). The deployment picks
its profile with the CLIENT environment variable (default: pretty_events), and
config/settings/base.py turns it into the COMPANY_*, THEME, FEATURES and TERMS
settings the rest of the app reads. Logos and app icons live in
assets/clients/<slug>/ (logo.png, logo-dark.png, icons/).

To add a client: copy an existing profile, change it, add its assets, and deploy
with CLIENT=<slug>. No code changes elsewhere.
"""
import importlib
from dataclasses import dataclass, field

# Optional modules a client can switch on or off. Everything else (customers, the
# events/projects list, billing, finance, accounting, staff, reports) is always on.
#   inventory      equipment register, reservations on quotations/invoices, issue & return,
#                  packing lists, the field job sheet and the inventory report
#   subscriptions  recurring charges (hosting, domains, retainers) that invoice themselves
ALL_FEATURES = frozenset({'inventory', 'subscriptions'})

# Brand colours, as CSS custom properties set in templates/base.html (light and dark
# theme). *-text variants are the shades that stay readable as text on that theme.
THEME_KEYS = ('primary', 'primary-hover', 'primary-text', 'primary-soft', 'on-primary',
              'accent', 'accent-text', 'accent-soft', 'sky')


@dataclass(frozen=True)
class Terms:
    """
    What the business calls its jobs. The data model always says Event; these are the
    words people see. Templates use {{ T.event }}, {{ T.Events }} and so on.
    """
    event: str = 'event'
    events: str = ''                      # plural; default adds an "s"
    event_type_help: str = 'e.g. Wedding, Introduction, Corporate function'
    event_date: str = 'Event date'
    end_date: str = 'End date'
    end_date_help: str = 'Leave blank for single-day events'
    customer: str = 'customer'
    customers: str = ''

    def as_context(self):
        events = self.events or f'{self.event}s'
        customers = self.customers or f'{self.customer}s'
        return {
            'event': self.event, 'events': events,
            'Event': self.event[:1].upper() + self.event[1:], 'Events': events[:1].upper() + events[1:],
            'customer': self.customer, 'customers': customers,
            'Customer': self.customer[:1].upper() + self.customer[1:],
            'Customers': customers[:1].upper() + customers[1:],
            'event_type_help': self.event_type_help,
            'event_date': self.event_date, 'end_date': self.end_date, 'end_date_help': self.end_date_help,
        }


@dataclass(frozen=True)
class Client:
    slug: str
    name: str                              # short name: header, browser tab, installed app
    legal_name: str                        # printed on documents
    app_description: str
    tagline: str = ''
    motto: str = ''
    address_lines: tuple = ()
    tin: str = ''
    contacts: tuple = ()                   # (label, phone) pairs, printed on documents
    email: str = ''
    website_email: str = ''
    theme_light: dict = field(default_factory=dict)
    theme_dark: dict = field(default_factory=dict)
    theme_color: str = '#000000'           # browser/phone toolbar colour
    pdf_bar_color: str = '#1b3a5c'         # the CLIENT DETAILS bar on quotations, invoices, receipts
    features: frozenset = frozenset()
    terms: Terms = Terms()
    # Event form fields this business doesn't use (any of: 'venue', 'guest_count', 'end_date').
    hidden_event_fields: tuple = ()
    # Confirmed -> In progress -> Completed by date. Off for businesses whose jobs don't
    # end on a fixed day (a website isn't finished just because its deadline passed).
    auto_complete_events: bool = True
    # Buttons under the quotation/invoice line items that add a common line in one tap.
    quick_add_lines: tuple = ('Labor', 'Delivery & setup', 'Miscellaneous')
    # Starter chart of accounts: {code: new name} for the business's own wording.
    account_names: dict = field(default_factory=dict)

    @property
    def static_dir(self):
        return f'clients/{self.slug}'

    def __post_init__(self):
        unknown = set(self.features) - ALL_FEATURES
        if unknown:
            raise ValueError(f'{self.slug}: unknown features {sorted(unknown)}')
        for theme in (self.theme_light, self.theme_dark):
            missing = set(THEME_KEYS) - set(theme)
            if missing:
                raise ValueError(f'{self.slug}: theme is missing {sorted(missing)}')


def settings_for(profile):
    """The Django settings a profile turns into (config/settings/base.py; tests use it to switch client)."""
    contacts = list(profile.contacts)
    return {
        'CLIENT_PROFILE': profile,
        'COMPANY_NAME': profile.name,
        'COMPANY_LEGAL_NAME': profile.legal_name,
        'COMPANY_TAGLINE': profile.tagline,
        'COMPANY_MOTTO': profile.motto,
        'COMPANY_ADDRESS_LINES': list(profile.address_lines),
        'COMPANY_TIN': profile.tin,
        'COMPANY_CONTACTS': contacts,
        'COMPANY_PHONES': [phone for _, phone in contacts],
        'COMPANY_EMAIL': profile.email,
        'COMPANY_WEBSITE_EMAIL': profile.website_email,
        'COMPANY_LOGO_STATIC_PATH': f'{profile.static_dir}/logo.png',
        'COMPANY_LOGO_DARK_STATIC_PATH': f'{profile.static_dir}/logo-dark.png',
        'COMPANY_ICONS_STATIC_DIR': f'{profile.static_dir}/icons',
        'FEATURES': frozenset(profile.features),
    }


def load(slug):
    try:
        module = importlib.import_module(f'config.clients.{slug}')
    except ModuleNotFoundError as exc:
        raise RuntimeError(f'No client profile config/clients/{slug}.py (CLIENT={slug!r})') from exc
    return module.PROFILE
