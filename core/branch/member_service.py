from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Branch, Member, MemberStatusHistory


class MemberService:
    def __init__(self, request):
        self.request = request

    @transaction.atomic
    def create(self, member):
        branch = Branch.unscoped.select_for_update().filter(pk=member.branch_id, is_active=True).first()
        if not branch or member.branch_id not in self.request.user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        ):
            raise ValidationError({'branch': 'You cannot create a member in this branch.'})

        prefix = f'{branch.code}-'
        latest_code = (
            Member.unscoped.filter(branch=branch, member_code__startswith=prefix)
            .order_by('-member_code')
            .values_list('member_code', flat=True)
            .first()
        )
        try:
            sequence = int(latest_code[len(prefix):]) + 1 if latest_code else 1
        except ValueError as exc:
            raise ValidationError({'member_code': 'The existing member numbering sequence is invalid.'}) from exc

        member.member_code = f'{prefix}{sequence:06d}'
        member.created_by = self.request.user
        member.updated_by = self.request.user
        member.full_clean()
        member.save()
        return member

    @transaction.atomic
    def update(self, member, expected_version=None):
        existing = Member.unscoped.select_for_update().filter(pk=member.pk).first()
        if not existing or existing.branch_id not in self.request.user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        ):
            raise Member.DoesNotExist

        if expected_version is None:
            raise ValidationError('The member version is required to save changes.')
        try:
            submitted_version = int(expected_version)
        except (TypeError, ValueError) as exc:
            raise ValidationError('The member version is invalid.') from exc
        if submitted_version != existing.version:
            raise ValidationError('This member was changed by another user. Reload and try again.')

        existing_data = {
            field.name: getattr(member, field.name)
            for field in member._meta.concrete_fields
            if field.name not in {'id', 'member_code', 'created_at', 'created_by', 'joined_at', 'version'}
        }
        for field_name, value in existing_data.items():
            setattr(existing, field_name, value)
        existing.updated_by = self.request.user
        existing.version += 1
        existing.full_clean()
        existing.save()
        return existing

    @transaction.atomic
    def change_status(self, member, new_status, reason):
        if not reason.strip():
            raise ValidationError({'reason': 'A reason is required for a status change.'})
        existing = Member.unscoped.select_for_update().filter(pk=member.pk).first()
        if not existing or existing.branch_id not in self.request.user.accessible_branch_ids(
            getattr(self.request, 'active_branch_id', None)
        ):
            raise Member.DoesNotExist
        if existing.status == new_status:
            raise ValidationError({'status': 'The member already has this status.'})

        old_status = existing.status
        existing.status = new_status
        existing.updated_by = self.request.user
        existing.version += 1
        existing.save(update_fields=['status', 'updated_by', 'updated_at', 'version'])
        MemberStatusHistory.objects.create(
            member=existing,
            old_status=old_status,
            new_status=new_status,
            reason=reason.strip(),
            changed_by=self.request.user,
        )
        return existing
