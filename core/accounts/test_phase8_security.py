import json
import logging
import re
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from ERP.settings import resolve_database_ssl_options

User = get_user_model()


class FirstPartyXSSAuditTests(SimpleTestCase):
    def test_templates_and_application_sources_do_not_mark_dynamic_values_safe(self):
        template_roots = [settings.BASE_DIR / 'templates']
        template_roots.extend((settings.BASE_DIR / 'core').glob('*/templates'))
        template_files = [
            path
            for root in template_roots
            for path in root.rglob('*.html')
        ]
        python_files = [
            path
            for root in (settings.BASE_DIR / 'core', settings.BASE_DIR / 'ERP')
            for path in root.rglob('*.py')
            if 'tests.py' not in path.name and 'test_' not in path.name
        ]

        for path in [*template_files, *python_files]:
            content = path.read_text(encoding='utf-8').lower()
            self.assertNotIn('|safe', content, str(path))
            self.assertNotIn('mark_safe(', content, str(path))
            self.assertNotIn('{% autoescape off %}', content, str(path))

    def test_every_first_party_jqgrid_autoencodes_cells(self):
        scripts = (
            path
            for path in (settings.BASE_DIR / 'static').rglob('*.js')
            if 'vendor' not in path.parts
        )
        grids = []
        for path in scripts:
            content = path.read_text(encoding='utf-8')
            grid_count = len(re.findall(r'\.jqGrid\s*\(\s*\{', content))
            if grid_count:
                autoencode_count = len(re.findall(r'\bautoencode\s*:\s*true\b', content))
                grids.append((path, grid_count, autoencode_count))
        self.assertTrue(grids)
        for path, grid_count, autoencode_count in grids:
            self.assertEqual(autoencode_count, grid_count, str(path))

        collection_grid = (settings.BASE_DIR / 'static/js/collections-sheet-list.js').read_text(
            encoding='utf-8'
        )
        self.assertNotIn('${value}', collection_grid)
        self.assertIn('document.createElement("a")', collection_grid)

    def test_javascript_markup_sinks_are_static_or_server_rendered_html(self):
        scripts = (
            path
            for path in (settings.BASE_DIR / 'static').rglob('*.js')
            if 'vendor' not in path.parts
        )
        for path in scripts:
            content = path.read_text(encoding='utf-8')
            self.assertNotRegex(content, r'\.html\s*\(', str(path))
            for assignment in re.findall(
                r'\.innerHTML\s*=\s*([^;\n]+)',
                content,
            ):
                if 'await response.text()' in assignment:
                    self.assertEqual(
                        path.name,
                        'popup.js',
                        'Only the popup may insert Django-rendered, autoescaped fragments.',
                    )
                else:
                    self.assertRegex(assignment.strip(), r"""^['"]""", str(path))

    def test_json_logs_redact_secrets_and_national_id_numbers(self):
        from core.common.structured_logging import SafeJSONFormatter

        record = logging.LogRecord(
            'core.test',
            logging.INFO,
            __file__,
            1,
            'national_id=%s token=%s password=%s',
            ('12345678901', 'private-token', 'dont-log-this'),
            None,
        )
        rendered = json.loads(SafeJSONFormatter().format(record))

        self.assertEqual(rendered['request_id'], '-')
        self.assertNotIn('dont-log-this', rendered['message'])
        self.assertNotIn('12345678901', rendered['message'])
        self.assertNotIn('private-token', rendered['message'])


class FaviconRoutingTests(SimpleTestCase):
    @override_settings(
        MIDDLEWARE=[
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'core.accounts.global_auth_middleware.GlobalLoginRequiredMiddleware',
            'core.accounts.middleware.URLPermissionMiddleware',
        ]
    )
    def test_anonymous_favicon_request_serves_public_icon_without_login_redirect(self):
        response = Client().get('/favicon.ico')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/svg+xml')
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')
        self.assertEqual(b''.join(response.streaming_content)[:4], b'<svg')


class ProductionDatabaseTLSSettingsTests(SimpleTestCase):
    def test_production_settings_reject_tls_downgrade_modes(self):
        for mode in ('prefer', 'disable', 'allow'):
            with self.subTest(mode=mode), self.assertRaises(ImproperlyConfigured):
                resolve_database_ssl_options(False, mode)

    def test_production_tls_defaults_to_require_and_uses_full_verification_with_ca(self):
        self.assertEqual(resolve_database_ssl_options(False), {'sslmode': 'require'})
        self.assertEqual(
            resolve_database_ssl_options(False, 'require', '/run/secrets/db-ca.pem'),
            {
                'sslmode': 'verify-full',
                'sslrootcert': '/run/secrets/db-ca.pem',
            },
        )

    def test_development_can_keep_a_relaxed_tls_mode(self):
        self.assertEqual(resolve_database_ssl_options(True, 'prefer'), {'sslmode': 'prefer'})


class AbsoluteSessionDeadlineTests(TestCase):
    @override_settings(SESSION_ABSOLUTE_TIMEOUT_HOURS=12)
    def test_absolute_expiry_is_independent_of_sliding_activity(self):
        user = User.objects.create_user(
            username='absolute-session-user',
            password='Temporary-test-password-123!',
        )
        self.client.force_login(user)
        session = self.client.session
        session['auth_started_at'] = 1_000
        session.save()

        with patch('core.accounts.middleware.time.time', return_value=1_000 + 12 * 3600 - 1):
            self.assertEqual(self.client.get('/').status_code, 200)
        with patch('core.accounts.middleware.time.time', return_value=1_000 + 12 * 3600):
            response = self.client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    @override_settings(SESSION_ABSOLUTE_TIMEOUT_HOURS=12)
    def test_expired_session_returns_json_login_challenge(self):
        user = User.objects.create_user(
            username='absolute-session-ajax-user',
            password='Temporary-test-password-123!',
        )
        self.client.force_login(user)
        session = self.client.session
        session['auth_started_at'] = 1_000
        session.save()

        with patch('core.accounts.middleware.time.time', return_value=1_000 + 12 * 3600):
            response = self.client.get('/', HTTP_ACCEPT='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('/accounts/login/', response.json()['login_url'])


class HealthEndpointTests(TestCase):
    def test_health_checks_dependencies_without_returning_data(self):
        response = self.client.get(reverse('health'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertRegex(response['X-Request-ID'], r'^[0-9a-f]{32}$')


class LoginWithoutMFATests(TestCase):
    def test_superuser_login_goes_directly_to_home_without_second_factor(self):
        user = User.objects.create_superuser(
            username='login-without-mfa-admin',
            email='login-without-mfa@example.invalid',
            password='Temporary-test-password-123!',
        )

        response = self.client.post(
            reverse('accounts:Module_Auth_login'),
            {'username': user.username, 'password': 'Temporary-test-password-123!'},
        )

        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertNotIn('mfa_verified_at', self.client.session)

    def test_mfa_routes_are_not_registered(self):
        for route_name in (
            'accounts:Module_Auth_mfa_setup',
            'accounts:Module_Auth_mfa_verify',
            'accounts:Module_Auth_mfa_reset',
        ):
            with self.subTest(route_name=route_name), self.assertRaises(NoReverseMatch):
                reverse(route_name, args=[1] if route_name.endswith('mfa_reset') else [])
