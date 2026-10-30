import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form
from core.configuration.services import get_organization_configuration

from .forms import (
    SavingsAccountForm,
    SavingsFeeForm,
    SavingsInterestForm,
    SavingsProductForm,
    SavingsReactivationReasonForm,
    SavingsReversalForm,
    SavingsTransactionForm,
    WithdrawalRejectionForm,
)
from .models import SavingsAccount, SavingsProduct, SavingsTransaction
from .services import SavingsService


def _show_form(request, template, form, title, *, status=200, **extra):
    return render_popup_form(
        request, template, {'form': form, 'title': title, **extra}, status=status
    )


@require_GET
def product_list(request):
    if 'page' in request.GET or request.GET.get('format') == 'json':
        products = SavingsProduct.objects.all()
        status = request.GET.get('status', '').strip()
        if status in {'active', 'inactive'}:
            products = products.filter(is_active=status == 'active')
        search = request.GET.get('searchString', request.GET.get('q', '')).strip()
        if search:
            products = products.filter(
                Q(code__icontains=search) | Q(name__icontains=search)
            )
        order_fields = {
            'code': 'code',
            'name': 'name',
            'annual_interest_rate': 'annual_interest_rate',
            'is_active': 'is_active',
        }
        order = order_fields.get(request.GET.get('sidx', 'code'), 'code')
        if request.GET.get('sord', 'asc').lower() == 'desc':
            order = f'-{order}'
        page_obj = Paginator(products.order_by(order), 25).get_page(
            request.GET.get('page', 1)
        )
        return JsonResponse({
            'page': page_obj.number,
            'total': page_obj.paginator.num_pages,
            'records': page_obj.paginator.count,
            'rows': [
                {
                    'id': product.pk,
                    'code': product.code,
                    'name': product.name,
                    'type': product.get_savings_type_display(),
                    'rate': str(product.annual_interest_rate),
                    'method': product.get_interest_method_display(),
                    'frequency': product.get_posting_frequency_display(),
                    'opening_minimum': f'{product.minimum_opening_balance:.2f}',
                    'minimum': f'{product.minimum_balance:.2f}',
                    'withdrawal_limit': (
                        f'{product.maximum_withdrawal:.2f}'
                        if product.maximum_withdrawal is not None
                        else '—'
                    ),
                    'fee': f'{product.fee_amount:.2f}',
                    'active': product.is_active,
                }
                for product in page_obj.object_list
            ],
        })
    products = SavingsProduct.objects.order_by('code')
    return render(request, 'savings/product_list.html', {'products': products})


@require_http_methods(['GET', 'POST'])
def product_form(request, pk=None):
    instance = get_object_or_404(SavingsProduct, pk=pk) if pk else None
    old_values = _savings_product_values(instance) if instance else None
    form = SavingsProductForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        product = form.save()
        log_action(
            'Update' if instance else 'Create',
            'SavingsProduct',
            product.pk,
            old_values=old_values,
            new_values=_savings_product_values(product),
        )
        message = 'Savings product saved.'
        response = popup_json_response(
            request, message=message, data={'id': product.pk}
        )
        if response is not None:
            return response
        messages.success(request, message)
        return redirect('savings:Module_Savings_products')
    return render_popup_form(
        request,
        'savings/product_form.html',
        {
            'form': form,
            'title': 'Edit savings product' if instance else 'Create savings product',
        },
        status=400 if request.method == 'POST' else 200,
    )


def _savings_product_values(product):
    if product is None:
        return None
    values = {}
    for field in product._meta.concrete_fields:
        value = getattr(product, field.attname)
        values[field.name] = (
            str(value)
            if value is not None and field.get_internal_type() == "DecimalField"
            else value
        )
    return values


@require_POST
def product_activate(request, pk):
    return _set_savings_product_active(request, pk, True)


@require_POST
def product_deactivate(request, pk):
    return _set_savings_product_active(request, pk, False)


@transaction.atomic
def _set_savings_product_active(request, pk, active):
    product = get_object_or_404(SavingsProduct.objects.select_for_update(), pk=pk)
    old_values = _savings_product_values(product)
    if product.is_active != active:
        product.is_active = active
        product.save(update_fields=['is_active'])
        log_action(
            'Activate' if active else 'Deactivate',
            'SavingsProduct',
            product.pk,
            old_values=old_values,
            new_values=_savings_product_values(product),
        )
    message = 'Savings product activated.' if active else 'Savings product deactivated.'
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'success': True,
            'message': message,
            'data': {'id': product.pk},
        })
    messages.success(request, message)
    return redirect('savings:Module_Savings_products')


