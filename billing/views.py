from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.generic import DetailView, ListView

from core.activity import log_model_activity
from core.utils import amount_in_words
from events.models import Event
from inventory.models import EquipmentItem

from .forms import (
    InvoiceForm, InvoiceLineItemFormSet, PaymentForm, QuotationForm, QuotationLineItemFormSet,
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


def render_pdf(request, template_name, context, filename):
    # Render context processors (branding, currency, etc.) into the PDF template too.
    html_string = render_to_string(template_name, context, request=request)
    try:
        from weasyprint import HTML
        # Resolve relative asset paths (e.g. the logo) straight off disk rather than
        # over HTTP — avoids a request-fetching-itself deadlock on the dev server.
        pdf_bytes = HTML(string=html_string, base_url=f'file://{settings.BASE_DIR}/').write_pdf()
    except (ImportError, OSError):
        # WeasyPrint's native deps (pango/cairo) aren't installed on this machine —
        # fall back to plain HTML so the document is still viewable/printable.
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
            payment = form.save(commit=False)
            payment.invoice = invoice
            payment.received_by = request.user
            payment.save()
            log_model_activity(request, payment, 'created', extra=f'on invoice {invoice.number}')
            messages.success(request, f'Payment of {payment.amount} recorded. Receipt {payment.receipt.number} generated.')
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


# ---------- Receipts ----------

class ReceiptDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Receipt
    permission_required = 'billing.view_receipt'
    template_name = 'billing/receipt_detail.html'


@login_required
@permission_required('billing.view_receipt', raise_exception=True)
def receipt_pdf(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    context = {
        'receipt': receipt,
        'amount_in_words': amount_in_words(receipt.payment.amount),
    }
    return render_pdf(request, 'pdf/receipt_pdf.html', context, f'{receipt.number}.pdf')
