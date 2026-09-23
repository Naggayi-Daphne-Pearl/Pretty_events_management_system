"""
Base Django settings for Pretty Events, shared by dev and production.
All secrets/environment-specific values come from env vars (see .env.example).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-env')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    'core',
    'customers',
    'events',
    'billing',
    'inventory',
    'finance',
    'staffing',
    'comms',
    'reports',
    'accounting',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.auth.SessionMaxAgeMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.branding',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = env('TIME_ZONE', default='Africa/Kampala')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
# Brand assets (logo, etc.) live under assets/ at the repo root; expose them to
# {% static %} without duplicating the files into a separate static/ folder.
STATICFILES_DIRS = [BASE_DIR / 'assets']

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Staff log in with their email address (username still accepted for old admin accounts).
AUTHENTICATION_BACKENDS = ['core.auth.EmailBackend']

# Sessions expire after 30 minutes of inactivity; each request resets the clock...
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# ...and never last longer than this from login, however active (core.auth.SessionMaxAgeMiddleware).
SESSION_MAX_AGE_HOURS = env.int('SESSION_MAX_AGE_HOURS', default=12)

# Lock an email out of logging in for a while after this many wrong passwords.
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15

# Password reset and staff invite links stop working after this long (and once used).
PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60

# Single currency for Phase 1 (confirmed default: UGX only, no multi-currency).
CURRENCY = 'UGX'

# Country code assumed for locally-typed phone numbers (e.g. 0772...) when building
# WhatsApp click-to-chat and call links. Numbers typed with +/00 keep their own.
DEFAULT_PHONE_COUNTRY_CODE = '256'

# Real business details, as printed on Pretty Events' physical receipt book —
# used on the branded quotation/invoice/receipt PDFs and in the app header.
# NOTE: transcribed from a photo of the receipt book; double-check the TIN and
# phone numbers against the original before relying on these for anything official.
COMPANY_LEGAL_NAME = 'PRETTY EVENTS LTD.'
COMPANY_TAGLINE = 'EVENTS MANAGEMENT & TENT HIRE'
COMPANY_MOTTO = 'Your Happiness Is Our Passion'
COMPANY_ADDRESS_LINES = ['Kiwatule Stage &', 'Kira Bulindo Road']
COMPANY_TIN = '1004479551'
COMPANY_PHONES = ['+256 393 254 159', '+256 772 682 448', '+256 703 492 505']
COMPANY_EMAIL = 'prettyevents5@gmail.com'
COMPANY_WEBSITE_EMAIL = 'info@prettyeventslimited.co.ug'
COMPANY_LOGO_STATIC_PATH = 'branding/pretty-events-logo.png'

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=COMPANY_EMAIL)
# Give up on an unreachable mail server well inside gunicorn's 30s worker timeout, so the
# user gets "could not send" (and can retry) instead of the request being killed mid-send.
EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=15)

# Railway's trial/hobby plans block outgoing SMTP, so production sends through Brevo's
# HTTPS API instead. Setting BREVO_API_KEY switches the backend automatically; the
# SMTP settings above stay as the fallback (e.g. local dev or a plan that allows SMTP).
# DEFAULT_FROM_EMAIL must be a sender verified in Brevo.
BREVO_API_KEY = env('BREVO_API_KEY', default='')
if BREVO_API_KEY:
    EMAIL_BACKEND = 'anymail.backends.brevo.EmailBackend'
    ANYMAIL = {
        'BREVO_API_KEY': BREVO_API_KEY,
        'REQUESTS_TIMEOUT': EMAIL_TIMEOUT,  # stay inside gunicorn's 30s worker timeout
    }

# Send warnings and errors (including full tracebacks for 500s) to stdout/stderr so they
# show up in Railway's deploy logs. Without this, Django's default config only emails
# errors to ADMINS when DEBUG is off, and with no ADMINS set they were silently lost.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'plain': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'},
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': env('DJANGO_LOG_LEVEL', default='WARNING'), 'propagate': False},
    },
}
