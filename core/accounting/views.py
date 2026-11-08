from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.forms import formset_factory
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html, format_html_join
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.accounts.permission_utils import user_has_route_permission
from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form
from core.common.templatetags.user_formatting import config_money
from core.configuration.services import get_system_configuration

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
    JournalLine,
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
    branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    accounts = Account.objects.select_related('parent').all()
    code = request.GET.get('code', '').strip()
    name = request.GET.get('name', '').strip()
    if code:
        accounts = accounts.filter(code__icontains=code)
    if name:
        accounts = accounts.filter(name__icontains=name)
    account_type = request.GET.get('type', '')
    if account_type in dict(Account.ACCOUNT_TYPE_CHOICES):
        accounts = accounts.filter(account_type=account_type)
    status = request.GET.get('status', '')
    if status in {'active', 'inactive'}:
        accounts = accounts.filter(is_active=status == 'active')

    order_fields = {
        'code': 'code',
        'name': 'name',
        'parent': 'parent__name',
        'account_type': 'account_type',
        'normal_balance': 'normal_balance',
        'posting': 'allows_direct_posting',
        'status': 'is_active',
    }
    order = order_fields.get(request.GET.get('sidx', 'code'), 'code')
    if request.GET.get('sord', 'asc').lower() == 'desc':
        order = f'-{order}'
    try:
        page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(accounts.order_by(order, 'pk'), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    balances = {
        row['account_id']: (
            row['debit'] or Decimal('0.00'),
            row['credit'] or Decimal('0.00'),
        )
        for row in JournalLine.objects.filter(
            entry__branch_id__in=branch_ids,
            entry__status=JournalEntry.STATUS_POSTED,
        ).values('account_id').annotate(
            debit=Sum('debit'),
            credit=Sum('credit'),
        )
    }
    system_configuration = get_system_configuration()

    def account_balance(account):
        debit, credit = balances.get(
            account.pk, (Decimal('0.00'), Decimal('0.00'))
        )
        return (
            debit - credit
            if account.normal_balance == Account.DEBIT
            else credit - debit
        )

    if request.GET.get('ajax') == '1':
        can_edit = user_has_route_permission(
            request.user, 'Module_Accounting_account_edit'
        )
        rows = []
        for account in page_obj.object_list:
            actions = []
            if can_edit:
                actions.append(format_html(
                    '<a href="{}?popup=1" data-popup data-popup-title="Edit account">'
                    'Edit</a>',
                    reverse(
                        'accounting:Module_Accounting_account_edit',
                        args=[account.pk],
                    ),
                ))
            rows.append({
                'id': account.pk,
                'code': account.code,
                'name': account.name,
                'parent': str(account.parent) if account.parent_id else '—',
                'account_type': account.get_account_type_display(),
                'normal_balance': account.get_normal_balance_display(),
                'current_balance': config_money(
                    account_balance(account), system_configuration
                ),
                'posting': (
                    'Direct' if account.allows_direct_posting else 'Control'
                ),
                'status': 'Active' if account.is_active else 'Inactive',
                'actions': format_html_join(
                    ' | ', '{}', ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'accounting/account_list.html', {
        'list_title': 'Chart of accounts',
        'grid_url': request.path,
        'filter_layout': 'members',
        'default_sort_name': 'code',
        'default_sort_order': 'asc',
        'initial_page_text': f'Page {page_obj.number} of {paginator.num_pages}',
        'add_url': (
            reverse('accounting:Module_Accounting_account_add')
            if user_has_route_permission(
                request.user, 'Module_Accounting_account_add'
            )
            else ''
        ),
        'add_title': 'Create account',
        'list_filters': [
            {
                'name': 'code', 'label': 'Account code',
                'value': code, 'placeholder': 'Account code',
            },
            {
                'name': 'name', 'label': 'Name',
                'value': name, 'placeholder': 'Account name',
            },
            {
                'name': 'type', 'label': 'Type', 'type': 'select',
                'value': account_type, 'options': Account.ACCOUNT_TYPE_CHOICES,
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': status,
                'options': (('active', 'Active'), ('inactive', 'Inactive')),
            },
        ],
        'list_columns': [
            {'name': 'code', 'label': 'Code', 'width': 110},
            {'name': 'name', 'label': 'Name', 'width': 190},
            {'name': 'parent', 'label': 'Parent', 'width': 190},
            {'name': 'account_type', 'label': 'Type', 'width': 110},
            {
                'name': 'normal_balance', 'label': 'Normal balance',
                'width': 130,
            },
            {
                'name': 'current_balance', 'label': 'Current balance',
                'width': 150, 'align': 'right', 'sortable': False,
            },
            {'name': 'posting', 'label': 'Posting', 'width': 90},
            {'name': 'status', 'label': 'Status', 'width': 100},
            {'name': 'actions', 'label': 'Actions', 'width': 90},
        ],
    })


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
        response = popup_json_response(
            request,
            message='Account saved successfully.',
            data={'id': account.pk},
        )
        if response is not None:
            return response
        messages.success(request, 'Account saved successfully.')
        return redirect('accounting:Module_Accounting_account_list')
    return render_popup_form(request, 'accounting/account_form.html', {
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
        response = popup_json_response(
            request,
            message='Fiscal year created successfully.',
            data={'id': fiscal_year.pk},
        )
        if response is not None:
            return response
        messages.success(request, 'Fiscal year created successfully.')
        return redirect('accounting:Module_Accounting_fiscal_years')
    return render_popup_form(request, 'accounting/fiscal_year_form.html', {
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
        response = popup_json_response(
            request,
            message='Accounting period created successfully.',
            data={'id': period.pk},
        )
        if response is not None:
            return response
        messages.success(request, 'Accounting period created successfully.')
        return redirect('accounting:Module_Accounting_fiscal_years')
    return render_popup_form(request, 'accounting/period_form.html', {
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
        response = popup_json_response(
            request,
            message='System account mapping saved.',
            data={'id': mapping.pk},
        )
        if response is not None:
            return response
        messages.success(request, 'System account mapping saved.')
        return redirect('accounting:Module_Accounting_system_accounts')
    return render_popup_form(request, 'accounting/system_account_form.html', {
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
    ).annotate(
        debit_total=Sum('lines__debit'),
        credit_total=Sum('lines__credit'),
    )
    voucher = request.GET.get('voucher', '').strip()
    if voucher:
        queryset = queryset.filter(voucher_number__icontains=voucher)
    branch = request.GET.get('branch', '').strip()
    if branch:
        queryset = queryset.filter(branch__code__icontains=branch)
    narration = request.GET.get('narration', '').strip()
    if narration:
        queryset = queryset.filter(narration__icontains=narration)
    status = request.GET.get('status', '').strip()
    if status in dict(JournalEntry.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    try:
        parsed_date_from = parse_date(date_from) if date_from else None
        parsed_date_to = parse_date(date_to) if date_to else None
    except ValueError:
        return HttpResponseBadRequest('Journal dates must use YYYY-MM-DD format.')
    if (date_from and parsed_date_from is None) or (
        date_to and parsed_date_to is None
    ):
        return HttpResponseBadRequest('Journal dates must use YYYY-MM-DD format.')
    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        return HttpResponseBadRequest('The start date must be on or before the end date.')
    if parsed_date_from:
        queryset = queryset.filter(journal_date__gte=parsed_date_from)
    if parsed_date_to:
        queryset = queryset.filter(journal_date__lte=parsed_date_to)

    order_fields = {
        'journal_date': 'journal_date',
        'voucher_number': 'voucher_number',
        'branch': 'branch__code',
        'narration': 'narration',
        'status': 'status',
        'debit': 'debit_total',
        'credit': 'credit_total',
    }
    order = order_fields.get(request.GET.get('sidx', 'journal_date'), 'journal_date')
    if request.GET.get('sord', 'desc').lower() == 'desc':
        order = f'-{order}'
    try:
        page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(queryset.order_by(order, '-pk'), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if request.GET.get('ajax') == '1':
        can_view = user_has_route_permission(
            request.user, 'Module_Accounting_journal_detail'
        )
        rows = []
        system_configuration = get_system_configuration()
        for entry in page_obj.object_list:
            actions = []
            if can_view:
                actions.append(format_html(
                    '<a href="{}">View</a>',
                    reverse(
                        'accounting:Module_Accounting_journal_detail',
                        args=[entry.pk],
                    ),
                ))
            rows.append({
                'id': entry.pk,
                'journal_date': entry.journal_date.isoformat(),
                'voucher_number': entry.voucher_number,
                'branch': entry.branch.code,
                'narration': entry.narration,
                'status': entry.get_status_display(),
                'debit': config_money(
                    entry.debit_total or Decimal('0.00'), system_configuration
                ),
                'credit': config_money(
                    entry.credit_total or Decimal('0.00'), system_configuration
                ),
                'actions': format_html_join(
                    ' | ', '{}', ((action,) for action in actions)
                ),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'accounting/journal_entry_list.html', {
        'list_title': 'Journal entries',
        'grid_url': request.path,
        'filter_layout': 'members',
        'default_sort_name': 'journal_date',
        'default_sort_order': 'desc',
        'initial_page_text': f'Page {page_obj.number} of {paginator.num_pages}',
        'list_actions': [],
        'add_url': (
            reverse('accounting:Module_Accounting_journal_add')
            if user_has_route_permission(
                request.user, 'Module_Accounting_journal_add'
            )
            else ''
        ),
        'add_title': 'Create journal entry',
        'list_filters': [
            {
                'name': 'voucher', 'label': 'Voucher number',
                'value': voucher, 'placeholder': 'Voucher number',
            },
            {
                'name': 'branch', 'label': 'Branch code',
                'value': branch, 'placeholder': 'Branch code',
            },
            {
                'name': 'narration', 'label': 'Narration',
                'value': narration, 'placeholder': 'Narration',
            },
            {
                'name': 'date', 'label': 'Journal date',
                'type': 'date-range',
                'from_name': 'date_from', 'from_value': date_from,
                'to_name': 'date_to', 'to_value': date_to,
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': status, 'options': JournalEntry.STATUS_CHOICES,
            },
        ],
        'list_columns': [
            {'name': 'journal_date', 'label': 'Date', 'width': 110},
            {'name': 'voucher_number', 'label': 'Voucher', 'width': 150},
            {'name': 'branch', 'label': 'Branch', 'width': 110},
            {'name': 'narration', 'label': 'Narration', 'width': 260},
            {'name': 'status', 'label': 'Status', 'width': 130},
            {
                'name': 'debit', 'label': 'Debit', 'width': 140,
                'align': 'right',
            },
            {
                'name': 'credit', 'label': 'Credit', 'width': 140,
                'align': 'right',
            },
            {'name': 'actions', 'label': 'Actions', 'width': 90},
        ],
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
            message = f'Journal voucher {entry.voucher_number} was saved.'
            response = popup_json_response(
                request, message=message, data={'id': entry.pk}
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('accounting:Module_Accounting_journal_detail', pk=entry.pk)

    return render_popup_form(request, 'accounting/journal_entry_form.html', {
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
            response = popup_json_response(
                request,
                message=f'Reversal voucher {reversal.voucher_number} was posted.',
                data={'id': reversal.pk},
            )
            if response is not None:
                return response
            messages.success(request, f'Reversal voucher {reversal.voucher_number} was posted.')
            return redirect('accounting:Module_Accounting_journal_detail', pk=reversal.pk)
    return render_popup_form(request, 'accounting/reversal_form.html', {
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
            response = popup_json_response(
                request, message='Reconciliation prepared successfully.'
            )
            if response is not None:
                return response
            messages.success(request, 'Reconciliation prepared for review.')
            return redirect('accounting:Module_Accounting_reconciliation_list')
    return render_popup_form(request, 'accounting/reconciliation_form.html', {
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
