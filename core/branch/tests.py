import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connections
from django.db.models.query import QuerySet
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import reverse

from core.accounting.models import Account, SystemAccountMapping
from core.accounts.models import Permission, Role, RolePermission, UserRole
from core.accounts.permission_utils import sync_permissions
from core.common.context import current_branch_id_var, current_user_var
from core.common.upload_validation import detect_upload_mime, validate_kyc_file

from .day_end_service import BranchDayService
from .member_service import MemberService
from .models import (
    Branch,
    BranchClosedDay,
    BranchHoliday,
    Center,
    Member,
    MemberKYC,
    Staff,
    UserBranchAccess,
)


class BranchIsolationTests(TestCase):
    def setUp(self):
        self.branch_one = Branch.objects.create(name="Branch One", code="ONE")
        self.branch_two = Branch.objects.create(name="Branch Two", code="TWO")
        self.user = get_user_model().objects.create_user(
            username="branch-scope-user",
            password="A-strong-test-password-123",
            branch=self.branch_one,
        )
        self.center_one = Center.unscoped.create(
            branch=self.branch_one,
            name="Center One",
            code="CENTER-1",
        )
        self.center_two = Center.unscoped.create(
            branch=self.branch_two,
            name="Center Two",
            code="CENTER-2",
        )
        sync_permissions()


class BranchDayEndTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Day-End Branch",
            code="DAY-END",
            business_date=date(2026, 1, 16),
        )
        self.user = get_user_model().objects.create_user(
            username="day-end-manager",
            password="day-end-test-password",
            branch=self.branch,
        )
        manager_staff = Staff.unscoped.create(
            branch=self.branch,
            user=self.user,
            full_name="Day-End Manager",
            designation="Branch Manager",
        )
        self.branch.branch_manager = manager_staff
        self.branch.save(update_fields=["branch_manager"])
        self.request = RequestFactory().post("/branch/day-end/")
        self.request.user = self.user
        self.request.active_branch_id = None
        self.user_token = current_user_var.set(self.user)
        self.branch_token = current_branch_id_var.set(None)
        self.addCleanup(current_user_var.reset, self.user_token)
        self.addCleanup(current_branch_id_var.reset, self.branch_token)
        cash = Account.objects.create(
            code="DAY-CASH",
            name="Day-end cash",
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        SystemAccountMapping.objects.create(key="cash_in_hand", account=cash)

    def test_day_end_checklist_blocks_unfinished_collection_sheets(self):
        from core.collections.models import CollectionSheet

        officer = Staff.unscoped.create(
            branch=self.branch, full_name="Field Officer"
        )
        center = Center.unscoped.create(
            branch=self.branch,
            field_officer=officer,
            name="Day-End Center",
            code="DAY-END-CENTER",
        )
        CollectionSheet.unscoped.create(
            branch=self.branch,
            center=center,
            field_officer=officer,
            collection_date=self.branch.business_date,
            idempotency_key=uuid.uuid4(),
            generated_by=self.user,
        )

        with self.assertRaisesRegex(ValidationError, "not Posted"):
            BranchDayService(self.request).close(
                branch_id=self.branch.pk,
                cash_count=Decimal("0.00"),
            )

    def test_close_skips_weekend_and_holiday_and_reopen_is_audited(self):
        from core.audit.models import AuditLog

        BranchHoliday.objects.create(
            branch=self.branch, date=date(2026, 1, 19), name="Branch holiday"
        )
        closed_day = BranchDayService(self.request).close(
            branch_id=self.branch.pk,
            cash_count=Decimal("0.00"),
        )
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.business_date, date(2026, 1, 20))
        self.assertTrue(closed_day.is_closed)

        reopened = BranchDayService(self.request).reopen(
            branch_id=self.branch.pk,
            business_date=date(2026, 1, 16),
            reason="Correct a day-end entry",
        )
        self.branch.refresh_from_db()
        self.assertFalse(reopened.is_closed)
        self.assertEqual(self.branch.business_date, date(2026, 1, 16))
        self.assertTrue(
            AuditLog.objects.filter(
                action="ReopenBusinessDay",
                entity_name="BranchClosedDay",
                entity_id=str(closed_day.pk),
            ).exists()
        )

    def test_closed_business_date_rejects_journal_creation(self):
        from core.accounting.services import JournalService

        BranchClosedDay.objects.create(
            branch=self.branch,
            business_date=self.branch.business_date,
            cash_count=Decimal("0.00"),
            closed_by=self.user,
        )
        with self.assertRaisesRegex(ValidationError, "[Bb]usiness date.*is closed"):
            JournalService(self.request).create_entry(
                branch_id=self.branch.pk,
                journal_date=self.branch.business_date,
                narration="Closed-day posting",
            )

    def test_day_end_routes_have_permissions_and_post_only_mutations(self):
        sync_permissions()
        self.client.force_login(self.user)
        role = Role.objects.create(name="day-end-access-role")
        UserRole.objects.create(user=self.user, role=role)
        routes = {
            "Module_Branch_day_end_checklist": [],
            "Module_Branch_day_end_close": [],
            "Module_Branch_day_end_reopen": [],
            "Module_BranchHoliday_list": [],
            "Module_BranchHoliday_create": [],
            "Module_BranchHoliday_edit": [1],
        }
        for route_name, args in routes.items():
            response = self.client.get(reverse(f"branch:{route_name}", args=args))
            self.assertEqual(response.status_code, 403, route_name)
        for route_name in (
            "Module_Branch_day_end_close",
            "Module_Branch_day_end_reopen",
        ):
            permission = Permission.objects.get(route_name=route_name)
            RolePermission.objects.create(role=role, permission=permission)
            response = self.client.get(reverse(f"branch:{route_name}"))
            self.assertEqual(response.status_code, 405, route_name)

