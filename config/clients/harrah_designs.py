from . import Client, Terms

# Harrah Designs builds websites for clients. Their jobs are projects with a deadline,
# not dated events, they hold no hire equipment, and much of their income repeats
# (hosting, domains, maintenance retainers).
# TODO before go-live: confirm the legal name, TIN, address, phone numbers and emails.
PROFILE = Client(
    slug='harrah_designs',
    name='Harrah Designs',
    legal_name='HARRAH DESIGNS',
    app_description='Clients, projects, billing and renewals for Harrah Designs.',
    tagline='WEBSITE DESIGN & DEVELOPMENT',
    address_lines=(),
    contacts=(),
    email='',
    # From the logo: red leads, near-black for contrast.
    theme_light={
        'primary': '#D7262C', 'primary-hover': '#B91F24', 'primary-text': '#C21F25',
        'primary-soft': 'rgba(215,38,44,0.08)', 'on-primary': '#ffffff',
        'accent': '#1F1F24', 'accent-text': '#B91F24', 'accent-soft': 'rgba(31,31,36,0.12)',
        'sky': '#6B6B76',
    },
    theme_dark={
        'primary': '#E5383B', 'primary-hover': '#F04B4E', 'primary-text': '#FF8A8C',
        'primary-soft': 'rgba(255,90,93,0.16)', 'on-primary': '#ffffff',
        'accent': '#4A4A54', 'accent-text': '#FF8A8C', 'accent-soft': 'rgba(255,255,255,0.14)',
        'sky': '#A0A0AA',
    },
    theme_color='#D7262C',
    pdf_bar_color='#1F1F24',
    features=frozenset({'subscriptions'}),
    terms=Terms(
        event='project',
        event_type_help='e.g. Business website, Online shop, Redesign, Maintenance',
        event_date='Start date',
        end_date='Deadline',
        end_date_help='When the site should go live',
        customer='client',
    ),
    hidden_event_fields=('venue', 'guest_count'),
    auto_complete_events=False,
    quick_add_lines=('Website design', 'Development', 'Hosting (1 year)', 'Domain (1 year)', 'Maintenance'),
    account_names={
        '1500': 'Computers & Equipment',
        '1510': 'Office Furniture',
        '4000': 'Website Design & Development Income',
        '4100': 'Hosting, Domains & Maintenance Income',
        '5000': 'Freelancers & Contractors',
        '5010': 'Hosting & Domain Costs',
        '5020': 'Software & Plugin Licences',
        '5030': 'Stock Photos & Assets',
    },
)
