"""
Emailing a quotation, invoice or receipt PDF: render it, send it, record it.

This runs as a Django task. With the default ImmediateBackend it runs inside the
request, exactly as before. With TASK_WORKER_ENABLED=True it is queued in the
database and a separate `manage.py db_worker` process sends it, so a slow mail
server can't hold a web worker past gunicorn's timeout.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.tasks import TaskResultStatus, task
from django.template.loader import render_to_string

from comms.models import CommunicationLog
from core.context_processors import branding
from core.emailing import send_pdf_email
from core.models import ActivityLog
from core.utils import amount_in_words

from .models import Invoice, Quotation, Receipt


def document_for(kind, pk):
    model = {'quotation': Quotation, 'invoice': Invoice, 'receipt': Receipt}[kind]
    return model.objects.get(pk=pk)


def pdf_context(document):
    kind = document._meta.model_name
    if kind == 'receipt':
        return {'receipt': document, 'amount_in_words': amount_in_words(document.payment.amount)}
    return {kind: document}


def render_document_pdf(document):
    """PDF bytes for a document outside a request, or None without WeasyPrint's native libs."""
    template = f'pdf/{document._meta.model_name}_pdf.html'
    html = render_to_string(template, {**branding(None), **pdf_context(document)})
    try:
        from weasyprint import HTML
        return HTML(string=html, base_url=f'file://{settings.BASE_DIR}/').write_pdf()
    except (ImportError, OSError):
        return None


def event_of(document):
    return document.payment.invoice.event if isinstance(document, Receipt) else document.event


@task
def email_document(kind, pk, to_email, body, user_id=None):
    """Returns True when sent. Success and failure both land in the logs staff can see."""
    document = document_for(kind, pk)
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    label = document._meta.verbose_name
    sent = send_pdf_email(
        to_email=to_email,
        subject=f'{label.capitalize()} {document.number} from {settings.COMPANY_LEGAL_NAME}',
        body=body,
        pdf_bytes=render_document_pdf(document),
        filename=f'{document.number}.pdf',
    )
    if not sent:
        ActivityLog.objects.create(
            actor=user, action=f'{kind}.email_failed',
            description=f'Emailing {label} "{document}" to {to_email} failed (mail server unreachable or refused)',
        )
        return False

    if kind == 'quotation' and document.status == Quotation.Status.DRAFT:
        document.status = Quotation.Status.SENT
        document.save(update_fields=['status'])
    event = event_of(document)
    CommunicationLog.objects.create(
        customer=event.customer, event=event,
        channel=CommunicationLog.Channel.EMAIL, direction=CommunicationLog.Direction.OUTBOUND,
        message=f'Emailed {label} {document.number} to {to_email}', logged_by=user,
    )
    ActivityLog.objects.create(
        actor=user, action=f'{kind}.emailed', description=f'Emailed {label} "{document}" to {to_email}',
    )
    return True


def send_or_queue(request, document, to_email, body):
    """
    Hand the email to the task backend. Returns 'sent', 'queued' or 'failed' so the
    view can tell the user what happened.
    """
    result = email_document.enqueue(
        document._meta.model_name, document.pk, to_email, body,
        request.user.pk if request.user.is_authenticated else None,
    )
    if not result.is_finished:
        return 'queued'
    return 'sent' if result.status == TaskResultStatus.SUCCESSFUL and result.return_value else 'failed'
