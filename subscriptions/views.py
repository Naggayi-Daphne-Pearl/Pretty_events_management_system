from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from comms.outreach import whatsapp_url
from core.activity import log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.pagination import paginate
from events.models import Event

from .forms import SubscriptionForm
from .models import Subscription
from .services import invoice_next_period, renewal_message

FILTERS = {
    'active': ('Active', lambda qs, today: qs.filter(is_active=True)),
    'due_soon': ('Due in 30 days', lambda qs, today: qs.filter(is_active=True, next_due_date__lte=today + timedelta(days=30))),
    'stopped': ('Stopped', lambda qs, today: qs.filter(is_active=False)),
    'all': ('All', lambda qs, today: qs),
}


@login_required
@permission_required('subscriptions.view_subscription', raise_exception=True)
def subscription_list(request):
    today = timezone.localdate()
    current = request.GET.get('show', 'active')
    if current not in FILTERS:
        current = 'active'
    queryset = FILTERS[current][1](Subscription.objects.select_related('event__customer', 'tax_group'), today)
    active = Subscription.objects.filter(is_active=True)
    yearly_total = sum((s.amount * 12 / s.months for s in active), 0)
    return render(request, 'subscriptions/subscription_list.html', {
        'page_obj': paginate(request, queryset, 50),
        'filters': [(key, label) for key, (label, _) in FILTERS.items()],
        'current': current,
        'yearly_total': yearly_total,
        'today': today,
    })


@login_required
@permission_required('subscriptions.view_subscription', raise_exception=True)
def subscription_detail(request, pk):
    subscription = get_object_or_404(Subscription.objects.select_related('event__customer', 'tax_group'), pk=pk)
    customer = subscription.customer
    return render(request, 'subscriptions/subscription_detail.html', {
        'object': subscription,
        'invoices': subscription.invoices.prefetch_related('line_items', 'payments').order_by('-due_date'),
        'whatsapp_url': whatsapp_url(customer.phone, renewal_message(subscription)) if subscription.is_active else '',
    })


def _form_view(request, subscription, initial=None):
    form = SubscriptionForm(request.POST or None, instance=subscription, initial=initial)
    if request.method == 'POST' and form.is_valid():
        creating = form.instance.pk is None
        if creating:
            form.instance.created_by = request.user
        subscription = form.save()
        log_model_activity(request, subscription, 'created' if creating else 'updated')
        messages.success(request, f'Renewal "{subscription.name}" saved. Next due {subscription.next_due_date:%d %b %Y}.')
        return redirect(subscription)
    return render(request, 'subscriptions/subscription_form.html', {'form': form, 'object': subscription})


@login_required
@permission_required('subscriptions.add_subscription', raise_exception=True)
def subscription_create(request):
    initial = {}
    event_pk = request.GET.get('event')
    if event_pk and event_pk.isdigit() and Event.objects.filter(pk=event_pk).exists():
        initial['event'] = event_pk
    return _form_view(request, Subscription(), initial)


@login_required
@permission_required('subscriptions.change_subscription', raise_exception=True)
def subscription_update(request, pk):
    return _form_view(request, get_object_or_404(Subscription, pk=pk))


@login_required
@permission_required('subscriptions.delete_subscription', raise_exception=True)
def subscription_delete(request, pk):
    subscription = get_object_or_404(Subscription, pk=pk)
    invoiced = subscription.invoices.count()
    return confirm_and_delete(
        request, subscription,
        cancel_url=subscription.get_absolute_url(), success_url=reverse('subscriptions:list'),
        blockers=[count_label(invoiced, 'invoice') if invoiced else ''],
        hint='It has already been invoiced. Untick Active on its edit page to stop future invoices instead.',
    )


@require_POST
@login_required
@permission_required('billing.add_invoice', raise_exception=True)
def subscription_invoice_now(request, pk):
    """Raise the next period's invoice straight away instead of waiting for the daily job."""
    subscription = get_object_or_404(Subscription, pk=pk, is_active=True)
    invoice = invoice_next_period(subscription, actor=request.user)
    messages.success(request, f'Invoice {invoice.number} raised for {subscription.name}, due {invoice.due_date:%d %b %Y}.')
    return redirect(invoice)
