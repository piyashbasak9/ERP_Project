import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from core.accounting.models import Account, SystemAccountMapping
from core.accounts.permission_utils import get_all_urls
from core.branch.models import Branch
from core.common.middleware import ContentSecurityPolicyMiddleware
from core.common.ui_registry import (
    LIST_PAGE_TEMPLATES,
    UI_PAGE_TYPES,
    get_ui_route_registry,
)
from core.reports.registry import REPORTS


class TemplateSecurityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline_scripts = []
        self.external_assets = []
        self.event_handlers = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and not attributes.get("src"):
            self.inline_scripts.append(tag)
        for attribute in ("src", "href"):
            value = attributes.get(attribute, "")
            if urlsplit(value).scheme in {"http", "https"}:
                self.external_assets.append(value)
        self.event_handlers.extend(
            name for name in attributes if name.lower().startswith("on")
        )


class ContentSecurityPolicyTests(SimpleTestCase):
    def test_policy_blocks_inline_and_external_scripts(self):
        middleware = ContentSecurityPolicyMiddleware(
            lambda _request: HttpResponse("ok")
        )
        response = middleware(RequestFactory().get("/"))
        script_policy = next(
            directive
            for directive in response["Content-Security-Policy"].split("; ")
            if directive.startswith("script-src ")
        )

        self.assertEqual(
            response["Content-Security-Policy"],
            ContentSecurityPolicyMiddleware.policy,
        )
        self.assertEqual(script_policy, "script-src 'self'")
        self.assertIn("object-src 'none'", response["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_policy_middleware_is_enabled(self):
        self.assertIn(
            "core.common.middleware.ContentSecurityPolicyMiddleware",
            settings.MIDDLEWARE,
        )

    def test_templates_have_no_inline_scripts_external_assets_or_event_handlers(self):
        template_root = Path(settings.BASE_DIR) / "templates"
        violations = []
        for template_path in template_root.rglob("*.html"):
            parser = TemplateSecurityParser()
            parser.feed(template_path.read_text(encoding="utf-8"))
            if parser.inline_scripts:
                violations.append(f"{template_path}: inline script")
            if parser.external_assets:
                violations.append(f"{template_path}: external asset")
            if parser.event_handlers:
                violations.append(f"{template_path}: inline event handler")

        self.assertEqual(violations, [])


class UIConventionRegistryTests(SimpleTestCase):
    def test_every_registered_application_route_has_a_ui_type(self):
        routes = get_ui_route_registry()
        unclassified = {
            name: route['view']
            for name, route in routes.items()
            if route['type'] not in UI_PAGE_TYPES
        }
        self.assertEqual(unclassified, {})
        self.assertTrue(
            {route['route_name'] for route in get_all_urls()} <= routes.keys()
        )

    def test_every_list_page_uses_the_shared_listpage_template(self):
        routes = get_ui_route_registry()
        list_views = {
            route['view']
            for route in routes.values()
            if route['type'] == 'list_page'
        }
        self.assertEqual(list_views, set(LIST_PAGE_TEMPLATES))
        templates_without_listpage = []
        for template_name in LIST_PAGE_TEMPLATES.values():
            template = get_template(template_name)
            source = template.template.source
            if 'partials/list_page.html' not in source:
                templates_without_listpage.append(template_name)
        self.assertEqual(templates_without_listpage, [])

    def test_base_shell_exposes_route_type_and_uses_dense_layout_for_lists(self):
        source = get_template('base.html').template.source
        self.assertIn('{% ui_page_type as current_ui_page_type %}', source)
        self.assertIn('data-ui-page-type="{{ current_ui_page_type }}"', source)
        self.assertIn("current_ui_page_type == 'list_page'", source)


class UIConventionRenderTests(TestCase):
    def setUp(self):
        branch = Branch.unscoped.create(
            name='UI Convention Branch',
            code='UIC',
            business_date=timezone.localdate(),
        )
        cash = Account.objects.create(
            code='UIC-CASH',
            name='UI convention cash',
            account_type=Account.ASSET,
            normal_balance=Account.DEBIT,
        )
        SystemAccountMapping.objects.create(key='cash_in_hand', account=cash)
        savings = Account.objects.create(
            code='UIC-SAVINGS',
            name='UI convention savings',
            account_type=Account.LIABILITY,
            normal_balance=Account.CREDIT,
        )
        SystemAccountMapping.objects.create(key='member_savings', account=savings)
        user = get_user_model().objects.create_superuser(
            username='ui-convention-admin',
            email='ui-convention@example.invalid',
            password='UI-convention-only-password-123!',
            branch=branch,
        )
        self.client.force_login(user)

    def test_dashboard_uses_shared_status_bar_shell(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or 'utf-8')
        self.assertIn('class="erp-dashboard-body', html)
        self.assertIn('data-ui-page-type="dashboard"', html)
        self.assertIn('class="footer-custom erp-status-bar"', html)

    def test_registered_html_pages_render_type_markers(self):
        routes = get_ui_route_registry()
        violations = []
        unavailable = []
        for route_name, route in routes.items():
            page_type = route['type']
            if page_type == 'non_page':
                continue
            path = re.sub(
                r'<(?:(?P<converter>[a-zA-Z_]\w*):)?(?P<name>\w+)>',
                lambda match: {
                    'int': '1',
                    'str': 'sample',
                    'slug': 'sample',
                    'uuid': str(uuid4()),
                    'path': 'sample',
                }.get(match.group('converter') or 'str', 'sample'),
                route['path'],
            )
            response = self.client.get(path, follow=True)
            content_type = response.headers.get('Content-Type', '')
            if response.status_code != 200 or not content_type.startswith('text/html'):
                reason = (
                    f"{route_name}: HTTP {response.status_code} "
                    f"({content_type or 'no content type'})"
                )
                if response.status_code >= 500:
                    violations.append(reason)
                else:
                    unavailable.append(reason)
                continue

            html = response.content.decode(response.charset or 'utf-8')
            required = {
                'list_page': (
                    'data-list-page',
                    'data-list-filters',
                    'data-list-grid',
                    'data-list-state',
                    'data-grid-pager',
                    'data-view-range',
                ),
                'report_page': (
                    'report-page' if route['view'] != 'core.reports.views.report_index' else '<h1',
                ),
                'popup_form_fragment': ('<form',),
                'auth_page': ('<form',) if route['view'] != 'django.contrib.auth.views.PasswordChangeDoneView' else ('<h1',),
                'dashboard': ('<h1',),
                'detail_statement_page': ('<h1',),
                'special_screen': ('<h1',),
            }[page_type]
            if route_name == 'Module_Collections_sheet_print':
                required = ('<h1',)
            for marker in required:
                if marker not in html:
                    violations.append(f'{route_name}: missing {marker}')
            if (
                route_name not in {
                    'Module_Auth_login',
                    'Module_Collections_sheet_print',
                }
                and page_type not in {'auth_page', 'popup_form_fragment'}
            ):
                for marker in ('erp-header', 'erp-status-bar'):
                    if marker not in html:
                        violations.append(f'{route_name}: missing {marker}')
            if page_type == 'list_page' and 'data-ui-page-type="list_page"' not in html:
                violations.append(f'{route_name}: missing list route type marker')
        self.assertEqual(violations, [], f'UI convention marker failures: {violations}')
        page_count = sum(route['type'] != 'non_page' for route in routes.values())
        print(
            f'UI convention render check visited {page_count} page routes; '
            f'{len(unavailable)} object-dependent or non-HTML routes need fixtures: '
            f'{unavailable}'
        )

    def test_registered_report_grids_return_success(self):
        for report in REPORTS:
            response = self.client.get(
                f'/reports/{report.slug}/data/',
                {
                    'page': 1,
                    'rows': 25,
                    'sidx': report.columns[0].key,
                    'sord': 'asc',
                    '_search': 'false',
                },
            )
            self.assertEqual(
                response.status_code,
                200,
                f'{report.slug} grid returned HTTP {response.status_code}',
            )

    def test_list_description_renders_inside_the_shared_title_bar(self):
        response = self.client.get('/loans/business-rules/approval-tiers/')

        self.assertEqual(response.status_code, 200)
        html = response.content.decode(response.charset or 'utf-8')
        title_start = html.index('<header class="erp-page-title">')
        title_end = html.index('</header>', title_start)
        title_bar = html[title_start:title_end]
        self.assertIn('erp-page-heading-copy', title_bar)
        self.assertIn('A branch-specific tier takes precedence', title_bar)
