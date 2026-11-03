import calendar
from datetime import date

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from billing.models import Invoice, TaxGroup
from core.models import TimeStampedModel
from events.models import Event


def add_months(start, months):
    """The same day `months` later, or the month's last day when it's shorter (31 Jan + 1 -> 28 Feb)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


class Subscription(TimeStampedModel):
    """
    A charge that repeats: yearly hosting, a domain renewal, a monthly maintenance
    retainer. It belongs to a project (Event), so its invoices sit with that project's
    other invoices. A set number of days before each due date the daily jobs raise the
    invoice by themselves (subscriptions.services), then move on to the next period.
    """

    class Interval(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        QUARTERLY = 'quarterly', 'Every 3 months'
        HALF_YEARLY = 'half_yearly', 'Every 6 months'
        YEARLY = 'yearly', 'Yearly'

    MONTHS = {Interval.MONTHLY: 1, Interval.QUARTERLY: 3, Interval.HALF_YEARLY: 6, Interval.YEARLY: 12}

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='subscriptions')
    name = models.CharField(max_length=200, help_text='As it appears on the invoice, e.g. "Hosting", "Domain example.co.ug".')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)],
                                 help_text='Charged each period, before tax.')
    interval = models.CharField(max_length=20, choices=Interval.choices, default=Interval.YEARLY)
    start_date = models.DateField(help_text='When the first period is due. Later periods follow from this date.')
    next_due_date = models.DateField(editable=False)
    periods_invoiced = models.PositiveIntegerField(default=0, editable=False)
    invoice_days_before = models.PositiveSmallIntegerField(
        default=14, help_text='How many days before each due date the invoice is raised.',
    )
    tax_group = models.ForeignKey(TaxGroup, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                                  verbose_name='Tax')
    is_active = models.BooleanField(default=True, verbose_name='Active',
                                    help_text='Untick to stop raising invoices (e.g. the client cancelled).')
    notes = models.TextField(blank=True)
    invoices = models.ManyToManyField(Invoice, blank=True, related_name='subscriptions', editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['next_due_date', 'name']

    def __str__(self):
        return f'{self.name} ({self.event.customer.name})'

    def get_absolute_url(self):
        return reverse('subscriptions:detail', args=[self.pk])

    @property
    def customer(self):
        return self.event.customer

    @property
    def months(self):
        return self.MONTHS[self.interval]

    def due_date_for(self, period):
        """Due date of period 0, 1, 2... counted from start_date, so short months never shift later dates."""
        return add_months(self.start_date, period * self.months)

    def period_end(self, due):
        return add_months(due, self.months)

    def save(self, *args, **kwargs):
        self.next_due_date = self.due_date_for(self.periods_invoiced)
        super().save(*args, **kwargs)
