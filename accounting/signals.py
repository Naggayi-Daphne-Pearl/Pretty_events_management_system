from django.db.models.signals import post_save
from django.dispatch import receiver

from finance.models import ExpenseRecord, IncomeRecord

from .posting import sync_expense_record, sync_income_record


# Any save of an income/expense record (from the app, admin or a script) re-posts
# its journal entry; deleting the record deletes the entry (on_delete=CASCADE).
@receiver(post_save, sender=IncomeRecord, dispatch_uid='accounting.post_income')
def post_income(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_income_record(instance)


@receiver(post_save, sender=ExpenseRecord, dispatch_uid='accounting.post_expense')
def post_expense(sender, instance, raw=False, **kwargs):
    if not raw:
        sync_expense_record(instance)