class BranchIsolationRemainderTests(BranchIsolationTests):
    def grant_route(self, route_name):
        role = Role.objects.create(name=f"branch-test-role-{Role.objects.count()}")
        permission = Permission.objects.get(route_name=route_name)
        RolePermission.objects.create(role=role, permission=permission)
        UserRole.objects.create(user=self.user, role=role)

    def test_scoped_manager_fails_closed_without_a_request_user(self):
        self.assertFalse(Center.objects.exists())

    def test_scoped_manager_limits_rows_to_user_branch(self):
        user_token = current_user_var.set(self.user)
        branch_token = current_branch_id_var.set(None)
        try:
            self.assertEqual(
                list(Center.objects.values_list("pk", flat=True)), [self.center_one.pk]
            )
        finally:
            current_branch_id_var.reset(branch_token)
            current_user_var.reset(user_token)

    def test_moving_branch_updates_three_level_descendant_paths(self):
        head_one = Branch.unscoped.create(
            name="Head One", code="HEAD-1", branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE
        )
        head_two = Branch.unscoped.create(
            name="Head Two", code="HEAD-2", branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE
        )
        region = Branch.objects.create(
            name="Region",
            code="REGION",
            branch_type=Branch.BRANCH_TYPE_REGION,
            parent=head_one,
        )
        area = Branch.objects.create(
            name="Area",
            code="AREA",
            branch_type=Branch.BRANCH_TYPE_AREA,
            parent=region,
        )
        branch = Branch.objects.create(
            name="Branch Unit",
            code="UNIT",
            branch_type=Branch.BRANCH_TYPE_BRANCH,
            parent=area,
        )
        self.user.branch = region
        self.user.save(update_fields=["branch"])
        descendant_center = Center.unscoped.create(
            branch=branch,
            name="Descendant Center",
            code="DESCENDANT-CENTER",
        )
        outside_center = Center.unscoped.create(
            branch=head_two,
            name="Outside Center",
            code="OUTSIDE-CENTER",
        )

        region.refresh_from_db()
        area.refresh_from_db()
        branch.refresh_from_db()
        expected_prefix = f"/{head_one.pk}/{region.pk}/{area.pk}/"
        self.assertEqual(region.hierarchy_path, f"/{head_one.pk}/{region.pk}/")
        self.assertEqual(area.hierarchy_path, expected_prefix)
        self.assertEqual(branch.hierarchy_path, f"{expected_prefix}{branch.pk}/")

        region.parent = head_two
        region.save()
        region.refresh_from_db()
        area.refresh_from_db()
        branch.refresh_from_db()

        expected_prefix = f"/{head_two.pk}/{region.pk}/{area.pk}/"
        self.assertEqual(region.hierarchy_path, f"/{head_two.pk}/{region.pk}/")
        self.assertEqual(area.hierarchy_path, expected_prefix)
        self.assertEqual(branch.hierarchy_path, f"{expected_prefix}{branch.pk}/")
        user_token = current_user_var.set(self.user)
        branch_token = current_branch_id_var.set(None)
        try:
            visible_center_ids = set(Center.objects.values_list("pk", flat=True))
        finally:
            current_branch_id_var.reset(branch_token)
            current_user_var.reset(user_token)
        self.assertEqual(visible_center_ids, {descendant_center.pk})
        self.assertNotIn(outside_center.pk, visible_center_ids)

    def test_move_into_descendant_is_rejected_without_creating_cycle(self):
        head = Branch.unscoped.create(
            name="Head", code="HEAD-CYCLE", branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE
        )
        region = Branch.objects.create(
            name="Region",
            code="REGION-CYCLE",
            branch_type=Branch.BRANCH_TYPE_REGION,
            parent=head,
        )
        area = Branch.objects.create(
            name="Area",
            code="AREA-CYCLE",
            branch_type=Branch.BRANCH_TYPE_AREA,
            parent=region,
        )

        head.parent = area
        with self.assertRaisesMessage(
            ValidationError, "Moving this unit would create a hierarchy cycle."
        ):
            head.save()

        head.refresh_from_db()
        region.refresh_from_db()
        area.refresh_from_db()
        self.assertIsNone(head.parent_id)
        self.assertEqual(region.hierarchy_path, f"/{head.pk}/{region.pk}/")
        self.assertEqual(area.hierarchy_path, f"/{head.pk}/{region.pk}/{area.pk}/")

    def test_move_locks_branch_and_descendants_for_update(self):
        head_one = Branch.unscoped.create(
            name="Head Lock One",
            code="HEAD-LOCK-1",
            branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE,
        )
        head_two = Branch.unscoped.create(
            name="Head Lock Two",
            code="HEAD-LOCK-2",
            branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE,
        )
        region = Branch.objects.create(
            name="Region Lock",
            code="REGION-LOCK",
            branch_type=Branch.BRANCH_TYPE_REGION,
            parent=head_one,
        )
        area = Branch.objects.create(
            name="Area Lock",
            code="AREA-LOCK",
            branch_type=Branch.BRANCH_TYPE_AREA,
            parent=region,
        )

        with patch(
            "django.db.models.query.QuerySet.select_for_update",
            autospec=True,
            side_effect=QuerySet.select_for_update,
        ) as locked:
            region.parent = head_two
            region.save()

        self.assertGreaterEqual(locked.call_count, 2)
        area.refresh_from_db()
        self.assertEqual(area.hierarchy_path, f"/{head_two.pk}/{region.pk}/{area.pk}/")

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_explicit_branch_access_can_be_selected_but_not_forged(self):
        UserBranchAccess.objects.create(user=self.user, branch=self.branch_two)
        self.assertEqual(
            self.user.accessible_branch_ids(),
            {self.branch_one.pk, self.branch_two.pk},
        )
        self.assertEqual(
            self.user.accessible_branch_ids(self.branch_two.pk), {self.branch_two.pk}
        )

        self.client.force_login(self.user)
        response = self.client.post(
            "/branch/switch/",
            {"branch_id": str(self.branch_two.pk)},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["active_branch_id"], self.branch_two.pk)

        response = self.client.post(
            "/branch/switch/", {"branch_id": "999999"}, secure=True
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_switch_rejects_wrong_method_and_deletes_branch_softly(self):
        self.grant_route("Module_Branch_delete_branch")
        self.client.force_login(self.user)

        response = self.client.get("/branch/switch/", secure=True)
        self.assertEqual(response.status_code, 405)

        self.center_one.is_active = False
        self.center_one.save(update_fields=["is_active"])
        response = self.client.post(
            f"/branch/delete/{self.branch_one.pk}/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.branch_one.refresh_from_db()
        self.assertFalse(self.branch_one.is_active)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_branch_tree_still_requires_its_route_permission(self):
        self.client.force_login(self.user)

        denied = self.client.get("/branch/tree/", secure=True)
        self.assertEqual(denied.status_code, 403)

        self.grant_route("Module_Branch_tree")
        allowed = self.client.get("/branch/tree/", secure=True)
        self.assertEqual(allowed.status_code, 200)

    def test_member_codes_are_branch_prefixed_and_stale_edits_are_rejected(self):
        request = RequestFactory().post("/branch/members/add/")
        request.user = self.user
        request.active_branch_id = None

        member = Member(
            branch=self.branch_one,
            first_name="Amina",
            last_name="Begum",
        )
        created = MemberService(request).create(member)
        self.assertEqual(created.member_code, "ONE-000001")

        created.first_name = "Changed"
        with self.assertRaises(ValidationError):
            MemberService(request).update(created, expected_version=0)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_member_detail_renders_status_choices_from_view_context(self):
        self.grant_route("Module_Members_detail")
        member = Member.unscoped.create(
            branch=self.branch_one,
            member_code="ONE-000001",
            first_name="Amina",
            last_name="Begum",
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/branch/members/{member.pk}/", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change status")
        self.assertContains(response, "Pending")

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_member_detail_cannot_be_opened_from_another_branch(self):
        self.grant_route("Module_Members_detail")
        member = Member.unscoped.create(
            branch=self.branch_two,
            member_code="TWO-000001",
            first_name="Amina",
            last_name="Begum",
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/branch/members/{member.pk}/", secure=True)

        self.assertEqual(response.status_code, 404)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_kyc_rejection_requires_a_reason_and_verification_is_audited(self):
        from core.audit.models import AuditLog

        self.grant_route("Module_Members_kyc_verify")
        member = Member.unscoped.create(
            branch=self.branch_one,
            member_code="ONE-000002",
            first_name="Amina",
            last_name="Begum",
        )
        document = MemberKYC.objects.create(
            member=member,
            document_type=MemberKYC.DOC_TYPE_NATIONAL_ID,
            document_number="ID-12345",
        )
        self.client.force_login(self.user)

        rejected = self.client.post(
            f"/branch/members/kyc/verify/{document.pk}/",
            {"status": "rejected"},
            secure=True,
        )
        self.assertEqual(rejected.status_code, 400)
        document.refresh_from_db()
        self.assertEqual(document.status, MemberKYC.STATUS_PENDING)

        verified = self.client.post(
            f"/branch/members/kyc/verify/{document.pk}/",
            {"status": "verified"},
            secure=True,
        )
        self.assertEqual(verified.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, MemberKYC.STATUS_VERIFIED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="Verify",
                entity_name="MemberKYC",
                entity_id=str(document.pk),
            ).exists()
        )

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_kyc_upload_rejects_mismatched_file_signature(self):
        self.grant_route("Module_Members_kyc")
        member = Member.unscoped.create(
            branch=self.branch_one,
            member_code="ONE-000003",
            first_name="Amina",
            last_name="Begum",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"/branch/members/kyc/{member.pk}/",
            {
                "document_type": MemberKYC.DOC_TYPE_NATIONAL_ID,
                "document_number": "ID-12345",
                "file": SimpleUploadedFile("identity.pdf", b"not a real PDF"),
            },
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(MemberKYC.objects.filter(member=member).exists())

    def test_upload_validation_checks_file_signature(self):
        valid_pdf = SimpleUploadedFile("identity.pdf", b"%PDF-1.7\nfile")
        self.assertEqual(detect_upload_mime(valid_pdf), "application/pdf")
        validate_kyc_file(valid_pdf)

        invalid_file = SimpleUploadedFile("identity.pdf", b"<html>not a PDF</html>")
        self.assertIsNone(detect_upload_mime(invalid_file))
        with self.assertRaises(ValidationError):
            validate_kyc_file(invalid_file)


class ConcurrentBranchMoveTests(TransactionTestCase):
    def test_simultaneous_moves_cannot_create_a_hierarchy_cycle(self):
        first = Branch.unscoped.create(
            name="Concurrent Head One",
            code="CONCURRENT-1",
            branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE,
        )
        second = Branch.unscoped.create(
            name="Concurrent Head Two",
            code="CONCURRENT-2",
            branch_type=Branch.BRANCH_TYPE_HEAD_OFFICE,
        )
        barrier = Barrier(2)

        def move(source_id, target_id):
            close_old_connections()
            try:
                source = Branch.unscoped.get(pk=source_id)
                source.parent = Branch.unscoped.get(pk=target_id)
                barrier.wait(timeout=10)
                source.save()
                return "moved"
            except ValidationError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda pair: move(*pair),
                    ((first.pk, second.pk), (second.pk, first.pk)),
                )
            )

        self.assertCountEqual(outcomes, ["moved", "rejected"])
        first.refresh_from_db()
        second.refresh_from_db()
        first_is_child = first.parent_id == second.pk
        second_is_child = second.parent_id == first.pk
        self.assertNotEqual(first_is_child, second_is_child)
        if first_is_child:
            self.assertEqual(first.hierarchy_path, f"/{second.pk}/{first.pk}/")
            self.assertEqual(second.hierarchy_path, f"/{second.pk}/")
        else:
            self.assertEqual(second.hierarchy_path, f"/{first.pk}/{second.pk}/")
            self.assertEqual(first.hierarchy_path, f"/{first.pk}/")
        self.assertEqual(
            first.hierarchy_path.count("/") + second.hierarchy_path.count("/"),
            5,
        )
