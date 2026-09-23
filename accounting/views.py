import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.activity import log_activity, log_model_activity
from core.deletion import confirm_and_delete, count_label
from core.pagination import PER_PAGE_OPTIONS, paginate, per_page_from

from . import reports
from .forms import AccountEntryForm, AccountForm, JournalEntryForm, JournalLineFormSet, TransferForm, lines_initial
from .models import Account, JournalEntry
from .services import save_entry


def _date_param(request, name, default):
    value = parse_date(request.GET.get(name) or '') if request.GET.get(name) else None
    return value or default


def _period(request):
    today = timezone.localdate()
    start = _date_param(request, 'start', reports.fiscal_year_start(today))
    end = _date_param(request, 'end', today)
    return start, end


def _csv(filename, header, rows):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


# ---------- Chart of accounts ----------

@login_required
@permission_required('accounting.view_account', raise_exception=True)
def chart_of_accounts(request):
    as_of = _date_param(request, 'as_of', timezone.localdate())
    show_inactive = request.GET.get('inactive') == '1'
    q = (request.GET.get('q') or '').strip()
    balances = reports.balances(as_of)
    accounts = Account.objects.select_related('parent').order_by('code')
    if not show_inactive:
        accounts = accounts.filter(is_active=True)
    if q:
        accounts = accounts.filter(Q(name__icontains=q) | Q(code__icontains=q))
    groups = []
    for value, label in Account.Type.choices:
        rows = [{'account': a, 'balance': balances.get(a.pk, 0)} for a in accounts if a.account_type == value]
        groups.append({'label': label, 'rows': rows, 'total': sum((r['balance'] for r in rows), 0)})
    if request.GET.get('format') == 'csv':
        return _csv(f'chart_of_accounts_{as_of}.csv', ['Code', 'Account', 'Type', 'Detail type', 'Parent', 'Active', f'Balance at {as_of}'], [
            [r['account'].code, r['account'].name, r['account'].get_account_type_display(), r['account'].get_detail_type_display(),
             r['account'].parent.code if r['account'].parent else '', 'Yes' if r['account'].is_active else 'No', r['balance']]
            for g in groups for r in g['rows']
        ])
    return render(request, 'accounting/chart_of_accounts.html', {
        'groups': groups, 'as_of': as_of, 'show_inactive': show_inactive, 'q': q,
    })


def _account_form_view(request, account=None):
    is_new = account is None
    initial = {'account_type': request.GET.get('type'), 'detail_type': request.GET.get('detail')} if is_new else None
    form = AccountForm(request.POST or None, instance=account, initial=initial)
    if request.method == 'POST' and form.is_valid():
        account = form.save()
        log_model_activity(request, account, 'created' if is_new else 'updated')
        messages.success(request, f'Account "{account}" saved.')
        return redirect(account.get_absolute_url())
    return render(request, 'accounting/account_form.html', {
        'form': form, 'object': account, 'details_by_type': {k: list(v) for k, v in Account.DETAILS_BY_TYPE.items()},
    })


@login_required
@permission_required('accounting.add_account', raise_exception=True)
def account_create(request):
    return _account_form_view(request)


@login_required
@permission_required('accounting.change_account', raise_exception=True)
def account_update(request, pk):
    return _account_form_view(request, get_object_or_404(Account, pk=pk))


@login_required
@permission_required('accounting.view_account', raise_exception=True)
def account_detail(request, pk):
    account = get_object_or_404(Account, pk=pk)
    start, end = _period(request)
    ledger = reports.account_ledger(account, start, end)
    if request.GET.get('format') == 'csv':
        return _csv(f'{account.code}_ledger_{start}_{end}.csv', ['Date', 'Entry', 'Description', 'Debit', 'Credit', 'Balance'],
                    [['', '', 'Opening balance', '', '', ledger['opening']]] + [
                        [r['line'].entry.date, r['line'].entry.number, r['line'].description or r['line'].entry.memo,
                         r['line'].debit or '', r['line'].credit or '', r['balance']] for r in ledger['rows']])
    per_page = per_page_from(request, 50)
    return render(request, 'accounting/account_detail.html', {
        'object': account, 'start': start, 'end': end, 'ledger': ledger,
        'page_obj': paginate(request, ledger['rows'], per_page), 'per_page': per_page, 'per_page_options': PER_PAGE_OPTIONS,
    })


