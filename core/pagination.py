from django.core.paginator import Paginator

PER_PAGE_OPTIONS = (25, 50, 100)


def per_page_from(request, default):
    """?per_page=N if it's one of the allowed sizes (never an arbitrary, huge N), else default."""
    try:
        value = int(request.GET.get('per_page', ''))
    except ValueError:
        return default
    return value if value in PER_PAGE_OPTIONS else default


def paginate(request, items, per_page, param='page'):
    """Page any queryset/list by ?<param>=N; out-of-range or junk page numbers fall back safely."""
    return Paginator(items, per_page).get_page(request.GET.get(param))


class PerPageMixin:
    """ListView mixin: lets the user pick 25/50/100 rows per page via ?per_page=."""

    def get_paginate_by(self, queryset):
        return per_page_from(self.request, self.paginate_by)

    def paginate_queryset(self, queryset, page_size):
        # Django's ListView 404s on ?page=abc or a page past the end (e.g. a stale link
        # after entries were deleted). Fall back to the nearest valid page instead.
        paginator = self.get_paginator(queryset, page_size)
        page = paginator.get_page(self.request.GET.get(self.page_kwarg))
        return paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['per_page_options'] = PER_PAGE_OPTIONS
        ctx['per_page'] = self.get_paginate_by(None)
        return ctx
