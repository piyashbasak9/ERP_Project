from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_POST

from core.audit.services import log_action
from core.common.popup import popup_json_response, render_popup_form

from .day_end_service import BranchDayService
from .forms import (
    BranchForm,
    BranchHolidayForm,
    CenterForm,
    DayEndCloseForm,
    DayEndReopenForm,
    GroupForm,
    MemberForm,
    MemberKYCForm,
    MemberStatusForm,
    StaffForm,
)
from .member_service import MemberService
from .models import Branch, BranchHoliday, Center, Group, Member, MemberKYC, Staff
from .service import BranchReadService, BranchWriteService

# Create your views here.


def _serialize_branch(branch):
    branch_id = branch.get('id') if isinstance(branch, dict) else branch.id
    edit_url = reverse('branch:Module_Branch_edit_branch', args=[branch_id])
    delete_url = reverse('branch:Module_Branch_delete_branch', args=[branch_id])
    
    action_html = (
        f'<div class="d-flex gap-2 justify-content-center">'
        f'<a href="{edit_url}?popup=1" class="btn btn-sm btn-outline-primary" title="Edit" data-popup data-popup-title="Edit branch">✏️</a>'
        f'<a href="{delete_url}" class="btn btn-sm btn-outline-danger" title="Delete" data-confirm data-confirm-title="Delete branch" data-confirm-message="Delete this branch? This action cannot be undone." data-confirm-button="Delete">🗑️</a>'
        f'</div>'
    )

    if isinstance(branch, dict):
        return {
            'id': branch.get('id'),
            'name': branch.get('name'),
            'code': branch.get('code'),
            'is_active': branch.get('is_active'),
            'created_by': branch.get('created_by'),
            'created_at': branch.get('created_at'),
            'updated_by': branch.get('updated_by'),
            'updated_at': branch.get('updated_at'),
            'actions': action_html
        }

    return {
        'id': branch.id,
        'name': branch.name,
        'code': branch.code,
        'is_active': branch.is_active,
        'created_by': branch.created_by_name if branch.created_by else None,
        'created_at': branch.created_at,
        'updated_by': branch.updated_by_name if branch.updated_by else None,
        'updated_at': branch.updated_at,
        'actions': action_html
    }



def index(request):
    data = BranchReadService(request).all()
    try:
        rows = min(max(int(request.GET.get('rows', 20)), 1), 100)
    except (TypeError, ValueError):
        rows = 20
    paginator = Paginator(data, rows)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if request.GET.get('ajax'):
        return JsonResponse({
            'rows': [_serialize_branch(item) for item in page_obj.object_list],
            'page': page_obj.number,
            'total': paginator.num_pages,
            'records': paginator.count,
        })

    return render(request, 'branch/index.html')



