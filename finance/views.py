from datetime import date

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Sum
from django.shortcuts import render
from django.views.generic import CreateView, ListView

from core.activity import log_model_activity

from .forms import ExpenseRecordForm, IncomeRecordForm
from .models import ExpenseRecord, IncomeRecord


def _period_bounds(request):
    today = date.today()
    default_start = today.replace(day=1)
    start = request.GET.get('start') or default_start.isoformat()
    end = request.GET.get('end') or today.isoformat()
    return start, end


class IncomeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = IncomeRecord
    permission_required = 'finance.view_incomerecord'
    paginate_by = 25
    template_name = 'finance/income_list.html'


class IncomeCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = IncomeRecord
    form_class = IncomeRecordForm
    permission_required = 'finance.add_incomerecord'
    template_name = 'finance/income_form.html'
    success_message = 'Income record added.'
    success_url = '/finance/income/'

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'created')
        return response


class ExpenseListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = ExpenseRecord
    permission_required = 'finance.view_expenserecord'
    paginate_by = 25
    template_name = 'finance/expense_list.html'


class ExpenseCreateView(LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, CreateView):
    model = ExpenseRecord
    form_class = ExpenseRecordForm
    permission_required = 'finance.add_expenserecord'
    template_name = 'finance/expense_form.html'
    success_message = 'Expense record added.'
    success_url = '/finance/expenses/'

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        response = super().form_valid(form)
        log_model_activity(self.request, self.object, 'created')
        return response


@login_required
@permission_required('finance.view_incomerecord', raise_exception=True)
def summary(request):
    start, end = _period_bounds(request)
    income_qs = IncomeRecord.objects.filter(date__gte=start, date__lte=end)
    expense_qs = ExpenseRecord.objects.filter(date__gte=start, date__lte=end)

    total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = expense_qs.aggregate(total=Sum('amount'))['total'] or 0

    expenses_by_category = (
        expense_qs.values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return render(request, 'finance/summary.html', {
        'start': start,
        'end': end,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': total_income - total_expenses,
        'expenses_by_category': expenses_by_category,
        'recent_income': income_qs.order_by('-date')[:15],
        'recent_expenses': expense_qs.order_by('-date')[:15],
    })
