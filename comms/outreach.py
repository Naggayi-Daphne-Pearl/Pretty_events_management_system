from urllib.parse import quote, urlencode

from django.conf import settings

from core.phone import to_international


def _money(amount):
    return f'{settings.CURRENCY} {amount:,.0f}'


def default_message(customer, event=None, document=None):
    """The pre-filled text for a WhatsApp chat / email started from the app.
    `document` is a Quotation, Invoice or Receipt (or None)."""
    greeting = f'Hello {customer.name}, this is {settings.COMPANY_LEGAL_NAME}.'
    if document is not None and document._meta.model_name == 'receipt':
        payment = document.payment
        invoice = payment.invoice
        text = (greeting + f' Thank you for your payment of {_money(payment.amount)} received on '
                f'{payment.paid_at:%d %b %Y}. Your receipt number is {document.number}.')
        if invoice.balance_due > 0:
            text += f' Remaining balance on invoice {invoice.number}: {_money(invoice.balance_due)}.'
        else:
            text += f' Invoice {invoice.number} is now fully paid.'
        return text + ' Thank you.'
    if document is not None:
        event = document.event
        kind = document._meta.verbose_name
        about = f' We are following up on {kind} {document.number} for your {event.event_type} on {event.event_date:%d %b %Y}.'
        amounts = f' Total: {_money(document.total)}.'
        if hasattr(document, 'balance_due') and document.balance_due > 0:
            amounts += f' Balance due: {_money(document.balance_due)}.'
        return greeting + about + amounts + ' Thank you.'
    if event is not None:
        return greeting + f' We are getting in touch about your {event.event_type} on {event.event_date:%d %b %Y}.'
    return greeting


def whatsapp_url(phone, text):
    number = to_international(phone)
    if not number:
        return ''
    return f'https://wa.me/{number}?{urlencode({"text": text}, quote_via=quote)}'


def call_url(phone):
    number = to_international(phone)
    return f'tel:+{number}' if number else ''


def email_url(email, subject, body):
    if not email:
        return ''
    return f'mailto:{quote(email)}?{urlencode({"subject": subject, "body": body}, quote_via=quote)}'