def add(request):
    form = BranchForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        try:
            instance = form.save(commit=False)
            branch = BranchWriteService(request).create({
                field: getattr(instance, field)
                for field in form.Meta.fields
            })
        except ValidationError as error:
            form.add_error(None, error)
        else:
            log_action(
                'Create',
                'Branch',
                branch.pk,
                new_values={
                    'name': branch.name,
                    'code': branch.code,
                    'branch_type': branch.branch_type,
                    'parent_id': branch.parent_id,
                },
                branch_id=branch.pk,
            )
            message = f"'{branch.name}' was created successfully."
            response = popup_json_response(
                request, message=message, data={'id': branch.pk}
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('branch:Module_Branch_index_branch')
    return render_popup_form(request, 'branch/add.html', {'form': form})


def edit(request, pk):
    branch = get_object_or_404(BranchReadService(request)._scoped_queryset(), pk=pk, is_active=True)
    form = BranchForm(request.POST or None, instance=branch, request=request)
    if request.method == 'POST' and form.is_valid():
        instance = form.save(commit=False)
        instance.updated_by = request.user
        old_values = {
            'name': branch.name,
            'code': branch.code,
            'branch_type': branch.branch_type,
            'parent_id': branch.parent_id,
        }
        try:
            updated = BranchWriteService(request).update(
                pk,
                {field: getattr(instance, field) for field in form.Meta.fields},
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if updated:
                log_action(
                    'Update',
                    'Branch',
                    updated.pk,
                    old_values=old_values,
                    new_values={
                        'name': updated.name,
                        'code': updated.code,
                        'branch_type': updated.branch_type,
                        'parent_id': updated.parent_id,
                    },
                    branch_id=updated.pk,
                )
                message = f"'{updated.name}' was updated successfully."
                response = popup_json_response(
                    request, message=message, data={'id': updated.pk}
                )
                if response is not None:
                    return response
                messages.success(request, message)
                return redirect('branch:Module_Branch_index_branch')
            return JsonResponse({'success': False, 'message': 'Branch not found.'}, status=404)
    return render_popup_form(
        request, 'branch/add.html', {'pk': pk, 'form': form, 'branch': branch}
    )



@require_POST
def delete(request, pk):
    try:
        branch = BranchWriteService(request).delete(pk)
    except ValidationError as error:
        message = '; '.join(error.messages)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': message}, status=400)
        messages.error(request, message)
        return redirect('branch:Module_Branch_index_branch')
    if not branch:
        message = f"Failed to delete branch '{pk}'."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': message}, status=400)
        messages.error(request, message)
        return redirect('branch:Module_Branch_index_branch')

    log_action(
        'Deactivate',
        'Branch',
        branch.pk,
        old_values={'is_active': True},
        new_values={'is_active': False},
        branch_id=branch.pk,
    )
    message = f"'{branch.name}' deleted successfully."
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': message})
    messages.success(request, f"✅ {message}")
    return redirect('branch:Module_Branch_index_branch')


@require_GET
def tree(request):
    allowed_ids = request.user.accessible_branch_ids(request.active_branch_id)
    branches = Branch.unscoped.filter(pk__in=allowed_ids, is_active=True).select_related('parent')
    return render(request, 'branch/tree.html', {'branches': branches})


@require_POST
def switch(request):
    raw_branch_id = request.POST.get('branch_id', '')
    if raw_branch_id:
        try:
            branch_id = int(raw_branch_id)
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Select a valid branch.'}, status=400)
        if branch_id not in request.user.accessible_branch_ids():
            return JsonResponse({'success': False, 'message': 'You cannot access that branch.'}, status=403)
        request.session['active_branch_id'] = branch_id
    else:
        request.session.pop('active_branch_id', None)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Active branch changed.'})
    redirect_to = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(redirect_to, allowed_hosts={request.get_host()}):
        redirect_to = reverse('branch:Module_Branch_index_branch')
    return redirect(redirect_to)


@require_GET
def member_list(request):
    queryset = Member.objects.select_related('branch', 'center', 'group').order_by('member_code')
    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            models.Q(member_code__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
        )
    selected_status = request.GET.get('status', '')
    if selected_status in dict(Member.STATUS_CHOICES):
        queryset = queryset.filter(status=selected_status)
    page_obj = Paginator(queryset, 25).get_page(request.GET.get('page', 1))
    return render(request, 'members/list.html', {
        'page_obj': page_obj,
        'search': search,
        'selected_status': selected_status,
        'statuses': Member.STATUS_CHOICES,
    })


def _audit_member_sensitive_read(member):
    if member.national_id or member.other_id_numbers:
        log_action(
            'ViewSensitiveData',
            'Member',
            member.pk,
            new_values={'fields': ['national_id', 'other_id_numbers']},
            branch_id=member.branch_id,
        )


@require_GET
def member_detail(request, pk):
    member = get_object_or_404(
        Member.objects.select_related('branch', 'center', 'group').prefetch_related(
            'nominees', 'kyc_documents', 'status_history'
        ),
        pk=pk,
    )
    _audit_member_sensitive_read(member)
    return render(request, 'members/detail.html', {
        'member': member,
        'statuses': Member.STATUS_CHOICES,
    })


def member_add(request):
    form = MemberForm(request.POST or None, request.FILES or None, request=request)
    if request.method == 'POST' and form.is_valid():
        member = form.save(commit=False)
        try:
            member = MemberService(request).create(member)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            log_action(
                'Create',
                'Member',
                member.pk,
                new_values={
                    'member_code': member.member_code,
                    'status': member.status,
                    'branch_id': member.branch_id,
                },
                branch_id=member.branch_id,
            )
            message = 'Member registered successfully.'
            response = popup_json_response(
                request,
                message=message,
                data={'id': member.pk},
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('branch:Module_Members_detail', pk=member.pk)
    return render_popup_form(
        request,
        'members/form.html',
        {'form': form, 'title': 'Register member'},
        status=400 if request.method == 'POST' else 200,
    )


def member_edit(request, pk):
    member = get_object_or_404(Member.objects, pk=pk)
    _audit_member_sensitive_read(member)
    form = MemberForm(request.POST or None, request.FILES or None, instance=member, request=request)
    if request.method == 'POST' and form.is_valid():
        updated_form_member = form.save(commit=False)
        try:
            member = MemberService(request).update(updated_form_member, request.POST.get('version'))
        except Member.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Member not found.'}, status=404)
        except (ValidationError, TypeError, ValueError) as error:
            form.add_error(None, error)
        else:
            log_action(
                'Update',
                'Member',
                member.pk,
                new_values={
                    'member_code': member.member_code,
                    'status': member.status,
                    'branch_id': member.branch_id,
                },
                branch_id=member.branch_id,
            )
            message = 'Member profile updated.'
            response = popup_json_response(
                request,
                message=message,
                data={'id': member.pk},
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect('branch:Module_Members_detail', pk=member.pk)
    return render_popup_form(
        request,
        'members/form.html',
        {
            'form': form,
            'title': f'Edit member {member.member_code}',
            'member': member,
            'version': member.version,
        },
        status=400 if request.method == 'POST' else 200,
    )


@require_POST
def member_status(request, pk):
    member = get_object_or_404(Member.objects, pk=pk)
    form = MemberStatusForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'message': 'Provide a valid status and reason.'}, status=400)
    old_status = member.status
    try:
        member = MemberService(request).change_status(
            member,
            form.cleaned_data['status'],
            form.cleaned_data['reason'],
        )
    except ValidationError as error:
        return JsonResponse({'success': False, 'message': '; '.join(error.messages)}, status=400)
    log_action(
        'StatusChange',
        'Member',
        member.pk,
        old_values={'status': old_status},
        new_values={'status': member.status},
        remarks=form.cleaned_data['reason'],
        branch_id=member.branch_id,
    )
    messages.success(request, 'Member status updated.')
    return redirect('branch:Module_Members_detail', pk=member.pk)


def member_kyc(request, pk):
    member = get_object_or_404(Member.objects, pk=pk)
    form = MemberKYCForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        document = form.save(commit=False)
        document.member = member
        document.full_clean()
        document.save()
        log_action(
            'Create',
            'MemberKYC',
            document.pk,
            new_values={'document_type': document.document_type, 'status': document.status},
            branch_id=member.branch_id,
        )
        response = popup_json_response(
            request,
            message='KYC document uploaded successfully.',
            data={'id': document.pk},
        )
        if response is not None:
            return response
        messages.success(request, 'KYC document uploaded for verification.')
        return redirect('branch:Module_Members_detail', pk=member.pk)
    return render_popup_form(
        request,
        'members/kyc_form.html',
        {'member': member, 'form': form},
        status=400 if request.method == 'POST' else 200,
    )


@require_POST
def member_kyc_verify(request, document_id):
    allowed_branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    document = get_object_or_404(
        MemberKYC.objects.select_related('member').filter(member__branch_id__in=allowed_branch_ids),
        pk=document_id,
    )
    status = request.POST.get('status')
    reason = request.POST.get('reason', '').strip()
    if status not in {MemberKYC.STATUS_VERIFIED, MemberKYC.STATUS_REJECTED}:
        return JsonResponse({'success': False, 'message': 'Select Verified or Rejected.'}, status=400)
    if status == MemberKYC.STATUS_REJECTED and not reason:
        return JsonResponse({'success': False, 'message': 'A rejection reason is required.'}, status=400)

    old_status = document.status
    document.status = status
    document.is_verified = status == MemberKYC.STATUS_VERIFIED
    document.verified_by = request.user
    document.verified_at = timezone.now()
    document.rejection_reason = reason if status == MemberKYC.STATUS_REJECTED else ''
    document.full_clean()
    document.save(update_fields=[
        'status', 'is_verified', 'verified_by', 'verified_at', 'rejection_reason',
    ])
    log_action(
        'Verify' if document.is_verified else 'Reject',
        'MemberKYC',
        document.pk,
        old_values={'status': old_status},
        new_values={'status': document.status},
        remarks=reason,
        branch_id=document.member.branch_id,
    )
    messages.success(request, f'KYC document {document.status}.')
    return redirect('branch:Module_Members_detail', pk=document.member_id)


@require_GET
def private_member_file(request, kind, file_id):
    allowed_branch_ids = request.user.accessible_branch_ids(request.active_branch_id)
    if kind == 'photo':
        member = get_object_or_404(Member.objects, pk=file_id)
        stored_file = member.photo
        content_type = 'image/jpeg'
        filename = f'{member.member_code}-photo.jpg'
        disposition = 'inline'
        entity_name = 'MemberPhoto'
        entity_id = member.pk
        branch_id = member.branch_id
    elif kind == 'kyc':
        document = get_object_or_404(
            MemberKYC.objects.select_related('member').filter(member__branch_id__in=allowed_branch_ids),
            pk=file_id,
        )
        stored_file = document.file
        content_type = document.mime_type if document.mime_type in {
            'image/jpeg', 'image/png', 'application/pdf',
        } else 'application/octet-stream'
        filename = document.file_name or 'kyc-document'
        disposition = 'attachment'
        entity_name = 'MemberKYC'
        entity_id = document.pk
        branch_id = document.member.branch_id
    else:
        return JsonResponse({'success': False, 'message': 'File not found.'}, status=404)

    if not stored_file:
        return JsonResponse({'success': False, 'message': 'File not found.'}, status=404)

    log_action('Download', entity_name, entity_id, branch_id=branch_id)
    response = FileResponse(stored_file.open('rb'), content_type=content_type)
    response['Content-Disposition'] = f'{disposition}; filename="{get_valid_filename(filename)}"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


ORGANIZATION_RESOURCES = {
    'centers': (Center, CenterForm, 'name', 'Center', 'Module_Center_list', 'Module_Center_add', 'Module_Center_edit'),
    'groups': (Group, GroupForm, 'name', 'Group', 'Module_Group_list', 'Module_Group_add', 'Module_Group_edit'),
    'staff': (Staff, StaffForm, 'full_name', 'Staff', 'Module_Staff_list', 'Module_Staff_add', 'Module_Staff_edit'),
}


@require_GET
def organization_list(request, resource):
    model, _, order_field, singular, _, add_route, edit_route = ORGANIZATION_RESOURCES[resource]
    queryset = model.objects.filter(is_active=True).order_by(order_field)
    page_obj = Paginator(queryset, 25).get_page(request.GET.get('page', 1))
    for record in page_obj.object_list:
        record.edit_url = reverse(f'branch:{edit_route}', args=[record.pk])
    return render(request, 'branch/organization_list.html', {
        'resource': resource,
        'title': singular if resource == 'staff' else f'{singular}s',
        'singular': singular,
        'add_url': reverse(f'branch:{add_route}'),
        'page_obj': page_obj,
    })


@transaction.atomic
def organization_form(request, resource, pk=None):
    model, form_class, _, singular, list_route, _, _ = ORGANIZATION_RESOURCES[resource]
    instance = get_object_or_404(model.objects, pk=pk, is_active=True) if pk else None
    form = form_class(request.POST or None, instance=instance, request=request)
    if request.method == 'POST' and form.is_valid():
        record = form.save(commit=False)
        try:
            record.full_clean()
            record.save()
            form.save_m2m()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            log_action(
                'Update' if instance else 'Create',
                model.__name__,
                record.pk,
                new_values={'name': getattr(record, 'name', getattr(record, 'full_name', ''))},
                branch_id=record.branch_id,
            )
            message = f'{singular} saved successfully.'
            response = popup_json_response(
                request,
                message=message,
                data={'id': record.pk},
            )
            if response is not None:
                return response
            messages.success(request, message)
            return redirect(f'branch:{list_route}')
    return render_popup_form(request, 'branch/organization_form.html', {
        'resource': resource,
        'title': f'Edit {singular}' if instance else f'Create {singular}',
        'list_url': reverse(f'branch:{list_route}'),
        'form': form,
        'pk': pk,
    }, status=400 if request.method == 'POST' else 200)


@require_GET
def day_end_checklist(request):
    raw_branch_id = request.GET.get("branch") or request.active_branch_id or request.user.branch_id
    try:
        branch_id = int(raw_branch_id)
        summary = BranchDayService(request).checklist(branch_id=branch_id)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "Select a valid branch."}, status=400)
    except Branch.DoesNotExist:
        from django.http import Http404

        raise Http404
    except PermissionDenied as error:
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    form = DayEndCloseForm(
        request=request,
        initial={"branch": summary["branch"], "cash_count": summary["cash_book"]},
    )
    reopen_form = DayEndReopenForm(
        request=request, initial={"branch": summary["branch"]}
    )
    return render(
        request,
        "branch/day_end_checklist.html",
        {"summary": summary, "form": form, "reopen_form": reopen_form},
    )