@require_GET
def account_list(request):
    accounts = SavingsAccount.objects.select_related(
        'branch',
        'product',
        'member',
        'group',
    )
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    if search:
        accounts = accounts.filter(
            Q(account_number__icontains=search)
            | Q(member__member_code__icontains=search)
            | Q(member__first_name__icontains=search)
            | Q(member__last_name__icontains=search)
            | Q(group__name__icontains=search)
        )
    if status in dict(SavingsAccount.STATUS_CHOICES):
        accounts = accounts.filter(status=status)
    page_obj = Paginator(accounts.order_by('account_number'), 25).get_page(
        request.GET.get('page', 1)
    )
    return render(request, 'savings/account_list.html', {
        'page_obj': page_obj,
        'search': search,
        'selected_status': status,
        'statuses': SavingsAccount.STATUS_CHOICES,
    })


@require_GET
def balance_report(request):
    rows = SavingsAccount.objects.filter(
        status__in=[SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT],
    ).values(
        'branch__name',
        'product__code',
        'product__name',
    ).annotate(
        account_count=Count('pk'),
        total_balance=Sum('balance'),
        total_reserved_balance=Sum('reserved_balance'),
        available_balance=Sum('balance') - Sum('reserved_balance'),
    ).order_by('branch__name', 'product__code')
    totals = SavingsAccount.objects.filter(
        status__in=[SavingsAccount.STATUS_ACTIVE, SavingsAccount.STATUS_DORMANT],
    ).aggregate(
        account_count=Count('pk'),
        total_balance=Sum('balance'),
        total_reserved_balance=Sum('reserved_balance'),
        available_balance=Sum('balance') - Sum('reserved_balance'),
    )
    return render(request, 'savings/balance_report.html', {
        'rows': rows,
        'totals': totals,
    })


@require_GET
def reconciliation_report(request):
    date_value = request.GET.get('as_of_date', '')
    as_of_date = parse_date(date_value) if date_value else timezone.localdate()
    if as_of_date is None:
        return HttpResponse('as_of_date must use YYYY-MM-DD format.', status=400)
    branch_value = request.GET.get('branch_id')
    try:
        branch_id = int(branch_value) if branch_value else None
    except ValueError:
        return HttpResponse('branch_id must be an integer.', status=400)
    try:
        result = SavingsService(request).reconcile_savings(
            as_of_date=as_of_date,
            branch_id=branch_id,
        )
    except ValidationError as exc:
        if branch_id is not None:
            raise PermissionDenied from exc
        raise
    return render(request, 'savings/reconciliation.html', result)


