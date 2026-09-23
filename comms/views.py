from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from billing.models import Invoice, Quotation, Receipt
from core.activity import log_model_activity
from core.deletion import confirm_and_delete
from core.pagination import PerPageMixin
from customers.models import Customer

from .forms import CommunicationLogForm
from .models import CommunicationLog
from .outreach import call_url, default_message, email_url, whatsapp_url


class ExternalAppRedirect(HttpResponseRedirect):
    """Django's redirect only allows http/https/ftp; these hand off to the phone
    dialer / mail client, so tel: and mailto: are needed too."""
    allowed_schemes = ['https', 'tel', 'mailto']


class CommunicationLogListView(LoginRequiredMixin, PermissionRequiredMixin, PerPageMixin, ListView):
    model = CommunicationLog
    permission_required = 'comms.view_communicationlog'
    paginate_by = 25
    template_name = 'comms/log_list.html'

    def get_queryset(self):
        qs = super().get_queryset().select_related('customer', 'event', 'logged_by')
        channel = self.request.GET.get('channel')
        if channel:
            qs = qs.filter(channel=channel)
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(customer__name__icontains=q) | Q(message__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['channel'] = self.request.GET.get('channel', '')
        ctx['channels'] = CommunicationLog.Channel.choices
        return ctx


def _customer_event(customer, raw_pk):
    """The customer's own event with this id, or None (ignores junk/foreign ids)."""
    return customer.events.filter(pk=raw_pk).first() if str(raw_pk or '').isdigit() else None


def _safe_next(request, fallback):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return fallback


@login_required
@permission_required('comms.add_communicationlog', raise_exception=True)
def log_create(request, customer_pk):
    customer = get_object_or_404(Customer, pk=customer_pk)
    event = _customer_event(customer, request.GET.get('event') or request.POST.get('event'))
    back_url = _safe_next(request, event.get_absolute_url() if event else customer.get_absolute_url())
    if request.method == 'POST':
        form = CommunicationLogForm(request.POST, customer=customer)
        if form.is_valid():
            log = form.save(commit=False)
            log.customer = customer
            log.logged_by = request.user
            log.save()
            log_model_activity(request, log, 'created', extra=f'with customer "{customer}"')
            messages.success(request, 'Communication logged.')
            return redirect(back_url)
    else:
        form = CommunicationLogForm(customer=customer, initial={'event': event})
    return render(request, 'comms/log_form.html', {'form': form, 'customer': customer, 'back_url': back_url})


@login_required
@permission_required('comms.change_communicationlog', raise_exception=True)
def log_update(request, pk):
    log = get_object_or_404(CommunicationLog.objects.select_related('customer'), pk=pk)
    back_url = _safe_next(request, log.customer.get_absolute_url())
    if request.method == 'POST':
        form = CommunicationLogForm(request.POST, instance=log, customer=log.customer)
        if form.is_valid():
            form.save()
            log_model_activity(request, log, 'updated', extra=f'with customer "{log.customer}"')
            messages.success(request, 'Communication log updated.')
            return redirect(back_url)
    else:
        form = CommunicationLogForm(instance=log, customer=log.customer)
    return render(request, 'comms/log_form.html', {
        'form': form, 'customer': log.customer, 'object': log, 'back_url': back_url,
    })


@login_required
@permission_required('comms.delete_communicationlog', raise_exception=True)
def log_delete(request, pk):
    log = get_object_or_404(CommunicationLog.objects.select_related('customer'), pk=pk)
    return confirm_and_delete(
        request, log,
        cancel_url=log.customer.get_absolute_url(),
        success_url=log.customer.get_absolute_url(),
    )


def _resolve_document(customer, value):
    """'invoice:12' / 'quotation:3' / 'receipt:7' -> that document, only if it belongs to this customer."""
    kind, _, pk = (value or '').partition(':')
    if not pk.isdigit():
        return None
    if kind == 'receipt':
        return (Receipt.objects.select_related('payment__invoice__event')
                .filter(pk=pk, payment__invoice__event__customer=customer).first())
    model = {'invoice': Invoice, 'quotation': Quotation}.get(kind)
    if not model:
        return None
    return model.objects.select_related('event').filter(pk=pk, event__customer=customer).first()


def _document_event(document):
    return document.payment.invoice.event if isinstance(document, Receipt) else document.event


@require_POST
@login_required
@permission_required('comms.add_communicationlog', raise_exception=True)
def contact_customer(request, customer_pk, channel):
    """
    Starts a WhatsApp chat, phone call or email with the customer and logs it in
    the same step, so the Communication Log stays complete without staff having
    to remember to fill it in afterwards. POST-only so link prefetching or a
    crawler can never create log entries. The message text is built here from
    the record, not taken from the browser.
    """
    customer = get_object_or_404(Customer, pk=customer_pk)
    document = _resolve_document(customer, request.POST.get('document'))
    event = _document_event(document) if document else _customer_event(customer, request.POST.get('event'))
    text = default_message(customer, event=event, document=document)

    if channel == CommunicationLog.Channel.WHATSAPP:
        target = whatsapp_url(customer.phone, text)
        note = f'Started a WhatsApp chat from the app: "{text}"'
    elif channel == CommunicationLog.Channel.CALL:
        target = call_url(customer.phone)
        note = f'Called {customer.phone} from the app'
    elif channel == CommunicationLog.Channel.EMAIL:
        subject = f'{settings.COMPANY_LEGAL_NAME}: {document.number}' if document else settings.COMPANY_LEGAL_NAME
        target = email_url(customer.email, subject, text)
        note = f'Started an email to {customer.email} from the app'
    else:
        raise Http404

    if not target:
        messages.error(request, f'{customer.name} has no {"email address" if channel == "email" else "phone number"} on file.')
        return redirect(_safe_next(request, customer.get_absolute_url()))

    if document:
        note += f' (about {document._meta.verbose_name} {document.number})'
    log = CommunicationLog.objects.create(
        customer=customer, event=event, channel=channel,
        direction=CommunicationLog.Direction.OUTBOUND, message=note, logged_by=request.user,
    )
    log_model_activity(request, log, 'created', extra=f'with customer "{customer}"')
    return ExternalAppRedirect(target)
