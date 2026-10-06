from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.activity import log_activity, log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.emailing import email_enabled_required
from core.once import claim_token
from core.pagination import paginate
from core.utils import amount_in_words
from events.models import Event
from inventory.models import EquipmentItem
from inventory.services import availability_for_event, warn_if_short

from .forms import (
    EmailDocumentForm, InvoiceForm, InvoiceLineItemFormSet, PaymentForm, QuotationForm, QuotationLineItemFormSet,
    TaxGroupForm,
)
from . import mobile_money
from .models import Invoice, MobileMoneyTransaction, Payment, Quotation, Receipt, TaxGroup
from .services import record_payment, sync_invoice_statuses
from .sharing import read_token
from .tasks import send_or_queue


def equipment_items_json(event=None):
    """Feeds the line-item table's "pick an inventory item" auto-fill JS —
    see quotation_form.html / invoice_form.html. With an event, "available" is what
    is free on the event's dates after other confirmed bookings, not just today."""
    items = EquipmentItem.objects.with_availability()
    if event is None:
        return {
            str(item.pk): {
                'name': item.name,
                'rate': str(item.default_rate) if item.default_rate is not None else '',
                'available': item.available_quantity,
                'unit': item.unit,
                'when': 'right now',
            }
            for item in items
        }
    free = availability_for_event(event)
    when = 'on this event\'s dates'
    return {
        str(item.pk): {
            'name': item.name,
            'rate': str(item.default_rate) if item.default_rate is not None else '',
            'available': max(free.get(item.pk, item.total_quantity), 0),
            'unit': item.unit,
            'when': when,
        }
        for item in items
    }


def generate_pdf_bytes(request, template_name, context):
    """Returns rendered PDF bytes, or None if WeasyPrint's native deps aren't installed."""
    # Render context processors (branding, currency, etc.) into the PDF template too.
    html_string = render_to_string(template_name, context, request=request)
    try:
        from weasyprint import HTML
        # Resolve relative asset paths (e.g. the logo) straight off disk rather than
        # over HTTP — avoids a request-fetching-itself deadlock on the dev server.
        return HTML(string=html_string, base_url=f'file://{settings.BASE_DIR}/').write_pdf()
    except (ImportError, OSError):
        return None


def render_pdf(request, template_name, context, filename):
    pdf_bytes = generate_pdf_bytes(request, template_name, context)
    if pdf_bytes is None:
        # WeasyPrint's native deps (pango/cairo) aren't installed on this machine —
        # fall back to plain HTML so the document is still viewable/printable.
        html_string = render_to_string(template_name, context, request=request)
        return HttpResponse(html_string)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ---------- Quotations ----------

class QuotationListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Quotation
    permission_required = 'billing.view_quotation'
    paginate_by = 25
    template_name = 'billing/quotation_list.html'

    def get_queryset(self):
        qs = super().get_queryset().select_related('event__customer')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status'] = self.request.GET.get('status', '')
        ctx['statuses'] = Quotation.Status.choices
        return ctx


class QuotationDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Quotation
    permission_required = 'billing.view_quotation'
    template_name = 'billing/quotation_detail.html'