@require_http_methods(['GET', 'POST'])
def account_create(request):
    form = SavingsAccountForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        values = form.cleaned_data
        try:
            account = SavingsService(request).open_account(
                branch_id=values['branch'].pk,
                product_id=values['product'].pk,
                member_id=values['member'].pk if values['owner_type'] == form.OWNER_MEMBER else None,
                group_id=values['group'].pk if values['owner_type'] == form.OWNER_GROUP else None,
                contribution_member_id=(
                    values['contribution_member'].pk if values['contribution_member'] else None
                ),
                opened_at=values['opened_at'],
                opening_balance=values['opening_balance'],
                idempotency_key=values['idempotency_key'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            message = f'Savings account {account.account_number} opened.'
            response = popup_json_response(
                request, message=message, data={'id': account.pk}
            )
            if response is not None:
                return response
            if not getattr(account, '_idempotent_replay', False):
                messages.success(request, message)
            return redirect('savings:Module_Savings_accounts')
    return render_popup_form(
        request,
        'savings/account_form.html',
        {'form': form, 'title': 'Open savings account'},
        status=400 if request.method == 'POST' else 200,
    )


@require_GET
def transaction_list(request):
    transactions = SavingsTransaction.objects.select_related(
        'branch',
        'account',
        'account__product',
        'account__member',
        'account__group',
        'created_by',
        'approved_by',
        'journal_entry',
    )
    status = request.GET.get('status', '').strip()
    if status in dict(SavingsTransaction.STATUS_CHOICES):
        transactions = transactions.filter(status=status)
    account_number = request.GET.get('account', '').strip()
    if account_number:
        transactions = transactions.filter(account__account_number=account_number)
    page_obj = Paginator(transactions, 30).get_page(request.GET.get('page', 1))
    return render(request, 'savings/transaction_list.html', {
        'page_obj': page_obj,
        'statuses': SavingsTransaction.STATUS_CHOICES,
        'selected_status': status,
        'account_number': account_number,
    })


@require_GET
def transaction_create(request, operation):
    if operation not in {'deposit', 'withdraw'}:
        return redirect('savings:Module_Savings_transactions')
    return _render_transaction_form(request, operation, None)


@require_POST
def transaction_submit(request, operation):
    if operation not in {'deposit', 'withdraw'}:
        return render(request, '404.html', status=404)
    return _render_transaction_form(request, operation, request.POST)


def _render_transaction_form(request, operation, data):
    form = SavingsTransactionForm(data, request=request)
    if data is not None and form.is_valid():
        values = form.cleaned_data
        service = SavingsService(request)
        try:
            if operation == 'deposit':
                result = service.deposit(
                    account_id=values['account'].pk,
                    amount=values['amount'],
                    transaction_date=values['transaction_date'],
                    payment_channel=values['payment_channel'],
                    idempotency_key=values['idempotency_key'],
                    contribution_member_id=(
                        values['contribution_member'].pk if values['contribution_member'] else None
                    ),
                    narration=values['narration'],
                )
            else:
                result = service.withdraw(
                    account_id=values['account'].pk,
                    amount=values['amount'],
                    transaction_date=values['transaction_date'],
                    payment_channel=values['payment_channel'],
                    idempotency_key=values['idempotency_key'],
                    narration=values['narration'],
                )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if result.status == SavingsTransaction.STATUS_PENDING:
                message = 'Withdrawal submitted for approval.'
            else:
                message = f'{operation.title()} posted successfully.'
            response = popup_json_response(request, message=message)
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('savings:Module_Savings_transactions')
    return _show_form(
        request,
        'savings/transaction_form.html',
        form,
        'Savings deposit' if operation == 'deposit' else 'Savings withdrawal',
        status=400 if data is not None else 200,
        form_action=reverse(f'savings:Module_Savings_submit_{operation}')
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_GET
def charge_fee(request):
    return _charge_fee(request, None)


@require_POST
def charge_fee_submit(request):
    return _charge_fee(request, request.POST)


def _charge_fee(request, data):
    form = SavingsFeeForm(data, request=request)
    if data is not None and form.is_valid():
        values = form.cleaned_data
        try:
            SavingsService(request).charge_fee(
                account_id=values['account'].pk,
                transaction_date=values['transaction_date'],
                idempotency_key=values['idempotency_key'],
                narration=values['narration'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            message = 'Savings fee posted successfully.'
            response = popup_json_response(request, message=message)
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('savings:Module_Savings_transactions')
    return _show_form(
        request,
        'savings/transaction_form.html',
        form,
        'Charge product fee',
        status=400 if data is not None else 200,
        form_action=reverse('savings:Module_Savings_submit_fee')
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_GET
def interest_post(request):
    return _interest_post(request, None)


@require_POST
def interest_post_submit(request):
    return _interest_post(request, request.POST)


def _interest_post(request, data):
    form = SavingsInterestForm(data, request=request)
    if data is not None and form.is_valid():
        values = form.cleaned_data
        try:
            result = SavingsService(request).post_interest(
                account_id=values['account'].pk,
                start_date=values['start_date'],
                end_date=values['end_date'],
                idempotency_key=values['idempotency_key'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            message = f'Interest of {result.amount} posted.'
            response = popup_json_response(request, message=message)
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('savings:Module_Savings_transactions')
    return _show_form(
        request,
        'savings/interest_form.html',
        form,
        'Post savings interest',
        status=400 if data is not None else 200,
        form_action=reverse('savings:Module_Savings_submit_interest')
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_GET
def statement(request, pk):
    account = get_object_or_404(
        SavingsAccount.objects.select_related('branch', 'product', 'member', 'group'),
        pk=pk,
    )
    transactions = account.transactions.filter(
        status=SavingsTransaction.STATUS_POSTED,
    ).select_related('created_by', 'journal_entry').order_by('transaction_date', 'pk')
    return render(request, 'savings/statement.html', {
        'account': account,
        'transactions': transactions,
    })


@require_GET
def statement_export(request, pk):
    account = get_object_or_404(
        SavingsAccount.objects.select_related('branch'),
        pk=pk,
    )
    transactions = account.transactions.filter(
        status=SavingsTransaction.STATUS_POSTED,
    ).order_by('transaction_date', 'pk')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{account.account_number}-statement.csv"'
    writer = csv.writer(response)
    organization = get_organization_configuration()
    writer.writerow([organization.legal_name])
    writer.writerow(['Savings statement', account.account_number])
    writer.writerow(['Branch', account.branch.name])
    writer.writerow([])
    writer.writerow(['Date', 'Type', 'Amount', 'Balance before', 'Balance after', 'Narration'])
    writer.writerows(
        (
            transaction.transaction_date.isoformat(),
            transaction.get_transaction_type_display(),
            transaction.amount,
            transaction.balance_before,
            transaction.balance_after,
            transaction.narration,
        )
        for transaction in transactions
    )
    log_action(
        'Export',
        'SavingsStatement',
        account.pk,
        new_values={
            'format': 'csv',
            'row_count': transactions.count(),
            'account_id': account.pk,
        },
        branch_id=account.branch_id,
    )
    return response


@require_GET
def reactivation_form(request, pk):
    account = get_object_or_404(SavingsAccount.objects, pk=pk)
    if account.status != SavingsAccount.STATUS_DORMANT:
        return render(request, '404.html', status=404)
    return _show_form(
        request,
        'savings/reactivation_form.html',
        SavingsReactivationReasonForm(),
        f'Reactivate savings account {account.account_number}',
        account=account,
    )


@require_POST
def reactivate_account(request, pk):
    account = get_object_or_404(SavingsAccount.objects, pk=pk)
    form = SavingsReactivationReasonForm(request.POST)
    if not form.is_valid():
        return _show_form(
            request,
            'savings/reactivation_form.html',
            form,
            f'Reactivate savings account {account.account_number}',
            status=400,
            account=account,
        )
    try:
        SavingsService(request).reactivate_account(
            account_id=pk,
            reason=form.cleaned_data['reason'],
        )
    except SavingsAccount.DoesNotExist:
        return render(request, '404.html', status=404)
    except ValidationError as exc:
        form.add_error(None, exc)
        return _show_form(
            request,
            'savings/reactivation_form.html',
            form,
            f'Reactivate savings account {account.account_number}',
            status=400,
            account=account,
        )
    messages.success(request, 'Savings account reactivated.')
    return redirect('savings:Module_Savings_accounts')


@require_GET
def reversal_form(request, pk):
    original = get_object_or_404(
        SavingsTransaction.objects.select_related('account', 'journal_entry'),
        pk=pk,
        status=SavingsTransaction.STATUS_POSTED,
    )
    return _show_form(
        request,
        'savings/reversal_form.html',
        SavingsReversalForm(),
        f'Reverse transaction {original.pk}',
        original=original,
        form_action=reverse(
            'savings:Module_Savings_reverse',
            args=[original.pk],
        ) + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_POST
def reverse_transaction(request, pk):
    original = get_object_or_404(
        SavingsTransaction.objects.select_related('account', 'journal_entry'),
        pk=pk,
        status=SavingsTransaction.STATUS_POSTED,
    )
    form = SavingsReversalForm(request.POST)
    if form.is_valid():
        try:
            reversal = SavingsService(request).reverse(
                transaction_id=original.pk,
                reversal_date=form.cleaned_data['reversal_date'],
                reason=form.cleaned_data['reason'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            message = f'Transaction reversed as {reversal.pk}.'
            response = popup_json_response(
                request, message=message, data={'id': reversal.pk}
            )
            if response is not None:
                return response
            messages.success(request, 'Savings transaction reversed successfully.')
            return redirect('savings:Module_Savings_transactions')
    return _show_form(
        request,
        'savings/reversal_form.html',
        form,
        f'Reverse transaction {original.pk}',
        status=400,
        original=original,
        form_action=reverse('savings:Module_Savings_reverse', args=[original.pk])
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_POST
def approve_withdrawal(request, pk):
    try:
        SavingsService(request).approve_withdrawal(transaction_id=pk)
    except SavingsTransaction.DoesNotExist:
        return render(request, '404.html', status=404)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        messages.success(request, 'Withdrawal approved and posted.')
    return redirect('savings:Module_Savings_transactions')


@require_POST
def close_account(request, pk):
    try:
        SavingsService(request).close_account(account_id=pk)
    except SavingsAccount.DoesNotExist:
        return render(request, '404.html', status=404)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        messages.success(request, 'Savings account closed.')
    return redirect('savings:Module_Savings_accounts')


@require_GET
def rejection_form(request, pk):
    pending = get_object_or_404(
        SavingsTransaction.objects,
        pk=pk,
        status=SavingsTransaction.STATUS_PENDING,
    )
    return _show_form(
        request,
        'savings/rejection_form.html',
        WithdrawalRejectionForm(),
        f'Reject withdrawal {pending.pk}',
        pending=pending,
        form_action=reverse('savings:Module_Savings_reject_withdrawal', args=[pending.pk])
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )


@require_POST
def reject_withdrawal(request, pk):
    pending = get_object_or_404(
        SavingsTransaction.objects,
        pk=pk,
        status=SavingsTransaction.STATUS_PENDING,
    )
    form = WithdrawalRejectionForm(request.POST)
    if form.is_valid():
        try:
            SavingsService(request).reject_withdrawal(
                transaction_id=pending.pk,
                reason=form.cleaned_data['reason'],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            message = 'Withdrawal rejected; reserved funds were released.'
            response = popup_json_response(request, message=message)
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('savings:Module_Savings_transactions')
    return _show_form(
        request,
        'savings/rejection_form.html',
        form,
        f'Reject withdrawal {pending.pk}',
        status=400,
        pending=pending,
        form_action=reverse('savings:Module_Savings_reject_withdrawal', args=[pending.pk])
        + ('?popup=1' if request.GET.get('popup') == '1' else ''),
    )
