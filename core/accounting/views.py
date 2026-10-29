from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.forms import formset_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit.services import log_action

from .forms import (
    AccountForm,
    AccountingPeriodForm,
    BalancedJournalLineFormSet,
    FiscalYearForm,
    JournalEntryForm,
    JournalLineForm,
    ReconciliationForm,
    ReversalForm,
    SystemAccountMappingForm,
    TrialBalanceForm,
)
from .models import (
    Account,
    AccountingPeriod,
    AccountReconciliation,
    FiscalYear,
    JournalEntry,
    SystemAccountMapping,
)
from .services import JournalService, ReconciliationService, build_trial_balance

JournalLineFormSet = formset_factory(
    JournalLineForm,
    formset=BalancedJournalLineFormSet,
    extra=2,
    min_num=2,
    validate_min=True,
)


@require_GET
def account_list(request):
    accounts = Account.objects.select_related('parent').all()
    return render(request, 'accounting/account_list.html', {'accounts': accounts})


@require_http_methods(['GET', 'POST'])
def account_form(request, pk=None):
    instance = get_object_or_404(Account.objects, pk=pk) if pk else None
    form = AccountForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        account = form.save()
        log_action(
            'Update' if instance else 'Create',
            'Account',
            account.pk,
            new_values={
                'code': account.code,
                'name': account.name,
                'account_type': account.account_type,
            },
        )
        messages.success(request, 'Account saved successfully.')
        if request.GET.get('popup') == '1':
            return render(request, 'popup_complete.html', {
                'completion_message': 'Account saved successfully.',
            })
        return redirect('accounting:Module_Accounting_account_list')
    return render(request, 'accounting/account_form.html', {
        'form': form,
        'title': 'Edit account' if instance else 'Create account',
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def fiscal_year_list(request):
    years = FiscalYear.objects.prefetch_related('periods').all()
    return render(request, 'accounting/fiscal_year_list.html', {'years': years})


@require_http_methods(['GET', 'POST'])
def fiscal_year_form(request):
    form = FiscalYearForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        fiscal_year = form.save()
        log_action(
            'Create',
            'FiscalYear',
            fiscal_year.pk,
            new_values={'name': fiscal_year.name},
        )
        messages.success(request, 'Fiscal year created successfully.')
        return redirect('accounting:Module_Accounting_fiscal_years')
    return render(request, 'accounting/fiscal_year_form.html', {
        'form': form,
        'title': 'Create fiscal year',
    }, status=400 if request.method == 'POST' else 200)


@require_http_methods(['GET', 'POST'])
def period_form(request):
    form = AccountingPeriodForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        period = form.save()
        log_action(
            'Create',
            'AccountingPeriod',
            period.pk,
            new_values={
                'fiscal_year': period.fiscal_year.name,
                'number': period.number,
                'name': period.name,
            },
        )
        messages.success(request, 'Accounting period created successfully.')
        return redirect('accounting:Module_Accounting_fiscal_years')
    return render(request, 'accounting/period_form.html', {
        'form': form,
        'title': 'Create accounting period',
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def system_account_list(request):
    mappings = SystemAccountMapping.objects.select_related('account').order_by('key')
    return render(request, 'accounting/system_account_list.html', {'mappings': mappings})


@require_http_methods(['GET', 'POST'])
def system_account_form(request, pk=None):
    instance = get_object_or_404(SystemAccountMapping.objects, pk=pk) if pk else None
    form = SystemAccountMappingForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        mapping = form.save()
        log_action(
            'Update' if instance else 'Create',
            'SystemAccountMapping',
            mapping.pk,
            new_values={'key': mapping.key, 'account_id': mapping.account_id},
        )
        messages.success(request, 'System account mapping saved.')
        if request.GET.get('popup') == '1':
            return render(request, 'popup_complete.html', {
                'completion_message': 'System account mapping saved.',
            })
        return redirect('accounting:Module_Accounting_system_accounts')
    return render(request, 'accounting/system_account_form.html', {
        'form': form,
        'title': 'Edit system account mapping' if instance else 'Create system account mapping',
    }, status=400 if request.method == 'POST' else 200)


@transaction.atomic
@require_POST
def close_period(request, pk):
    period = get_object_or_404(AccountingPeriod.objects.select_for_update(), pk=pk)
    if period.is_closed:
        messages.info(request, 'This accounting period is already closed.')
        return redirect('accounting:Module_Accounting_fiscal_years')
    period.is_closed = True
    period.save(update_fields=['is_closed'])
    log_action(
        'Close',
        'AccountingPeriod',
        period.pk,
        new_values={'is_closed': True},
    )
    messages.success(request, f'{period.name} was closed.')
    return redirect('accounting:Module_Accounting_fiscal_years')


@require_GET
def journal_entry_list(request):
    queryset = JournalEntry.objects.select_related(
        'branch', 'created_by', 'posted_by', 'fiscal_year', 'period'
    ).prefetch_related('lines')
    status = request.GET.get('status', '').strip()
    if status in dict(JournalEntry.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    page_obj = Paginator(queryset, 25).get_page(request.GET.get('page', 1))
    return render(request, 'accounting/journal_entry_list.html', {
        'page_obj': page_obj,
        'selected_status': status,
        'statuses': JournalEntry.STATUS_CHOICES,
    })


@require_http_methods(['GET', 'POST'])
def journal_entry_create(request):
    form = JournalEntryForm(request.POST or None, request=request)
    line_formset = JournalLineFormSet(request.POST or None, prefix='lines')
    if request.method == 'POST' and form.is_valid() and line_formset.is_valid():
        lines = [line.cleaned_data for line in line_formset.forms if line.has_changed()]
        try:
            with transaction.atomic():
                service = JournalService(request)
                entry = service.create_entry(
                    branch_id=form.cleaned_data['branch'].pk,
                    journal_date=form.cleaned_data['journal_date'],
                    narration=form.cleaned_data['narration'],
                    voucher_type=form.cleaned_data['voucher_type'],
                    requires_approval=form.cleaned_data['requires_approval'],
                    idempotency_key=form.cleaned_data['idempotency_key'],
                )
                if not entry._idempotent_replay:
                    for line in lines:
                        service.add_line(
                            entry_id=entry.pk,
                            account_id=line['account'].pk,
                            debit=line['debit'],
                            credit=line['credit'],
                            narration=line['narration'],
                        )
                    if entry.requires_approval:
                        service.submit_for_approval(entry_id=entry.pk)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f'Journal voucher {entry.voucher_number} was saved.')
            if request.GET.get('popup') == '1':
                return render(request, 'popup_complete.html', {
                    'completion_message': f'Journal voucher {entry.voucher_number} was saved.',
                })
            return redirect('accounting:Module_Accounting_journal_detail', pk=entry.pk)

    return render(request, 'accounting/journal_entry_form.html', {
        'form': form,
        'line_formset': line_formset,
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def journal_entry_detail(request, pk):
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            'branch', 'fiscal_year', 'period', 'created_by', 'posted_by', 'reversal_of'
        ).prefetch_related('lines__account'),
        pk=pk,
    )
    reverse_form = ReversalForm(initial={'reversal_date': timezone.localdate()})
    return render(request, 'accounting/journal_entry_detail.html', {
        'entry': entry,
        'reverse_form': reverse_form,
    })


@require_POST
def journal_entry_post(request, pk):
    try:
        entry = JournalService(request).post(entry_id=pk)
    except JournalEntry.DoesNotExist:
        raise Http404
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, f'Journal voucher {entry.voucher_number} was posted.')
    return redirect('accounting:Module_Accounting_journal_detail', pk=pk)


@require_http_methods(['GET', 'POST'])
def journal_entry_reverse(request, pk):
    entry = get_object_or_404(JournalEntry.objects, pk=pk)
    form = ReversalForm(request.POST or None, initial={'reversal_date': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        try:
            reversal = JournalService(request).reverse(
                entry_id=entry.pk,
                reversal_date=form.cleaned_data['reversal_date'],
                reason=form.cleaned_data['reason'],
            )
        except JournalEntry.DoesNotExist:
            raise Http404
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f'Reversal voucher {reversal.voucher_number} was posted.')
            return redirect('accounting:Module_Accounting_journal_detail', pk=reversal.pk)
    return render(request, 'accounting/reversal_form.html', {
        'form': form,
        'entry': entry,
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def trial_balance(request):
    form = TrialBalanceForm(request.GET or None, request=request)
    report = None
    if form.is_valid() and request.GET:
        selected_branch = form.cleaned_data['branch']
        branch_ids = (
            request.user.accessible_branch_ids(selected_branch.pk)
            if selected_branch
            else request.user.accessible_branch_ids(request.active_branch_id)
        )
        report = build_trial_balance(
            start_date=form.cleaned_data['start_date'],
            end_date=form.cleaned_data['end_date'],
            branch_ids=branch_ids,
        )
    return render(request, 'accounting/trial_balance.html', {
        'form': form,
        'report': report,
    })


@require_GET
def reconciliation_list(request):
    branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    reconciliations = AccountReconciliation.objects.select_related(
        'branch', 'account', 'prepared_by', 'reconciled_by'
    ).filter(branch_id__in=branch_ids)
    return render(request, 'accounting/reconciliation_list.html', {
        'reconciliations': reconciliations,
    })


@require_http_methods(['GET', 'POST'])
def reconciliation_create(request):
    form = ReconciliationForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        try:
            ReconciliationService(request).create(
                branch_id=form.cleaned_data['branch'].pk,
                account_id=form.cleaned_data['account'].pk,
                as_of_date=form.cleaned_data['as_of_date'],
                statement_balance=form.cleaned_data['statement_balance'],
                notes=form.cleaned_data['notes'],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Reconciliation prepared for review.')
            if request.GET.get('popup') == '1':
                return render(request, 'popup_complete.html', {
                    'completion_message': 'Reconciliation prepared successfully.',
                })
            return redirect('accounting:Module_Accounting_reconciliation_list')
    return render(request, 'accounting/reconciliation_form.html', {
        'form': form,
    }, status=400 if request.method == 'POST' else 200)


@require_POST
def reconciliation_confirm(request, pk):
    try:
        reconciliation = ReconciliationService(request).confirm(reconciliation_id=pk)
    except AccountReconciliation.DoesNotExist:
        raise Http404
    except ValidationError as error:
        messages.error(request, '; '.join(error.messages))
    else:
        messages.success(request, f'{reconciliation.account.name} reconciliation confirmed.')
    return redirect('accounting:Module_Accounting_reconciliation_list')
