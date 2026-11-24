import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.accounting.models import Account, SystemAccountMapping
from core.accounts.permission_utils import get_all_urls
from core.branch.models import Branch
from core.common.ui_registry import get_ui_route_registry


def example_path(route):
    replacements = {
        "int": "1",
        "str": "sample",
        "slug": "sample",
        "uuid": str(uuid4()),
        "path": "sample",
    }
    return re.sub(
        r"<(?:(?P<converter>[a-zA-Z_]\w*):)?(?P<name>\w+)>",
        lambda match: replacements.get(match.group("converter") or "str", "sample"),
        route,
    )



class ResponsiveAuditTests(StaticLiveServerTestCase):
    def setUp(self):
        branch = Branch.unscoped.create(
            name="Responsive Audit Branch",
            code="RESP",
            business_date=timezone.localdate(),
        )
        cash = Account.objects.create(
            code="RESP-CASH",
            name="Responsive audit cash",
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        SystemAccountMapping.objects.create(key="cash_in_hand", account=cash)
        savings = Account.objects.create(
            code="RESP-SAVINGS",
            name="Responsive audit savings",
            account_type=Account.LIABILITY,
            normal_balance=Account.CREDIT,
        )
        SystemAccountMapping.objects.create(key="member_savings", account=savings)
        self.user = get_user_model().objects.create_superuser(
            username="responsive-audit-admin",
            email="responsive-audit@example.invalid",
            password="Responsive-audit-only-password-123!",
            branch=branch,
        )

    def test_registered_routes_across_responsive_matrix(self):
        client = self.client_class()
        client.force_login(self.user)
        client.raise_request_exception = False
        paths = []
        unavailable_routes = []
        server_errors = []
        ui_routes = get_ui_route_registry()
        for route in get_all_urls():
            path = "/" + example_path(route["url"]).lstrip("/")
            route_name = route["route_name"]
            ui_route = ui_routes.get(route_name)
            if ui_route and ui_route["type"] == "popup_form_fragment":
                unavailable_routes.append({
                    "route": path,
                    "reason": "Popup form fragment; rendered in its shared modal host",
                })
                continue
            if route_name.startswith("API"):
                unavailable_routes.append({
                    "route": path,
                    "reason": "API endpoint, not a page",
                })
                continue
            try:
                callback = resolve(path).func
            except Resolver404:
                unavailable_routes.append({
                    "route": path,
                    "reason": "Sample URL does not resolve",
                })
                continue
            if not allows_get(callback):
                unavailable_routes.append({
                    "route": path,
                    "reason": "GET is not an allowed method",
                })
                continue
            response = client.get(path, follow=True)
            content_type = response.headers.get("Content-Type", "")
            if response.status_code == 200 and content_type.startswith("text/html"):
                paths.append(path)
            else:
                unavailable_routes.append({
                    "route": path,
                    "reason": f"HTTP {response.status_code} ({content_type or 'no content type'})",
                })
                if response.status_code >= 500:
                    server_errors.append(f"{path}: HTTP {response.status_code}")
        dashboard_response = client.get("/", follow=True)
        if (
            dashboard_response.status_code == 200
            and dashboard_response.headers.get("Content-Type", "").startswith("text/html")
        ):
            paths.append("/")
        else:
            unavailable_routes.append({
                "route": "/",
                "reason": (
                    f"Dashboard HTTP {dashboard_response.status_code} "
                    f"({dashboard_response.headers.get('Content-Type', 'no content type')})"
                ),
            })
        paths = sorted(set(paths))
        self.assertEqual(server_errors, [], f"UI routes returned server errors: {server_errors}")
        selected_paths = os.environ.get("ERP_RESPONSIVE_PATHS")
        if selected_paths:
            requested_paths = set(json.loads(selected_paths))
            paths = [path for path in paths if path in requested_paths]
        results_dir = Path(os.environ.get(
            "ERP_RESPONSIVE_RESULTS_DIR",
            Path.cwd() / "test-results",
        ))
        results_dir.mkdir(parents=True, exist_ok=True)
        output_path = results_dir / "responsive-audit.json"
        environment = os.environ.copy()
        for variable in (
            "SNAP_LIBRARY_PATH",
            "GTK_PATH",
            "GTK_EXE_PREFIX",
            "GTK_IM_MODULE_FILE",
            "GTK_MODULES",
            "GIO_MODULE_DIR",
        ):
            environment.pop(variable, None)
        environment.update({
            "ERP_E2E_BASE_URL": self.live_server_url,
            "ERP_E2E_COOKIE_NAME": settings.SESSION_COOKIE_NAME,
            "ERP_E2E_SESSION_COOKIE": client.cookies[
                settings.SESSION_COOKIE_NAME
            ].value,
            "ERP_E2E_PATHS": json.dumps(paths),
            "ERP_RESPONSIVE_UNAVAILABLE_ROUTES": json.dumps(unavailable_routes),
            "ERP_RESPONSIVE_RESULTS_FILE": str(output_path),
            "ERP_RESPONSIVE_SCREENSHOT_DIR": str(results_dir / "screenshots"),
        })
        result = subprocess.run(
            ["node", str(Path.cwd() / "e2e" / "responsive_audit_browser.cjs")],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if not output_path.is_file():
            self.fail(
                f"Responsive Playwright audit produced no results:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        audit_results = json.loads(output_path.read_text(encoding="utf-8"))
        audit_results["unavailable_routes"] = unavailable_routes
        self.assertEqual(len(audit_results["routes"]), len(paths))
        failures = audit_results["failures"]
        report_path = Path.cwd() / "docs" / "ui" / "responsive-report.md"
        write_responsive_report(report_path, audit_results)
        if result.returncode:
            self.fail(
                f"Responsive Playwright audit failed:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        if os.environ.get("ERP_RESPONSIVE_STRICT", "1") == "1":
            self.assertFalse(
                failures,
                f"{len(failures)} responsive failures. See {report_path}",
            )
        print(
            f"Responsive audit visited {len(paths)} routes across "
            f"{len(audit_results['browsers'])} browser(s) and "
            f"{len(audit_results['viewports'])} viewport(s); "
            f"{len(unavailable_routes)} registry routes were not HTML pages; "
            f"{len(failures)} failure(s)."
        )


def allows_get(callback):
    view_class = getattr(callback, "view_class", None)
    if view_class:
        return "get" in view_class.http_method_names
    wrapped = callback
    while wrapped:
        methods = getattr(wrapped, "request_method_list", None)
        if methods is not None:
            return "GET" in methods
        wrapped = getattr(wrapped, "__wrapped__", None)
    return True


def write_responsive_report(path, results):
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped_failures = {}
    category_counts = Counter()
    for failure in results["failures"]:
        category_counts[finding_category(failure["finding"])] += 1
        key = (failure["route"], failure["viewport"], failure["browser"])
        grouped_failures.setdefault(key, Counter())[finding_category(
            failure["finding"]
        )] += 1
    lines = [
        "# Responsive UI Audit",
        "",
        (
            f"HTML pages audited: **{len(results['routes'])}** across "
            f"**{len(results['browsers'])}** browser(s) and "
            f"**{len(results['viewports'])}** viewport(s)."
        ),
        (
            f"Finding count: **{len(results['failures'])}**. Registry routes not "
            f"audited as HTML pages: **{len(results.get('unavailable_routes', []))}**."
        ),
        "",
        "| Check category | Failures after |",
        "|---|---:|",
    ]
    for category, count in sorted(category_counts.items()):
        lines.append(f"| {category} | {count} |")
    lines.extend([
        "",
        (
            "No directly comparable before-run was retained: the earlier audit "
            "used a different detector and treated popup fragments as standalone "
            "pages. Current results use the same detector across the listed pages, "
            "browsers and viewports."
        ),
    ])
    lines.extend([
        "",
        "| Page | Viewport | Browser | Finding |",
        "|---|---:|---|---|",
    ])
    for (route, viewport, browser), findings in sorted(grouped_failures.items()):
        summary = "; ".join(
            f"{category}: {count}"
            for category, count in sorted(findings.items())
        )
        lines.append(
            f"| `{route}` | {viewport} | {browser} | "
            f"{summary} |"
        )
    if not grouped_failures:
        lines.append("| — | — | — | No failures detected. |")
    if results.get("unavailable_routes"):
        lines.extend([
            "",
            "## Registry routes excluded from visual checks",
            "",
            (
                "These routes are API endpoints, reject GET, do not resolve with "
                "the sample URL, or did not return an HTML 200 response during preflight."
            ),
            "",
            "| Route | Reason |",
            "|---|---|",
        ])
        for route in results["unavailable_routes"]:
            lines.append(f"| `{route['route']}` | {route['reason']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finding_category(finding):
    categories = {
        "horizontal page scroll": "horizontal page overflow",
        "element outside viewport": "element outside viewport",
        "overlap:": "layout overlap",
        "clipped overlay": "clipped overlay",
        "popup actions extend": "popup actions outside viewport",
        "grid width mismatch": "grid width mismatch",
        "grid did not resize": "grid resize failure",
        "small touch target": "touch target below 44px",
        "small text": "text below minimum font size",
        "console error": "browser console error",
        "navigation drawer": "navigation drawer behavior",
        "dropdown menu": "dropdown behavior",
        "popup link": "popup behavior",
        "toast overlaps": "toast overlaps header",
        "navigation failed": "browser navigation failure",
        "report filter panel": "report filter behavior",
        "report results": "report mobile-card behavior",
        "report compact pager": "report mobile-pager behavior",
        "list results": "list mobile-card behavior",
        "shared navbar height": "shared navbar sizing",
    }
    return next(
        (category for prefix, category in categories.items() if finding.startswith(prefix)),
        "other",
    )
