"""
Signed links that let a client open one quotation, invoice or receipt PDF without
logging in, e.g. from the WhatsApp message staff send. A link names exactly one
document, can't be altered to point at another, and stops working after
SHARE_LINK_DAYS. The server's SECRET_KEY signs it, so rotating that key revokes
every outstanding link.
"""
from django.conf import settings
from django.core import signing
from django.urls import reverse

SALT = 'billing.share-document'
KINDS = ('quotation', 'invoice', 'receipt')


def share_token(document):
    return signing.dumps([document._meta.model_name, document.pk], salt=SALT, compress=True)


def share_url(request, document):
    return request.build_absolute_uri(reverse('billing:shared_document', args=[share_token(document)]))


def read_token(token):
    """(kind, pk) for a valid, unexpired token, else None."""
    try:
        kind, pk = signing.loads(token, salt=SALT, max_age=settings.SHARE_LINK_DAYS * 24 * 60 * 60)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    return (kind, pk) if kind in KINDS else None
