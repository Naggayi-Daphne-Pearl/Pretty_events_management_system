from . import Client

# Real business details, as printed on Pretty Events' physical receipt book.
# NOTE: transcribed from a photo of the receipt book; double-check the TIN and
# phone numbers against the original before relying on these for anything official.
PROFILE = Client(
    slug='pretty_events',
    name='Pretty Events',
    legal_name='PRETTY EVENTS LTD.',
    app_description='Bookings, billing, equipment and staff for Pretty Events.',
    tagline='EVENTS MANAGEMENT & TENT HIRE',
    motto='Your Happiness Is Our Passion',
    address_lines=('Kiwatule Stage &', 'Kira Bulindo Road'),
    tin='1004479551',
    # Named contact numbers for the CONTACTS box (as supplied by the client, 2026-09-24).
    contacts=(
        ('James', '0772 682 448'),
        ('Rukiah', '0704 316 745'),
        ('Office line', '0393 254 159'),
    ),
    email='prettyevents5@gmail.com',
    website_email='info@prettyeventslimited.co.ug',
    # From the logo: navy (PRETTY) leads, orange (EVENTS / centre tent) accents,
    # sky blue (side tents) for small touches.
    theme_light={
        'primary': '#2B3490', 'primary-hover': '#222a78', 'primary-text': '#2B3490',
        'primary-soft': 'rgba(43,52,144,0.08)', 'on-primary': '#ffffff',
        'accent': '#E8681F', 'accent-text': '#B9500F', 'accent-soft': 'rgba(232,104,31,0.18)',
        'sky': '#00A8E8',
    },
    theme_dark={
        'primary': '#3D47C2', 'primary-hover': '#4954d6', 'primary-text': '#A9B0FF',
        'primary-soft': 'rgba(140,150,255,0.16)', 'on-primary': '#ffffff',
        'accent': '#F27A36', 'accent-text': '#F79A5E', 'accent-soft': 'rgba(242,122,54,0.24)',
        'sky': '#3CC4F5',
    },
    theme_color='#2B3490',
    pdf_bar_color='#1b3a5c',
    features=frozenset({'inventory'}),
)