@require_POST
def day_end_close(request):
    form = DayEndCloseForm(request.POST, request=request)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "message": "Correct the day-end details.", "errors": form.errors},
            status=400,
        )
    try:
        BranchDayService(request).close(
            branch_id=form.cleaned_data["branch"].pk,
            cash_count=form.cleaned_data["cash_count"],
            cash_difference_reason=form.cleaned_data["cash_difference_reason"],
            carryover_note=form.cleaned_data["carryover_note"],
        )
    except (ValidationError, PermissionDenied) as error:
        if isinstance(error, ValidationError):
            return JsonResponse(
                {"success": False, "message": "; ".join(error.messages)}, status=400
            )
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    messages.success(request, "Business day closed.")
    return redirect("branch:Module_Branch_day_end_checklist")


@require_POST
def day_end_reopen(request):
    form = DayEndReopenForm(request.POST, request=request)
    if not form.is_valid():
        return JsonResponse(
            {"success": False, "message": "Correct the reopening details.", "errors": form.errors},
            status=400,
        )
    try:
        BranchDayService(request).reopen(
            branch_id=form.cleaned_data["branch"].pk,
            business_date=form.cleaned_data["business_date"],
            reason=form.cleaned_data["reason"],
        )
    except (ValidationError, PermissionDenied) as error:
        if isinstance(error, ValidationError):
            return JsonResponse(
                {"success": False, "message": "; ".join(error.messages)}, status=400
            )
        return JsonResponse({"success": False, "message": str(error)}, status=403)
    messages.success(request, "Business day reopened.")
    return redirect("branch:Module_Branch_day_end_checklist")


