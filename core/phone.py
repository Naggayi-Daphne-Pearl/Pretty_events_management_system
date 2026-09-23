import re

from django.conf import settings


def to_international(phone):
    """
    Normalise a locally-typed phone number into international digits with no
    '+' (the format wa.me links need), e.g. '0772 123 456' -> '256772123456'.
    Numbers already typed with a '+' or '00' prefix keep their own country code.
    Returns '' if there are no digits at all.
    """
    raw = (phone or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    country_code = settings.DEFAULT_PHONE_COUNTRY_CODE
    if raw.startswith('+'):
        return digits
    if digits.startswith('00'):
        return digits[2:]
    if digits.startswith(country_code) and len(digits) > 9:
        return digits
    if digits.startswith('0'):
        return country_code + digits[1:]
    if len(digits) == 9:
        return country_code + digits
    return digits
