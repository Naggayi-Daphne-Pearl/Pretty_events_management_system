from django import template
from django.utils.html import format_html

from core.once import FIELD_NAME, issue_token

register = template.Library()


@register.simple_tag(takes_context=True)
def once_token(context):
    """Hidden one-time token for forms that must not be submitted twice. See core.once."""
    return format_html('<input type="hidden" name="{}" value="{}">', FIELD_NAME, issue_token(context['request'].user))
