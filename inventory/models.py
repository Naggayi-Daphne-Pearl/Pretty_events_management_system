from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse

from core.models import TimeStampedModel
from events.models import Event


class EquipmentCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Equipment categories'

    def __str__(self):
        return self.name


class EquipmentItem(TimeStampedModel):
    name = models.CharField(max_length=150)
    category = models.ForeignKey(
        EquipmentCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='items',
    )
    total_quantity = models.PositiveIntegerField(default=0)
    unit = models.CharField(max_length=30, default='pieces')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('inventory:item_detail', args=[self.pk])

    @property
    def quantity_issued(self):
        outstanding = self.issues.select_related(None).all()
        total_issued = 0
        for issue in outstanding:
            total_issued += issue.quantity_outstanding
        return total_issued

    @property
    def available_quantity(self):
        return self.total_quantity - self.quantity_issued


class EquipmentIssue(TimeStampedModel):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='equipment_issues')
    equipment_item = models.ForeignKey(EquipmentItem, on_delete=models.PROTECT, related_name='issues')
    quantity_issued = models.PositiveIntegerField()
    issued_at = models.DateField()
    expected_return_date = models.DateField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='equipment_issued',
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-issued_at']

    def __str__(self):
        return f'{self.quantity_issued} x {self.equipment_item.name} -> {self.event}'

    @property
    def quantity_returned(self):
        return self.returns.aggregate(total=Sum('quantity_returned'))['total'] or 0

    @property
    def quantity_outstanding(self):
        return self.quantity_issued - self.quantity_returned

    @property
    def is_fully_returned(self):
        return self.quantity_outstanding <= 0


class EquipmentReturn(TimeStampedModel):
    issue = models.ForeignKey(EquipmentIssue, on_delete=models.CASCADE, related_name='returns')
    quantity_returned = models.PositiveIntegerField()
    returned_at = models.DateField()
    condition_notes = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='equipment_returns_received',
    )

    class Meta:
        ordering = ['-returned_at']

    def __str__(self):
        return f'{self.quantity_returned} returned for {self.issue}'
