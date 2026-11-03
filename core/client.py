"""
This deployment's client profile (config/clients/), as the rest of the app uses it:
which optional modules are on, and what the business calls things.
"""
import re

from django.conf import settings
from django.http import Http404


def feature_enabled(name):
    return name in settings.FEATURES


def features():
    """{'inventory': True, ...} for templates: {% if FEATURES.inventory %}."""
    return {name: True for name in settings.FEATURES}


def terms():
    """The business's words: terms()['Event'] is 'Event' or 'Project', and so on."""
    return settings.CLIENT_PROFILE.terms.as_context()


def term(key):
    return terms()[key]


_WORDS = re.compile(r'\b(events?|Events?|EVENTS?|customers?|Customers?|CUSTOMERS?)\b')


def reword(text):
    """
    Fixed wording written for an events business, in this business's words: swaps the
    nouns event(s)/customer(s) for terms(), keeping their case ('Can view customer' ->
    'Can view client'). Whole phrases such as 'Event date' need their own term. A no-op
    for businesses that use the default terms.
    """
    if not text:
        return text
    words = terms()

    def swap(match):
        found = match.group(0)
        word = words[found.lower()]
        if found.isupper():
            return word.upper()
        if found[0].isupper():
            return word[:1].upper() + word[1:]
        return word
    return _WORDS.sub(swap, str(text))


def event_field_hidden(name):
    return name in settings.CLIENT_PROFILE.hidden_event_fields


# URL namespaces and pages that belong to an optional module. FeatureGateMiddleware
# answers 404 for them when the module is off, so no view needs its own check.
FEATURE_PAGES = {
    'inventory': {
        'namespaces': ('inventory',),
        'pages': ('events:job', 'events:packing_list', 'reports:inventory_summary'),
    },
    'subscriptions': {
        'namespaces': ('subscriptions',),
        'pages': (),
    },
}


class FeatureGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None:
            return None
        page = f'{match.namespace}:{match.url_name}'
        for feature, owned in FEATURE_PAGES.items():
            if feature_enabled(feature):
                continue
            if match.namespace in owned['namespaces'] or page in owned['pages']:
                raise Http404
        return None
