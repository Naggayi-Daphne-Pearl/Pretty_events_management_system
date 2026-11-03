from django import template

from core.client import reword as reword_text

register = template.Library()


@register.filter
def reword(text):
    """Fixed text in the business's own words: {{ "Assign them to events."|reword }} (see core.client.reword)."""
    return reword_text(text)
