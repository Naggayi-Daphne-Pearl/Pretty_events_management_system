from collections import OrderedDict

from django.contrib.auth.models import Permission

# The apps whose permissions are meaningful business-role checkboxes. Deliberately
# excludes Django's own internal apps (auth, admin, contenttypes, sessions) — a
# business role has no business ticking "can add content type".
MANAGEABLE_APPS = OrderedDict([
    ('customers', 'Customers'),
    ('events', 'Events'),
    ('billing', 'Quotations, Invoices & Payments'),
    ('inventory', 'Inventory'),
    ('finance', 'Finance'),
    ('staffing', 'Staff'),
    ('comms', 'Communication'),
    ('accounting', 'Accounting'),
])

# Line items are only ever edited inline through their parent (quotation/invoice)
# formset, never permission-checked on their own — hide them from the checklist.
HIDDEN_MODELS = {'quotationlineitem', 'invoicelineitem', 'journalline'}

ACTION_ORDER = {'view': 0, 'add': 1, 'change': 2, 'delete': 3}


def grouped_permissions():
    """
    All manageable permissions, grouped by app then by model, for rendering as a
    checklist. Each model's permissions are ordered view/add/change/delete first,
    with any custom permission (e.g. 'view_assigned_events_only') listed last.
    """
    permissions = (
        Permission.objects.filter(content_type__app_label__in=MANAGEABLE_APPS)
        .exclude(content_type__model__in=HIDDEN_MODELS)
        .select_related('content_type')
    )

    by_app = OrderedDict((app_label, OrderedDict()) for app_label in MANAGEABLE_APPS)
    for perm in permissions:
        app_label = perm.content_type.app_label
        model = perm.content_type.model
        by_app[app_label].setdefault(model, []).append(perm)

    def sort_key(perm):
        action = perm.codename.split('_', 1)[0]
        return ACTION_ORDER.get(action, 99)

    groups = []
    for app_label, app_display in MANAGEABLE_APPS.items():
        models = by_app.get(app_label) or {}
        if not models:
            continue
        model_groups = []
        for model, perms in models.items():
            perms.sort(key=sort_key)
            model_groups.append({
                'model': model,
                'display_name': perms[0].content_type.name.title() if perms else model,
                'permissions': perms,
            })
        groups.append({'app_label': app_label, 'display_name': app_display, 'models': model_groups})
    return groups


def restricted_to_own_events(user):
    """
    True if this user's role should only ever see events they're personally
    assigned to. Driven entirely by the 'events.view_assigned_events_only'
    permission — tick it on any (dynamically named/created) group in Django
    admin to scope that role this way, rather than hardcoding a role name.
    """
    return user.has_perm('events.view_assigned_events_only') and not user.is_superuser


def scope_events_to_assignments(queryset, user):
    if restricted_to_own_events(user):
        return queryset.filter(assignments__staff_member__user=user).distinct()
    return queryset