@login_required
@permission_required('accounting.add_journalentry', raise_exception=True)
def account_entry(request, pk):
    """Record a manual debit or credit straight onto one general ledger account."""
    account = get_object_or_404(Account, pk=pk)
    if not account.is_active:
        messages.error(request, f'"{account}" is inactive. Reactivate it before adding entries.')
        return redirect(account.get_absolute_url())
    form = AccountEntryForm(request.POST or None, account=account)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        entry = JournalEntry(date=d['date'], memo=d['memo'] or f'Entry on {account.name}', reference=d['reference'],
                             source=d['source'], created_by=request.user)
        try:
            save_entry(entry, form.lines())
        except ValidationError as error:
            form.add_error(None, error)
        else:
            log_model_activity(request, entry, 'created', extra=f'on account "{account}"')
            messages.success(request, f'Entry {entry.number} recorded on {account.name}.')
            return redirect(account.get_absolute_url())
    return render(request, 'accounting/account_entry_form.html', {'form': form, 'object': account})


@login_required
@permission_required('accounting.delete_account', raise_exception=True)
def account_delete(request, pk):
    account = get_object_or_404(Account, pk=pk)
    return confirm_and_delete(
        request, account,
        cancel_url=account.get_absolute_url(),
        success_url=reverse('accounting:chart'),
        blockers=[
            'automatic posting (it is a system account)' if account.system_key else '',
            count_label(account.lines.count(), 'journal line'),
            count_label(account.children.count(), 'sub-account'),
            count_label(account.expense_categories.count(), 'expense category', 'expense categories'),
            count_label(account.expense_records.count(), 'expense record'),
        ],
        hint='Accounts with history are kept so past reports stay correct. Untick "Is active" to hide it from new entries.',
    )


# ---------- Journals ----------

@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def journal_list(request):
    entries = JournalEntry.objects.prefetch_related('lines').select_related('created_by')
    source = request.GET.get('source', '')
    q = (request.GET.get('q') or '').strip()
    start = _date_param(request, 'start', None)
    end = _date_param(request, 'end', None)
    if source:
        entries = entries.filter(source=source)
    if q:
        entries = entries.filter(Q(number__icontains=q) | Q(memo__icontains=q) | Q(reference__icontains=q)
                                 | Q(lines__account__name__icontains=q)).distinct()
    if start:
        entries = entries.filter(date__gte=start)
    if end:
        entries = entries.filter(date__lte=end)
    per_page = per_page_from(request, 25)
    return render(request, 'accounting/journal_list.html', {
        'page_obj': paginate(request, entries, per_page), 'per_page': per_page, 'per_page_options': PER_PAGE_OPTIONS,
        'source': source, 'sources': JournalEntry.Source.choices, 'q': q, 'start': start or '', 'end': end or '',
    })


@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def journal_detail(request, pk):
    entry = get_object_or_404(JournalEntry.objects.prefetch_related('lines__account'), pk=pk)
    return render(request, 'accounting/journal_detail.html', {'object': entry})


def _journal_form_view(request, entry):
    is_new = entry.pk is None
    if not is_new and entry.is_auto:
        messages.info(request, 'This entry was created automatically. Edit the income or expense record it came from instead.')
        return redirect(entry.get_absolute_url())
    form = JournalEntryForm(request.POST or None, instance=entry)
    initial = None if is_new else lines_initial(entry)
    prefill = Account.objects.filter(pk=request.GET.get('account'), is_active=True).first() if (is_new and str(request.GET.get('account', '')).isdigit()) else None
    if prefill:
        initial = [{'account': prefill}]  # "New journal" from an account page starts with that account
    formset = JournalLineFormSet(request.POST or None, prefix='lines', initial=initial)
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        entry = form.save(commit=False)
        if is_new:
            entry.created_by = request.user
        try:
            save_entry(entry, formset.lines)
        except ValidationError as error:
            formset._non_form_errors = formset.error_class(error.messages)
        else:
            log_model_activity(request, entry, 'created' if is_new else 'updated')
            messages.success(request, f'Journal {entry.number} saved.')
            return redirect(entry.get_absolute_url())
    return render(request, 'accounting/journal_form.html', {'form': form, 'formset': formset, 'object': None if is_new else entry})


@login_required
@permission_required('accounting.add_journalentry', raise_exception=True)
def journal_create(request):
    return _journal_form_view(request, JournalEntry())


@login_required
@permission_required('accounting.change_journalentry', raise_exception=True)
def journal_update(request, pk):
    return _journal_form_view(request, get_object_or_404(JournalEntry, pk=pk))


