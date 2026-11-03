from django.conf import settings


from .client import features, terms


def branding(request):
    profile = settings.CLIENT_PROFILE
    return {
        'COMPANY_NAME': settings.COMPANY_NAME,
        'COMPANY_LEGAL_NAME': settings.COMPANY_LEGAL_NAME,
        'COMPANY_TAGLINE': settings.COMPANY_TAGLINE,
        'COMPANY_MOTTO': settings.COMPANY_MOTTO,
        'COMPANY_ADDRESS_LINES': settings.COMPANY_ADDRESS_LINES,
        'COMPANY_TIN': settings.COMPANY_TIN,
        'COMPANY_PHONES': settings.COMPANY_PHONES,
        'COMPANY_CONTACTS': settings.COMPANY_CONTACTS,
        'COMPANY_EMAIL': settings.COMPANY_EMAIL,
        'COMPANY_WEBSITE_EMAIL': settings.COMPANY_WEBSITE_EMAIL,
        'COMPANY_LOGO_STATIC_PATH': settings.COMPANY_LOGO_STATIC_PATH,
        'COMPANY_LOGO_DARK_STATIC_PATH': settings.COMPANY_LOGO_DARK_STATIC_PATH,
        'COMPANY_ICONS_STATIC_DIR': settings.COMPANY_ICONS_STATIC_DIR,
        'THEME_LIGHT': profile.theme_light,
        'THEME_DARK': profile.theme_dark,
        'THEME_COLOR': profile.theme_color,
        'PDF_BAR_COLOR': profile.pdf_bar_color,
        'FEATURES': features(),
        'T': terms(),
        'QUICK_ADD_LINES': profile.quick_add_lines,
        'HIDDEN_EVENT_FIELDS': {name: True for name in profile.hidden_event_fields},
        'CURRENCY': settings.CURRENCY,
        'EMAIL_ENABLED': settings.EMAIL_ENABLED,
    }


def navigation(request):
    """Sidebar, tabs, "+ New" menu and phone bar for the signed-in user (see core.navigation)."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    from django.utils.functional import SimpleLazyObject

    from .navigation import build
    from .notifications import for_user
    context = build(request)
    # Only worked out if the page shows the bell.
    context['notifications'] = SimpleLazyObject(lambda: for_user(request.user))
    return context
