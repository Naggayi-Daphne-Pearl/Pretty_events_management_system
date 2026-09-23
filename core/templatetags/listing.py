from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def has_filters(context):
    """True if the current list is narrowed by any query-string filter (paging and
    rows-per-page don't count). Lets a list tell "nothing here yet" apart from
    "nothing matches your filters"."""
    request = context.get('request')
    if request is None:
        return False
    return any(value for key, value in request.GET.items() if key != 'per_page' and not key.endswith('page'))


def _url_with(request, **changes):
    """Current URL's query string with some params replaced (None removes one)."""
    params = request.GET.copy()
    for key, value in changes.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    query = params.urlencode()
    return f'?{query}' if query else request.path


@register.simple_tag(takes_context=True)
def page_links(context, page_obj, param='page'):
    """
    Numbered page links for a Page, eliding the middle of long ranges
    (1 2 … 7 8 [9] 10 11 … 40 41). Keeps every other query param (filters,
    per_page, another list's page) so paging never drops the user's filters.
    `param` lets two paginated lists share one page (e.g. timeline_page).
    """
    request = context['request']
    paginator = page_obj.paginator
    links = []
    for number in paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1):
        if number == paginator.ELLIPSIS:
            links.append({'gap': True})
        else:
            links.append({'number': number, 'current': number == page_obj.number,
                          'url': _url_with(request, **{param: number})})
    return {
        'links': links,
        'previous_url': _url_with(request, **{param: page_obj.previous_page_number()}) if page_obj.has_previous() else '',
        'next_url': _url_with(request, **{param: page_obj.next_page_number()}) if page_obj.has_next() else '',
    }


@register.simple_tag(takes_context=True)
def per_page_query_fields(context, param='page'):
    """(name, value) pairs of the current filters, minus paging, for the rows-per-page form."""
    request = context['request']
    return [(k, v) for k, v in request.GET.items() if k not in (param, 'per_page')]