@login_required
@permission_required('accounting.delete_journalentry', raise_exception=True)
def journal_delete(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    return confirm_and_delete(
        request, entry,
        cancel_url=entry.get_absolute_url(),
        success_url=reverse('accounting:journal_list'),
        blockers=[f'the {entry.get_source_display().lower()} it was created from' if entry.is_auto else ''],
        also_deleted=[count_label(entry.lines.count(), 'journal line')],
        hint='Automatic entries disappear when their income or expense record is deleted.',
    )


# ---------- Banking ----------

@login_required
@permission_required('accounting.view_account', raise_exception=True)
def banking(request):
    balances = reports.balances(timezone.localdate())
    accounts = Account.objects.filter(detail_type=Account.Detail.CASH_BANK).order_by('-is_active', 'code')
    rows = [{'account': a, 'balance': balances.get(a.pk, 0),
             'recent': a.lines.select_related('entry').order_by('-entry__date', '-entry__pk')[:5]} for a in accounts]
    return render(request, 'accounting/banking.html', {
        'rows': rows, 'total': sum((r['balance'] for r in rows if r['account'].is_active), 0),
    })


@login_required
@permission_required('accounting.add_journalentry', raise_exception=True)
def transfer_create(request):
    form = TransferForm(request.POST or None, initial={'from_account': request.GET.get('from')})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        memo = d['memo'] or f'Transfer from {d["from_account"].name} to {d["to_account"].name}'
        entry = JournalEntry(date=d['date'], memo=memo, reference=d['reference'],
                             source=JournalEntry.Source.TRANSFER, created_by=request.user)
        save_entry(entry, [
            {'account': d['to_account'], 'debit': d['amount'], 'description': memo},
            {'account': d['from_account'], 'credit': d['amount'], 'description': memo},
        ])
        log_activity(request, 'journalentry.transfer', f'Transferred {d["amount"]:,.2f} from "{d["from_account"]}" to "{d["to_account"]}" ({entry.number})')
        messages.success(request, f'Transfer recorded as {entry.number}.')
        return redirect('accounting:banking')
    return render(request, 'accounting/transfer_form.html', {'form': form})


# ---------- Reports ----------

@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def reports_index(request):
    return render(request, 'accounting/reports_index.html')


@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def trial_balance(request):
    as_of = _date_param(request, 'as_of', timezone.localdate())
    tb = reports.trial_balance(as_of)
    if request.GET.get('format') == 'csv':
        return _csv(f'trial_balance_{as_of}.csv', ['Code', 'Account', 'Type', 'Debit', 'Credit'],
                    [[r['account'].code, r['account'].name, r['account'].get_account_type_display(), r['debit'] or '', r['credit'] or '']
                     for r in tb['rows']] + [['', 'Total', '', tb['total_debit'], tb['total_credit']]])
    return render(request, 'accounting/trial_balance.html', {'as_of': as_of, **tb})


def _section_csv_rows(sections):
    rows = []
    for section in sections:
        rows.append([section.title, ''])
        for r in section.rows:
            rows.append([f'  {r["account"].code} {r["account"].name}' if 'account' in r else f'  {r["label"]}', r['amount']])
        rows.append([f'Total {section.title.lower()}', section.total])
    return rows


@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def income_statement(request):
    start, end = _period(request)
    report = reports.income_statement(start, end)
    if request.GET.get('format') == 'csv':
        rows = _section_csv_rows([report['income'], report['cost_of_sales']]) + [['Gross profit', report['gross_profit']]]
        rows += _section_csv_rows([report['expenses']]) + [['Operating profit', report['operating_profit']]]
        rows += _section_csv_rows([report['other_income'], report['other_expenses']]) + [['Net profit', report['net_profit']]]
        return _csv(f'income_statement_{start}_{end}.csv', ['Line', 'Amount'], rows)
    return render(request, 'accounting/income_statement.html', {'start': start, 'end': end, **report})


@login_required
@permission_required('accounting.view_journalentry', raise_exception=True)
def balance_sheet(request):
    as_of = _date_param(request, 'as_of', timezone.localdate())
    report = reports.balance_sheet(as_of)
    if request.GET.get('format') == 'csv':
        rows = [['ASSETS', '']] + _section_csv_rows(report['asset_sections']) + [['Total assets', report['total_assets']]]
        rows += [['LIABILITIES', '']] + _section_csv_rows(report['liability_sections']) + [['Total liabilities', report['total_liabilities']]]
        rows += _section_csv_rows([report['equity']]) + [['Total liabilities and equity', report['liabilities_and_equity']]]
        return _csv(f'balance_sheet_{as_of}.csv', ['Line', 'Amount'], rows)
    return render(request, 'accounting/balance_sheet.html', {'as_of': as_of, **report})