@login_required
@permission_required('billing.add_quotation', raise_exception=True)
def quotation_create(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    quotation = Quotation(event=event, created_by=request.user)
    if request.method == 'POST':
        form = QuotationForm(request.POST, instance=quotation)
        formset = QuotationLineItemFormSet(request.POST, instance=quotation, prefix='line_items')
        # Check the lines too before saving anything, so a rejected form never leaves
        # an empty quotation behind.
        form_ok = form.is_valid()
        if formset.is_valid() and form_ok:
            with transaction.atomic():
                quotation = form.save()
                formset.instance = quotation
                formset.save()
            log_model_activity(request, quotation, 'created', extra=f'for event "{event}"')
            if event.advance_status_at_least(Event.Status.QUOTED):
                messages.info(request, f'Event status advanced to "{event.get_status_display()}".')
            messages.success(request, f'Quotation {quotation.number} created.')
            return redirect('billing:quotation_detail', pk=quotation.pk)
    else:
        form = QuotationForm(instance=quotation)
        formset = QuotationLineItemFormSet(instance=quotation, prefix='line_items')
    return render(request, 'billing/quotation_form.html', {
        'form': form, 'formset': formset, 'event': event, 'equipment_items': equipment_items_json(event),
    })


@login_required
@permission_required('billing.change_quotation', raise_exception=True)
def quotation_update(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.has_invoice:
        # Once converted, the invoice is the working document: editing the quotation too
        # would leave two versions that disagree. The quotation stays as the record of the offer.
        messages.info(request, f'{quotation.number} was converted to invoice {quotation.invoice.number}, '
                               'so it can no longer be edited. Make changes on the invoice instead.')
        return redirect('billing:quotation_detail', pk=quotation.pk)
    if request.method == 'POST':
        form = QuotationForm(request.POST, instance=quotation)
        formset = QuotationLineItemFormSet(request.POST, instance=quotation, prefix='line_items')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            log_model_activity(request, quotation, 'updated')
            messages.success(request, f'Quotation {quotation.number} updated.')
            return redirect('billing:quotation_detail', pk=quotation.pk)
    else:
        form = QuotationForm(instance=quotation)
        formset = QuotationLineItemFormSet(instance=quotation, prefix='line_items')
    return render(request, 'billing/quotation_form.html', {
        'form': form, 'formset': formset, 'event': quotation.event, 'object': quotation,
        'equipment_items': equipment_items_json(quotation.event),
    })


@login_required
@permission_required('billing.delete_quotation', raise_exception=True)
def quotation_delete(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.has_invoice:
        messages.warning(request, f'{quotation.number} already has an invoice and can\'t be deleted — cancel the invoice instead if this booking fell through.')
        return redirect('billing:quotation_detail', pk=quotation.pk)
    if request.method == 'POST':
        event = quotation.event
        number = quotation.number
        quotation.delete()
        log_activity(request, 'quotation.deleted', f'Deleted quotation "{number}" for event "{event}"')
        messages.success(request, f'Quotation {number} deleted.')
        return redirect('events:detail', pk=event.pk)
    return render(request, 'billing/quotation_confirm_delete.html', {'object': quotation})


@login_required
@permission_required('billing.add_invoice', raise_exception=True)
def quotation_convert(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.has_invoice:
        messages.warning(request, 'This quotation already has an invoice.')
        return redirect('billing:invoice_detail', pk=quotation.invoice.pk)
    invoice = Invoice.create_from_quotation(quotation, created_by=request.user)
    quotation.status = Quotation.Status.APPROVED
    quotation.save(update_fields=['status'])
    log_model_activity(request, invoice, 'created', extra=f'from quotation {quotation.number}')
    if quotation.event.advance_status_at_least(Event.Status.CONFIRMED):
        messages.info(request, f'Event status advanced to "{quotation.event.get_status_display()}".')
        warn_if_short(request, quotation.event)
    messages.success(request, f'Invoice {invoice.number} created from {quotation.number}.')
    return redirect('billing:invoice_detail', pk=invoice.pk)


@login_required
@permission_required('billing.view_quotation', raise_exception=True)
def quotation_pdf(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    return render_pdf(request, 'pdf/quotation_pdf.html', {'quotation': quotation}, f'{quotation.number}.pdf')


@email_enabled_required
@login_required
@permission_required('billing.change_quotation', raise_exception=True)
def quotation_email(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    customer = quotation.event.customer
    if request.method == 'POST':
        form = EmailDocumentForm(request.POST)
        if form.is_valid():
            if not claim_token(request):
                messages.info(request, 'That email was already sent. It was not sent again.')
                return redirect('billing:quotation_detail', pk=quotation.pk)
            to_email = form.cleaned_data['to_email']
            outcome = send_or_queue(request, quotation, to_email, form.cleaned_data['message'])
            if outcome == 'failed':
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/quotation_email_form.html', {'form': form, 'object': quotation})
            if outcome == 'queued':
                messages.success(request, f'Quotation {quotation.number} is being emailed to {to_email}. It shows in the Communication log once sent.')
            else:
                messages.success(request, f'Quotation {quotation.number} emailed to {to_email}.')
            return redirect('billing:quotation_detail', pk=quotation.pk)
    else:
        form = EmailDocumentForm(initial={
            'to_email': customer.email,
            'message': (
                f'Hi {customer.name},\n\n'
                f'Please find attached quotation {quotation.number} for your '
                f'{quotation.event.event_type} on {quotation.event.event_date}.\n\n'
                f'Thank you,\n{settings.COMPANY_LEGAL_NAME}'
            ),
        })
    return render(request, 'billing/quotation_email_form.html', {'form': form, 'object': quotation})


# ---------- Invoices ----------

class InvoiceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Invoice
    permission_required = 'billing.view_invoice'
    paginate_by = 25
    template_name = 'billing/invoice_list.html'

    def get_queryset(self):
        sync_invoice_statuses()
        qs = super().get_queryset().select_related('event__customer')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status'] = self.request.GET.get('status', '')
        ctx['statuses'] = Invoice.Status.choices
        return ctx


class InvoiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Invoice
    permission_required = 'billing.view_invoice'
    template_name = 'billing/invoice_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['payment_form'] = PaymentForm(initial={'amount': self.object.balance_due})
        return ctx


@login_required
@permission_required('billing.change_invoice', raise_exception=True)
def invoice_update(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        formset = InvoiceLineItemFormSet(request.POST, instance=invoice, prefix='line_items')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            invoice.refresh_status()
            log_model_activity(request, invoice, 'updated')
            messages.success(request, f'Invoice {invoice.number} updated.')
            return redirect('billing:invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)
        formset = InvoiceLineItemFormSet(instance=invoice, prefix='line_items')
    return render(request, 'billing/invoice_form.html', {
        'form': form, 'formset': formset, 'object': invoice, 'equipment_items': equipment_items_json(invoice.event),
    })


@login_required
@permission_required('billing.add_payment', raise_exception=True)
def invoice_add_payment(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            if not claim_token(request):
                messages.info(request, 'That payment was already recorded. It was not recorded again.')
                return redirect('billing:invoice_detail', pk=invoice.pk)
            data = form.cleaned_data
            payment, advanced = record_payment(
                invoice, amount=data['amount'], method=data['method'], paid_at=data['paid_at'],
                reference_number=data['reference_number'], notes=data['notes'], received_by=request.user,
            )
            log_model_activity(request, payment, 'created', extra=f'on invoice {invoice.number}')
            if advanced:
                messages.info(request, f'Event status advanced to "{invoice.event.get_status_display()}".')
                warn_if_short(request, invoice.event)
            messages.success(request, f'Payment of {settings.CURRENCY} {payment.amount:,.0f} recorded. Receipt {payment.receipt.number} is ready: send it to the client below.')
            return redirect('billing:receipt_detail', pk=payment.receipt.pk)
        # Re-render the invoice page with the bound form so the actual field
        # errors show up (e.g. "Ensure that there are no more than 2 decimal
        # places") — a redirect here would silently discard them.
        messages.error(request, 'Could not record payment — see the error below.')
        return render(request, 'billing/invoice_detail.html', {'object': invoice, 'payment_form': form})
    return redirect('billing:invoice_detail', pk=pk)


@login_required
@permission_required('billing.view_invoice', raise_exception=True)
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return render_pdf(request, 'pdf/invoice_pdf.html', {'invoice': invoice}, f'{invoice.number}.pdf')


@email_enabled_required
@login_required
@permission_required('billing.change_invoice', raise_exception=True)
def invoice_email(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    customer = invoice.event.customer
    if request.method == 'POST':
        form = EmailDocumentForm(request.POST)
        if form.is_valid():
            if not claim_token(request):
                messages.info(request, 'That email was already sent. It was not sent again.')
                return redirect('billing:invoice_detail', pk=invoice.pk)
            to_email = form.cleaned_data['to_email']
            outcome = send_or_queue(request, invoice, to_email, form.cleaned_data['message'])
            if outcome == 'failed':
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/invoice_email_form.html', {'form': form, 'object': invoice})
            if outcome == 'queued':
                messages.success(request, f'Invoice {invoice.number} is being emailed to {to_email}. It shows in the Communication log once sent.')
            else:
                messages.success(request, f'Invoice {invoice.number} emailed to {to_email}.')
            return redirect('billing:invoice_detail', pk=invoice.pk)
    else:
        form = EmailDocumentForm(initial={
            'to_email': customer.email,
            'message': (
                f'Hi {customer.name},\n\n'
                f'Please find attached invoice {invoice.number} for your '
                f'{invoice.event.event_type} on {invoice.event.event_date}. '
                f'Balance due: {settings.CURRENCY} {invoice.balance_due:,.0f}.\n\n'
                f'Thank you,\n{settings.COMPANY_LEGAL_NAME}'
            ),
        })
    return render(request, 'billing/invoice_email_form.html', {'form': form, 'object': invoice})


@login_required
@permission_required('billing.delete_invoice', raise_exception=True)
def invoice_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return confirm_and_delete(
        request, invoice,
        cancel_url=invoice.get_absolute_url(),
        success_url=reverse('events:detail', args=[invoice.event_id]),
        blockers=[count_label(invoice.payments.count(), 'recorded payment')],
        also_deleted=[count_label(invoice.line_items.count(), 'line item')],
        hint='Invoices with payments are part of the financial record. Set the status to Cancelled instead.',
    )


# ---------- Receipts ----------

class ReceiptListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Receipt
    permission_required = 'billing.view_receipt'
    paginate_by = 25
    template_name = 'billing/receipt_list.html'

    def get_queryset(self):
        qs = super().get_queryset().select_related('payment__invoice__event__customer', 'payment__received_by')
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q) | Q(payment__invoice__number__icontains=q)
                | Q(payment__invoice__event__customer__name__icontains=q)
                | Q(payment__reference_number__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        return ctx


class ReceiptDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Receipt
    permission_required = 'billing.view_receipt'
    template_name = 'billing/receipt_detail.html'

    def get_queryset(self):
        return super().get_queryset().select_related('payment__invoice__event__customer', 'payment__received_by')


def receipt_pdf_context(receipt):
    return {
        'receipt': receipt,
        'amount_in_words': amount_in_words(receipt.payment.amount),
    }


def shared_document(request, token):
    """Public, link-only view of one PDF (see billing.sharing). No login: the signed token is the key."""
    found = read_token(token)
    if found is None:
        return render(request, 'billing/share_expired.html', {'auth_page': True}, status=404)
    kind, pk = found
    if kind == 'quotation':
        quotation = get_object_or_404(Quotation, pk=pk)
        return render_pdf(request, 'pdf/quotation_pdf.html', {'quotation': quotation}, f'{quotation.number}.pdf')
    if kind == 'invoice':
        invoice = get_object_or_404(Invoice, pk=pk)
        return render_pdf(request, 'pdf/invoice_pdf.html', {'invoice': invoice}, f'{invoice.number}.pdf')
    receipt = get_object_or_404(Receipt, pk=pk)
    return render_pdf(request, 'pdf/receipt_pdf.html', receipt_pdf_context(receipt), f'{receipt.number}.pdf')


@login_required
@permission_required('billing.view_receipt', raise_exception=True)
def receipt_pdf(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    return render_pdf(request, 'pdf/receipt_pdf.html', receipt_pdf_context(receipt), f'{receipt.number}.pdf')


@email_enabled_required
@login_required
@permission_required('billing.change_receipt', raise_exception=True)
def receipt_email(request, pk):
    receipt = get_object_or_404(Receipt.objects.select_related('payment__invoice__event__customer'), pk=pk)
    payment = receipt.payment
    invoice = payment.invoice
    customer = invoice.event.customer
    if request.method == 'POST':
        form = EmailDocumentForm(request.POST)
        if form.is_valid():
            if not claim_token(request):
                messages.info(request, 'That email was already sent. It was not sent again.')
                return redirect('billing:receipt_detail', pk=receipt.pk)
            to_email = form.cleaned_data['to_email']
            outcome = send_or_queue(request, receipt, to_email, form.cleaned_data['message'])
            if outcome == 'failed':
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/receipt_email_form.html', {'form': form, 'object': receipt})
            if outcome == 'queued':
                messages.success(request, f'Receipt {receipt.number} is being emailed to {to_email}. It shows in the Communication log once sent.')
            else:
                messages.success(request, f'Receipt {receipt.number} emailed to {to_email}.')
            return redirect('billing:receipt_detail', pk=receipt.pk)
    else:
        balance_line = (
            f'Remaining balance on invoice {invoice.number}: {settings.CURRENCY} {invoice.balance_due:,.0f}.'
            if invoice.balance_due > 0 else f'Invoice {invoice.number} is now fully paid.'
        )
        form = EmailDocumentForm(initial={
            'to_email': customer.email,
            'message': (
                f'Hi {customer.name},\n\n'
                f'Thank you for your payment of {settings.CURRENCY} {payment.amount:,.0f} '
                f'received on {payment.paid_at:%d %b %Y}. Please find attached receipt {receipt.number}.\n\n'
                f'{balance_line}\n\n'
                f'Thank you,\n{settings.COMPANY_LEGAL_NAME}'
            ),
        })
    return render(request, 'billing/receipt_email_form.html', {'form': form, 'object': receipt})


# ---------- Mobile money ----------

@csrf_exempt
@require_POST
def mobile_money_webhook(request, provider):
    """Provider callback. Authenticated by HMAC signature, not by login (see billing.mobile_money)."""
    if not settings.MOBILE_MONEY_WEBHOOK_SECRET:
        raise Http404
    if not mobile_money.signature_ok(request.body, request.headers.get('X-Signature', '')):
        return JsonResponse({'error': 'bad signature'}, status=403)
    try:
        txn, created = mobile_money.receive(provider, mobile_money.parse_body(request.body))
    except mobile_money.WebhookError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'status': txn.status, 'duplicate': not created})


@login_required
@permission_required('billing.view_payment', raise_exception=True)
def mobile_money_list(request):
    unmatched = MobileMoneyTransaction.objects.filter(status=MobileMoneyTransaction.Status.UNMATCHED)
    recent = MobileMoneyTransaction.objects.exclude(status=MobileMoneyTransaction.Status.UNMATCHED).select_related(
        'payment__invoice__event__customer', 'payment__receipt', 'allocated_by',
    )
    return render(request, 'billing/mobile_money_list.html', {
        'unmatched': unmatched,
        'page': paginate(request, recent, per_page=25),
        'open_invoices': Invoice.objects.exclude(
            status__in=[Invoice.Status.PAID, Invoice.Status.CANCELLED],
        ).select_related('event__customer').prefetch_related('line_items', 'payments').order_by('-created_at'),
        'webhook_enabled': bool(settings.MOBILE_MONEY_WEBHOOK_SECRET),
    })


@require_POST
@login_required
@permission_required('billing.add_payment', raise_exception=True)
def mobile_money_allocate(request, pk):
    txn = get_object_or_404(MobileMoneyTransaction, pk=pk)
    if txn.status != MobileMoneyTransaction.Status.UNMATCHED:
        messages.info(request, f'{txn} was already dealt with.')
        return redirect('billing:mobile_money')
    if request.POST.get('action') == 'ignore':
        txn.status = MobileMoneyTransaction.Status.IGNORED
        txn.allocated_by = request.user
        txn.save(update_fields=['status', 'allocated_by', 'updated_at'])
        log_activity(request, 'mobile_money.ignored', f'Marked {txn} as not an invoice payment')
        messages.success(request, f'{txn} marked as not an invoice payment.')
        return redirect('billing:mobile_money')
    invoice = Invoice.objects.exclude(status=Invoice.Status.CANCELLED).filter(pk=request.POST.get('invoice')).first()
    if invoice is None:
        messages.error(request, 'Pick the invoice this payment is for.')
        return redirect('billing:mobile_money')
    with transaction.atomic():
        txn = MobileMoneyTransaction.objects.select_for_update().get(pk=txn.pk)
        if txn.status != MobileMoneyTransaction.Status.UNMATCHED:
            messages.info(request, f'{txn} was already dealt with.')
            return redirect('billing:mobile_money')
        payment = mobile_money.apply_to_invoice(txn, invoice, user=request.user)
    messages.success(request, f'{txn} recorded on invoice {invoice.number}. Receipt {payment.receipt.number} is ready.')
    return redirect('billing:mobile_money')


# ---------- Taxes ----------

class TaxGroupListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = TaxGroup
    permission_required = 'billing.view_taxgroup'
    template_name = 'billing/tax_list.html'


class TaxGroupFormMixin(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin):
    model = TaxGroup
    form_class = TaxGroupForm
    template_name = 'billing/tax_form.html'
    success_url = reverse_lazy('billing:tax_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'updated' if self.kwargs.get('pk') else 'created')
        return response


class TaxGroupCreateView(TaxGroupFormMixin, CreateView):
    permission_required = 'billing.add_taxgroup'
    success_message = 'Tax "%(name)s" added. Choose it on quotations and invoices that should include it.'


class TaxGroupUpdateView(TaxGroupFormMixin, UpdateView):
    permission_required = 'billing.change_taxgroup'
    success_message = 'Tax "%(name)s" saved. Documents already issued keep the rate they were issued with.'
