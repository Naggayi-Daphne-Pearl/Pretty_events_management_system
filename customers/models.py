from django.conf import settings
from django.db import models
from django.urls import reverse

from core.models import TimeStampedModel


class Customer(TimeStampedModel):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30)
    alt_phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='customers_created',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('customers:detail', args=[self.pk])
