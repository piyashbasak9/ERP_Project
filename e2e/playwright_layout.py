import os
import subprocess
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import RequestFactory
from django.test.client import Client
from django.urls import reverse
from django.utils import timezone

from core.branch.models import Branch, Member
from core.savings.models import SavingsProduct
from core.savings.services import SavingsService


class ListLayoutPlaywrightTests(StaticLiveServerTestCase):
    def setUp(self):
        self.branch = Branch.unscoped.create(
            name="Layout Test Branch",
            code="LAYOUT",
            business_date=timezone.localdate(),
        )
        self.user = get_user_model().objects.create_superuser(
            username="layout-playwright-admin",
            email="layout-playwright@example.invalid",
            password="Layout-E2E-only-password-123!",
            branch=self.branch,
        )
        self.member = Member.unscoped.create(
            branch=self.branch,
            member_code="LAYOUT-000001",
            first_name="Layout",
            last_name="Member",
            status=Member.STATUS_ACTIVE,
        )
        for index in range(2, 23):
            Member.unscoped.create(
                branch=self.branch,
                member_code=f"LAYOUT-{index:06}",
                first_name="Layout",
                last_name=f"Member {index:02}",
                status=Member.STATUS_ACTIVE,
            )
        product = SavingsProduct.objects.create(
            code="LAYOUT-GEN",
            name="Layout general savings",
            savings_type=SavingsProduct.TYPE_GENERAL,
            minimum_opening_balance=Decimal("0.00"),
        )
        request = RequestFactory().get("/")
        request.user = self.user
        request.active_branch_id = None
        with patch("pdb.set_trace"):
            SavingsService(request).open_account(
                branch_id=self.branch.pk,
                product_id=product.pk,
                member_id=self.member.pk,
                opened_at=timezone.localdate(),
                opening_balance=Decimal("0.00"),
            )

    def test_pilot_lists_fit_two_desktop_viewports(self):
        client = Client()
        client.force_login(self.user)
        paths = [
            reverse("branch:Module_Branch_index_branch"),
            reverse("branch:Module_Members_list"),
            reverse("savings:Module_Savings_accounts"),
        ]
        member_grid = client.get(paths[1], {"ajax": "1"}).json()
        self.assertEqual(member_grid["records"], 22)
        screenshot_directory = Path(settings.BASE_DIR) / "docs" / "ui"
        screenshot_directory.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update({
            "ERP_E2E_BASE_URL": self.live_server_url,
            "ERP_E2E_COOKIE_NAME": settings.SESSION_COOKIE_NAME,
            "ERP_E2E_SESSION_COOKIE": client.cookies[settings.SESSION_COOKIE_NAME].value,
            "ERP_E2E_PATHS": ",".join(paths),
            "ERP_E2E_SCREENSHOT_DIR": str(screenshot_directory),
        })
        result = subprocess.run(
            ["node", str(settings.BASE_DIR / "e2e" / "list_layout_browser.cjs")],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Playwright failed:\n{result.stdout}\n{result.stderr}",
        )
        self.assertIn("Desktop layout checks passed", result.stdout)
        print(result.stdout, end="")