@require_GET
def holiday_list(request):
    allowed = request.user.accessible_branch_ids(request.active_branch_id)
    holidays = BranchHoliday.objects.filter(branch_id__in=allowed).select_related(
        "branch"
    )
    return render(request, "branch/holiday_list.html", {"holidays": holidays})


def holiday_form(request, pk=None):
    allowed = request.user.accessible_branch_ids(request.active_branch_id)
    holiday = None
    if pk is not None:
        holiday = get_object_or_404(
            BranchHoliday.objects.filter(branch_id__in=allowed), pk=pk
        )
    form = BranchHolidayForm(request.POST or None, request=request, instance=holiday)
    if request.method == "POST" and form.is_valid():
        old_values = (
            {
                "branch_id": holiday.branch_id,
                "date": holiday.date.isoformat(),
                "name": holiday.name,
                "is_active": holiday.is_active,
            }
            if holiday
            else {}
        )
        instance = form.save(commit=False)
        instance.branch_id = form.cleaned_data["branch"].pk
        try:
            instance.full_clean()
            instance.save()
        except ValidationError as error:
            form.add_error(None, error)
        else:
            log_action(
                "Update" if holiday else "Create",
                "BranchHoliday",
                instance.pk,
                old_values=old_values,
                new_values={
                    "branch_id": instance.branch_id,
                    "date": instance.date.isoformat(),
                    "name": instance.name,
                    "is_active": instance.is_active,
                },
                branch_id=instance.branch_id,
            )
            response = popup_json_response(
                request, message="Holiday saved.", data={"id": instance.pk}
            )
            if response is not None:
                return response
            messages.success(request, "Holiday saved.")
            return redirect("branch:Module_BranchHoliday_list")
    return render_popup_form(
        request,
        "branch/holiday_form.html",
        {"form": form, "title": "Edit holiday" if holiday else "Add holiday"},
        status=400 if request.method == "POST" else 200,
    )
