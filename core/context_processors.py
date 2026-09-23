from django.conf import settings


def branding(request):
    return {
        'COMPANY_NAME': 'Pretty Events',
        'COMPANY_LEGAL_NAME': settings.COMPANY_LEGAL_NAME,
        'COMPANY_TAGLINE': settings.COMPANY_TAGLINE,
        'COMPANY_MOTTO': settings.COMPANY_MOTTO,
        'COMPANY_ADDRESS_LINES': settings.COMPANY_ADDRESS_LINES,
        'COMPANY_TIN': settings.COMPANY_TIN,
        'COMPANY_PHONES': settings.COMPANY_PHONES,
        'COMPANY_EMAIL': settings.COMPANY_EMAIL,
        'COMPANY_WEBSITE_EMAIL': settings.COMPANY_WEBSITE_EMAIL,
        'COMPANY_LOGO_STATIC_PATH': settings.COMPANY_LOGO_STATIC_PATH,
        'CURRENCY': settings.CURRENCY,
        'EMAIL_ENABLED': settings.EMAIL_ENABLED,
    }
