from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.generic import DetailView, ListView

from comms.models import CommunicationLog
from core.activity import log_activity, log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.emailing import send_pdf_email
from core.once import claim_token
from core.utils import amount_in_words
from events.models import Event
from finance.models import IncomeRecord
from inventory.models import EquipmentItem

from .forms import (
    EmailDocumentForm, InvoiceForm, InvoiceLineItemFormSet, PaymentForm, QuotationForm,
    QuotationLineItemFormSet,
)
from .models import Invoice, Payment, Quotation, Receipt


def equipment_items_json():
    """Feeds the line-item table's "pick an inventory item" auto-fill JS —
    see quotation_form.html / invoice_form.html."""
    return {
        str(item.pk): {
            'name': item.name,
            'rate': str(item.default_rate) if item.default_rate is not None else '',
            'available': item.available_quantity,
            'unit': item.unit,
        }
        for item in EquipmentItem.objects.all()
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
        if form.is_valid():
            quotation = form.save(commit=False)
            quotation.event = event
            quotation.created_by = request.user
            quotation.save()
            formset = QuotationLineItemFormSet(request.POST, instance=quotation, prefix='line_items')
            if formset.is_valid():
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
        'form': form, 'formset': formset, 'event': event, 'equipment_items': equipment_items_json(),
    })


@login_required
@permission_required('billing.change_quotation', raise_exception=True)
def quotation_update(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
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
        'equipment_items': equipment_items_json(),
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
    messages.success(request, f'Invoice {invoice.number} created from {quotation.number}.')
    return redirect('billing:invoice_detail', pk=invoice.pk)


@login_required
@permission_required('billing.view_quotation', raise_exception=True)
def quotation_pdf(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    return render_pdf(request, 'pdf/quotation_pdf.html', {'quotation': quotation}, f'{quotation.number}.pdf')


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
            pdf_bytes = generate_pdf_bytes(request, 'pdf/quotation_pdf.html', {'quotation': quotation})
            sent = send_pdf_email(
                to_email=to_email,
                subject=f'Quotation {quotation.number} from {settings.COMPANY_LEGAL_NAME}',
                body=form.cleaned_data['message'],
                pdf_bytes=pdf_bytes,
                filename=f'{quotation.number}.pdf',
            )
            if not sent:
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/quotation_email_form.html', {'form': form, 'object': quotation})
            if quotation.status == Quotation.Status.DRAFT:
                quotation.status = Quotation.Status.SENT
                quotation.save(update_fields=['status'])
            CommunicationLog.objects.create(
                customer=customer,
                event=quotation.event,
                channel=CommunicationLog.Channel.EMAIL,
                direction=CommunicationLog.Direction.OUTBOUND,
                message=f'Emailed quotation {quotation.number} to {to_email}',
                logged_by=request.user,
            )
            log_model_activity(request, quotation, 'emailed', extra=f'to {to_email}')
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
        'form': form, 'formset': formset, 'object': invoice, 'equipment_items': equipment_items_json(),
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
            payment = form.save(commit=False)
            payment.invoice = invoice
            payment.received_by = request.user
            payment.save()
            log_model_activity(request, payment, 'created', extra=f'on invoice {invoice.number}')
            # A payment IS income — record it automatically so Finance/P&L totals are
            # correct without staff having to separately re-enter every invoice payment
            # as an income record too (that would just be error-prone double-entry).
            IncomeRecord.objects.create(
                amount=payment.amount,
                source=IncomeRecord.Source.INVOICE_PAYMENT,
                date=payment.paid_at,
                event=invoice.event,
                payment=payment,
                description=f'Payment on invoice {invoice.number}',
                recorded_by=request.user,
            )
            if invoice.event.advance_status_at_least(Event.Status.CONFIRMED):
                messages.info(request, f'Event status advanced to "{invoice.event.get_status_display()}".')
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
            pdf_bytes = generate_pdf_bytes(request, 'pdf/invoice_pdf.html', {'invoice': invoice})
            sent = send_pdf_email(
                to_email=to_email,
                subject=f'Invoice {invoice.number} from {settings.COMPANY_LEGAL_NAME}',
                body=form.cleaned_data['message'],
                pdf_bytes=pdf_bytes,
                filename=f'{invoice.number}.pdf',
            )
            if not sent:
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/invoice_email_form.html', {'form': form, 'object': invoice})
            CommunicationLog.objects.create(
                customer=customer,
                event=invoice.event,
                channel=CommunicationLog.Channel.EMAIL,
                direction=CommunicationLog.Direction.OUTBOUND,
                message=f'Emailed invoice {invoice.number} to {to_email}',
                logged_by=request.user,
            )
            log_model_activity(request, invoice, 'emailed', extra=f'to {to_email}')
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


@login_required
@permission_required('billing.view_receipt', raise_exception=True)
def receipt_pdf(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    return render_pdf(request, 'pdf/receipt_pdf.html', receipt_pdf_context(receipt), f'{receipt.number}.pdf')


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
            pdf_bytes = generate_pdf_bytes(request, 'pdf/receipt_pdf.html', receipt_pdf_context(receipt))
            sent = send_pdf_email(
                to_email=to_email,
                subject=f'Receipt {receipt.number} from {settings.COMPANY_LEGAL_NAME}',
                body=form.cleaned_data['message'],
                pdf_bytes=pdf_bytes,
                filename=f'{receipt.number}.pdf',
            )
            if not sent:
                messages.error(request, 'Could not send the email: the mail server could not be reached. Please try again, and tell your administrator if it keeps failing.')
                return render(request, 'billing/receipt_email_form.html', {'form': form, 'object': receipt})
            CommunicationLog.objects.create(
                customer=customer,
                event=invoice.event,
                channel=CommunicationLog.Channel.EMAIL,
                direction=CommunicationLog.Direction.OUTBOUND,
                message=f'Emailed receipt {receipt.number} to {to_email}',
                logged_by=request.user,
            )
            log_model_activity(request, receipt, 'emailed', extra=f'to {to_email}')
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
