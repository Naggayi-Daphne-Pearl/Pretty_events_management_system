from django import template

register = template.Library()


@register.filter
def person_name(user):
    """
    The name to print for a user on documents: their staff record's full name if they
    have one, else the name on their account, else their email or username. Logins are
    created from an email address, so the account itself often has no first/last name.
    """
    if not user:
        return ''
    profile = getattr(user, 'staff_profile', None)
    if profile and profile.full_name:
        return profile.full_name
    return user.get_full_name() or user.email or user.username
