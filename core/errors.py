from django.conf import settings
from django.http import HttpResponseServerError
from django.template import loader


def server_error(request):
    """Django's 500 handler, plus the business name and colours. Uses no context
    processors or database, since those may be what failed."""
    try:
        theme = settings.CLIENT_PROFILE.theme_dark
        context = {'name': settings.COMPANY_NAME, 'primary': theme['primary'],
                   'primary_text': theme['primary-text'], 'accent': theme['accent']}
    except Exception:
        context = {}
    return HttpResponseServerError(loader.get_template('500.html').render(context))
