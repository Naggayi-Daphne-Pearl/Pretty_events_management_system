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
