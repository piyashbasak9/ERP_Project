import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.middleware.csrf import get_token
from django.http import HttpResponse, JsonResponse
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
from core.configuration.services import (
    get_organization_configuration,
    get_system_configuration,
)

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


def _add_validation_error(form, error):
    if hasattr(error, 'message_dict'):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


@require_GET
def product_list(request):
    if request.GET.get('ajax') == '1' or request.GET.get('format') == 'json':
        products = SavingsProduct.objects.all()
        status = request.GET.get('status', '').strip()
        if status in {'active', 'inactive'}:
            products = products.filter(is_active=status == 'active')
        code = request.GET.get('code', '').strip()
        name = request.GET.get('name', '').strip()
        search = request.GET.get(
            'searchString',
            request.GET.get('q', ''),
        ).strip()
        if code:
            products = products.filter(code__icontains=code)
        if name:
            products = products.filter(name__icontains=name)
        if search and not code and not name:
            products = products.filter(
                Q(code__icontains=search) | Q(name__icontains=search)
            )
        order_fields = {
            'code': 'code',
            'name': 'name',
            'type': 'savings_type',
            'rate': 'annual_interest_rate',
            'method': 'interest_method',
            'frequency': 'posting_frequency',
            'opening_minimum': 'minimum_opening_balance',
            'minimum': 'minimum_balance',
            'withdrawal_limit': 'maximum_withdrawal',
            'fee': 'fee_amount',
            'status': 'is_active',
        }
        order = order_fields.get(request.GET.get('sidx', 'code'), 'code')
        if request.GET.get('sord', 'asc').lower() == 'desc':
            order = f'-{order}'
        try:
            page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
        except (TypeError, ValueError):
            page_size = 20
        page_obj = Paginator(products.order_by(order, 'pk'), page_size).get_page(
            request.GET.get('page', 1)
        )
        can_edit = user_has_route_permission(
            request.user, 'Module_Savings_product_edit'
        )
        can_activate = user_has_route_permission(
            request.user, 'Module_Savings_product_activate'
        )
        can_deactivate = user_has_route_permission(
            request.user, 'Module_Savings_product_deactivate'
        )
        rows = []
        for product in page_obj.object_list:
            actions = []
            if can_edit:
                actions.append(format_html(
                    '<a href="{}?popup=1" data-popup '
                    'data-popup-title="Edit savings product">Edit</a>',
                    reverse(
                        'savings:Module_Savings_product_edit',
                        args=[product.pk],
                    ),
                ))
            if product.is_active and can_deactivate:
                actions.append(format_html(
                    '<button class="btn btn-sm btn-outline-danger" '
                    'type="button" data-toggle-product="{}">Deactivate</button>',
                    reverse(
                        'savings:Module_Savings_product_deactivate',
                        args=[product.pk],
                    ),
                ))
            elif not product.is_active and can_activate:
                actions.append(format_html(
                    '<button class="btn btn-sm btn-outline-success" '
                    'type="button" data-toggle-product="{}">Activate</button>',
                    reverse(
                        'savings:Module_Savings_product_activate',
                        args=[product.pk],
                    ),
                ))
            rows.append({
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
                'status': 'Active' if product.is_active else 'Inactive',
                'actions': format_html_join(' | ', '{}', ((action,) for action in actions)),
            })
        return JsonResponse({
            'page': page_obj.number,
            'total': page_obj.paginator.num_pages,
            'records': page_obj.paginator.count,
            'rows': rows,
        })
    products = SavingsProduct.objects.order_by('code')
    initial_page = Paginator(products, 20).get_page(1)
    return render(request, 'savings/product_list.html', {
        'list_title': 'Savings products',
        'grid_url': request.path,
        'filter_layout': 'members',
        'initial_page_text': (
            f'Page {initial_page.number} of {initial_page.paginator.num_pages}'
        ),
        'add_url': (
            reverse('savings:Module_Savings_product_add')
            if user_has_route_permission(
                request.user, 'Module_Savings_product_add'
            )
            else ''
        ),
        'add_title': 'Create savings product',
        'list_filters': [
            {
                'name': 'code', 'label': 'Product code',
                'value': request.GET.get('code', ''),
                'placeholder': 'Product code',
            },
            {
                'name': 'name', 'label': 'Name',
                'value': request.GET.get('name', ''),
                'placeholder': 'Product name',
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': request.GET.get('status', ''),
                'options': [('active', 'Active'), ('inactive', 'Inactive')],
            },
        ],
        'list_columns': [
            {'name': 'code', 'label': 'Product code', 'width': 130},
            {'name': 'name', 'label': 'Name', 'width': 200},
            {'name': 'type', 'label': 'Type', 'width': 130},
            {'name': 'rate', 'label': 'Rate %', 'width': 110, 'align': 'right'},
            {'name': 'method', 'label': 'Interest method', 'width': 160, 'hidden': True},
            {'name': 'frequency', 'label': 'Posting', 'width': 120, 'hidden': True},
            {'name': 'opening_minimum', 'label': 'Opening min', 'width': 130, 'align': 'right', 'hidden': True},
            {'name': 'minimum', 'label': 'Min balance', 'width': 130, 'align': 'right', 'hidden': True},
            {'name': 'withdrawal_limit', 'label': 'Withdrawal max', 'width': 140, 'align': 'right', 'hidden': True},
            {'name': 'fee', 'label': 'Fee', 'width': 110, 'align': 'right'},
            {'name': 'status', 'label': 'Status', 'width': 100},
            {'name': 'actions', 'label': 'Actions', 'width': 150, 'sortable': False},
        ],
    })


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
    sort_fields = {
        'account_number': 'account_number',
        'product': 'product__name',
        'owner': 'member__first_name',
        'branch': 'branch__name',
        'balance': 'balance',
        'available': 'balance',
        'status': 'status',
    }
    sort_field = sort_fields.get(request.GET.get('sidx'), 'account_number')
    if request.GET.get('sord') == 'desc':
        sort_field = f'-{sort_field}'
    try:
        page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
    except (TypeError, ValueError):
        page_size = 20
    paginator = Paginator(accounts.order_by(sort_field, 'pk'), page_size)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    if request.GET.get('ajax'):
        can_statement = user_has_route_permission(
            request.user, 'Module_Savings_statement'
        )
        can_export = user_has_route_permission(
            request.user, 'Module_Savings_statement_export'
        )
        can_reactivate = user_has_route_permission(
            request.user, 'Module_Savings_reactivation_form'
        )
        can_close = user_has_route_permission(
            request.user, 'Module_Savings_close_account'
        )
        system_configuration = get_system_configuration()
        rows = []
        for account in page_obj.object_list:
            owner = (
                account.member.full_name
                if account.member_id
                else f'{account.group.name} (Group)'
            )
            actions = []
            if can_statement:
                actions.append(format_html(
                    '<a href="{}">Statement</a>',
                    reverse('savings:Module_Savings_statement', args=[account.pk]),
                ))
            if can_export:
                actions.append(format_html(
                    '<a href="{}">CSV</a>',
                    reverse('savings:Module_Savings_statement_export', args=[account.pk]),
                ))
            if account.status == SavingsAccount.STATUS_DORMANT and can_reactivate:
                actions.append(format_html(
                    '<a href="{}">Reactivate</a>',
                    reverse('savings:Module_Savings_reactivation_form', args=[account.pk]),
                ))
            if (
                account.balance == 0
                and account.reserved_balance == 0
                and account.status != 'closed'
                and can_close
            ):
                actions.append(format_html(
                    '<a href="{}" data-confirm data-confirm-title="Close account" '
                    'data-confirm-message="Close savings account {}?" '
                    'data-confirm-button="Close">Close</a>',
                    reverse('savings:Module_Savings_close_account', args=[account.pk]),
                    account.account_number,
                ))
            rows.append({
                'id': account.pk,
                'account_number': account.account_number,
                'product': account.product.name,
                'owner': owner,
                'branch': account.branch.name,
                'balance': config_money(account.balance, system_configuration),
                'available': config_money(
                    account.available_balance, system_configuration
                ),
                'status': account.get_status_display(),
                'actions': format_html_join(' | ', '{}', ((action,) for action in actions)),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'savings/account_list.html', {
        'list_title': 'Savings accounts',
        'grid_url': request.path,
        'initial_page_text': f'Page {page_obj.number} of {paginator.num_pages}',
        'add_url': (
            reverse('savings:Module_Savings_account_add')
            if user_has_route_permission(
                request.user, 'Module_Savings_account_add'
            )
            else ''
        ),
        'add_title': 'Open savings account',
        'list_filters': [
            {
                'name': 'q', 'label': 'Account / owner',
                'value': search, 'placeholder': 'Account number or owner',
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': status, 'options': SavingsAccount.STATUS_CHOICES,
            },
        ],
        'list_columns': [
            {'name': 'account_number', 'label': 'Account number', 'width': 150},
            {'name': 'product', 'label': 'Product', 'width': 160},
            {'name': 'owner', 'label': 'Owner', 'width': 200},
            {'name': 'branch', 'label': 'Branch', 'width': 150, 'hidden': True},
            {'name': 'balance', 'label': 'Balance', 'width': 120, 'align': 'right'},
            {'name': 'available', 'label': 'Available', 'width': 120, 'align': 'right'},
            {'name': 'status', 'label': 'Status', 'width': 100},
            {'name': 'actions', 'label': 'Actions', 'width': 180},
        ],
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
            _add_validation_error(form, exc)
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
    sort_fields = {
        'date': 'transaction_date',
        'account': 'account__account_number',
        'type': 'transaction_type',
        'amount': 'amount',
        'balance': 'balance_after',
        'status': 'status',
        'voucher': 'journal_entry__voucher_number',
        'maker_checker': 'created_by__username',
    }
    sort_field = sort_fields.get(request.GET.get('sidx'), 'pk')
    descending = request.GET.get('sord', 'desc').lower() == 'desc'
    if sort_field == 'pk':
        ordering = ['-pk']
    else:
        ordering = [f'-{sort_field}' if descending else sort_field, '-pk']
    transactions = transactions.order_by(*ordering)
    if request.GET.get('ajax') == '1':
        try:
            page_size = min(max(int(request.GET.get('rows', 20)), 1), 200)
        except (TypeError, ValueError):
            page_size = 20
        page_obj = Paginator(transactions, page_size).get_page(
            request.GET.get('page', 1)
        )
        can_approve = user_has_route_permission(
            request.user, 'Module_Savings_approve_withdrawal'
        )
        can_reject = user_has_route_permission(
            request.user, 'Module_Savings_rejection_form'
        )
        can_reverse = user_has_route_permission(
            request.user, 'Module_Savings_reversal_form'
        )
        can_statement = user_has_route_permission(
            request.user, 'Module_Savings_statement'
        )
        csrf_token = get_token(request)
        rows = []
        for item in page_obj.object_list:
            actions = []
            if can_statement:
                actions.append(format_html(
                    '<a class="btn btn-sm btn-outline-primary" href="{}">'
                    'Statement</a>',
                    reverse(
                        'savings:Module_Savings_statement',
                        args=[item.account_id],
                    ),
                ))
            if item.status == SavingsTransaction.STATUS_PENDING:
                if can_approve:
                    actions.append(format_html(
                        '<form class="d-inline" method="post" action="{}">'
                        '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
                        '<button class="btn btn-sm btn-outline-success" type="submit">'
                        'Approve</button></form>',
                        reverse(
                            'savings:Module_Savings_approve_withdrawal',
                            args=[item.pk],
                        ),
                        csrf_token,
                    ))
                if can_reject:
                    actions.append(format_html(
                        '<a class="btn btn-sm btn-outline-danger" href="{}?popup=1" '
                        'data-popup data-popup-title="Reject withdrawal">Reject</a>',
                        reverse(
                            'savings:Module_Savings_rejection_form',
                            args=[item.pk],
                        ),
                    ))
            elif item.status == SavingsTransaction.STATUS_POSTED and can_reverse:
                actions.append(format_html(
                    '<a class="btn btn-sm btn-outline-danger" href="{}?popup=1" '
                    'data-popup data-popup-title="Reverse savings transaction">'
                    'Reverse</a>',
                    reverse(
                        'savings:Module_Savings_reversal_form',
                        args=[item.pk],
                    ),
                ))
            rows.append({
                'id': item.pk,
                'date': item.transaction_date.isoformat(),
                'account': item.account.account_number,
                'type': item.get_transaction_type_display(),
                'amount': f'{item.amount:.2f}',
                'balance': f'{item.balance_after:.2f}',
                'status': item.get_status_display(),
                'voucher': item.journal_entry.voucher_number if item.journal_entry_id else '—',
                'maker_checker': (
                    f'{item.created_by.get_username()} / {item.approved_by.get_username()}'
                    if item.approved_by_id
                    else item.created_by.get_username()
                ),
                'actions': format_html_join(
                    ' ',
                    '{}',
                    ((action,) for action in actions),
                ),
            })
        return JsonResponse({
            'rows': rows,
            'page': page_obj.number,
            'total': page_obj.paginator.num_pages,
            'records': page_obj.paginator.count,
        })

    page_obj = Paginator(transactions, 20).get_page(request.GET.get('page', 1))
    list_actions = []
    for route_name, url_name, title, label in [
        (
            'Module_Savings_deposit',
            'Module_Savings_deposit',
            'Savings deposit',
            'Deposit',
        ),
        (
            'Module_Savings_withdraw',
            'Module_Savings_withdraw',
            'Savings withdrawal',
            'Withdraw',
        ),
        (
            'Module_Savings_fee',
            'Module_Savings_fee',
            'Charge product fee',
            'Charge fee',
        ),
        (
            'Module_Savings_interest',
            'Module_Savings_interest',
            'Post savings interest',
            'Post interest',
        ),
    ]:
        if user_has_route_permission(request.user, route_name):
            list_actions.append({
                'url': reverse(f'savings:{url_name}') + '?popup=1',
                'title': title,
                'label': label,
            })
    return render(request, 'savings/transaction_list.html', {
        'list_title': 'Transaction register',
        'grid_url': request.path,
        'filter_layout': 'members',
        'default_sort_name': 'date',
        'default_sort_order': 'desc',
        'initial_page_text': f'Page {page_obj.number} of {page_obj.paginator.num_pages}',
        'list_actions': list_actions,
        'statuses': SavingsTransaction.STATUS_CHOICES,
        'selected_status': status,
        'account_number': account_number,
        'list_filters': [
            {
                'name': 'account', 'label': 'Account number',
                'value': account_number, 'placeholder': 'Account number',
            },
            {
                'name': 'status', 'label': 'Status', 'type': 'select',
                'value': status, 'options': SavingsTransaction.STATUS_CHOICES,
            },
        ],
        'list_columns': [
            {'name': 'date', 'label': 'Date', 'width': 120},
            {'name': 'account', 'label': 'Account', 'width': 160},
            {'name': 'type', 'label': 'Type', 'width': 130},
            {'name': 'amount', 'label': 'Amount', 'width': 120, 'align': 'right'},
            {'name': 'balance', 'label': 'Balance', 'width': 120, 'align': 'right'},
            {'name': 'status', 'label': 'Status', 'width': 140},
            {'name': 'voucher', 'label': 'Voucher', 'width': 120, 'hidden': True},
            {'name': 'maker_checker', 'label': 'Maker / checker', 'width': 180, 'hidden': True},
            {'name': 'actions', 'label': 'Actions', 'width': 210, 'sortable': False},
        ],
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
            _add_validation_error(form, exc)
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
            _add_validation_error(form, exc)
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
            _add_validation_error(form, exc)
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
        _add_validation_error(form, exc)
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
            _add_validation_error(form, exc)
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
            _add_validation_error(form, exc)
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
