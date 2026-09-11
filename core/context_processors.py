from django.conf import settings


def branding(request):
    return {
        'COMPANY_NAME': 'Pretty Events',
        'CURRENCY': settings.CURRENCY,
    }
