"""
Daily housekeeping without a cron service: the first request each day runs the jobs
(status changes that depend only on the date). A unique row per day makes sure only
one web worker runs them, however many requests arrive at once. The same jobs remain
available as management commands for a cron schedule.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

_last_checked = None  # per process, so most requests skip the database entirely


def run_daily_jobs(today):
    from billing.services import sync_invoice_statuses
    from events.services import sync_event_statuses

    from .client import feature_enabled
    result = {'events': sync_event_statuses(today)}
    if feature_enabled('subscriptions'):
        from subscriptions.services import invoice_due_subscriptions
        result['renewal_invoices'] = invoice_due_subscriptions(today)
    # After raising renewal invoices, so one already past its due date shows as overdue.
    result['invoices'] = sync_invoice_statuses(today)
    return result


def run_if_due():
    global _last_checked
    from .models import DailyJobRun

    today = timezone.localdate()
    if _last_checked == today:
        return None
    try:
        with transaction.atomic():
            DailyJobRun.objects.create(day=today)
            result = run_daily_jobs(today)
    except IntegrityError:
        result = None  # another worker already ran today's jobs
    except Exception:  # never break a page because housekeeping failed; try again next request
        logger.exception('Daily jobs failed')
        return None
    _last_checked = today
    return result


class DailyJobsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        run_if_due()
        return self.get_response(request)
