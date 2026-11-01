import json
import logging
import re
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP, totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.audit.models import AuditLog
from ERP.settings import resolve_database_ssl_options

from .models import Permission, RecoveryCode, Role, RolePermission, UserRole

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
            'password=%s national_id=%s token=%s',
            ('dont-log-this', '12345678901', 'private-token'),
            None,
        )
        rendered = json.loads(SafeJSONFormatter().format(record))

        self.assertEqual(rendered['request_id'], '-')
        self.assertNotIn('dont-log-this', rendered['message'])
        self.assertNotIn('12345678901', rendered['message'])
        self.assertNotIn('private-token', rendered['message'])


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
    @override_settings(SESSION_ABSOLUTE_TIMEOUT_HOURS=12, MFA_REQUIRED=False)
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

    @override_settings(SESSION_ABSOLUTE_TIMEOUT_HOURS=12, MFA_REQUIRED=False)
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


@override_settings(
    MFA_REQUIRED=True,
    MFA_FAILURE_LIMIT=5,
    MFA_COOLOFF_SECONDS=900,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher'],
)
class PrivilegedMFAEnforcementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='mfa-admin',
            email='mfa-admin@example.invalid',
            password='Temporary-test-password-123!',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _new_totp(self, device):
        return f'{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):0{device.digits}d}'

    def _enroll(self):
        response = self.client.get(reverse('accounts:Module_Auth_mfa_setup'))
        self.assertEqual(response.status_code, 200)
        device = TOTPDevice.objects.get(user=self.user, name='primary')
        response = self.client.post(
            reverse('accounts:Module_Auth_mfa_setup'),
            {'token': self._new_totp(device)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(device.__class__.objects.get(pk=device.pk).confirmed)
        return response

    def test_password_only_login_cannot_open_page_or_ajax_endpoint(self):
        self.client.logout()
        login = self.client.post(
            reverse('accounts:Module_Auth_login'),
            {'username': self.user.username, 'password': 'Temporary-test-password-123!'},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn(
            reverse('accounts:Module_Auth_mfa_setup'),
            login['Location'],
        )
        self.assertIn('auth_started_at', self.client.session)
        page = self.client.get('/')
        self.assertRedirects(
            page,
            reverse('accounts:Module_Auth_mfa_setup') + '?next=%2F',
            fetch_redirect_response=False,
        )
        direct = self.client.get(reverse('accounts:Module_Auth_list_users'))
        self.assertEqual(direct.status_code, 302)
        self.assertIn(reverse('accounts:Module_Auth_mfa_setup'), direct['Location'])
        ajax = self.client.get(
            reverse('accounts:Module_Auth_list_users'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(ajax.status_code, 403)
        self.assertIn('mfa_url', ajax.json())
        json_fetch = self.client.get(
            reverse('accounts:Module_Auth_list_users'),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(json_fetch.status_code, 403)
        self.assertIn('mfa_url', json_fetch.json())

    def test_enrollment_creates_hashed_recovery_codes(self):
        response = self._enroll()
        codes = response.context['recovery_codes']

        self.assertEqual(len(codes), 10)
        stored = list(RecoveryCode.objects.filter(user=self.user))
        self.assertEqual(len(stored), 10)
        self.assertNotIn(codes[0], stored[0].code_hash)
        self.assertEqual(identify_hasher(stored[0].code_hash).algorithm, 'pbkdf2_sha256')

    def test_recovery_code_is_single_use_and_unlocks_the_session(self):
        response = self._enroll()
        recovery_code = response.context['recovery_codes'][0]
        session = self.client.session
        session.pop('mfa_verified_at', None)
        session.save()

        verify_url = reverse('accounts:Module_Auth_mfa_verify')
        verified = self.client.post(verify_url, {'token': recovery_code})
        self.assertEqual(verified.status_code, 302)
        self.assertEqual(
            RecoveryCode.objects.filter(user=self.user, used_at__isnull=False).count(),
            1,
        )

        self.client.logout()
        self.client.force_login(self.user)
        rejected = self.client.post(verify_url, {'token': recovery_code})
        self.assertEqual(rejected.status_code, 200)
        self.assertContains(rejected, 'was not accepted')

    def test_totp_code_cannot_be_replayed(self):
        self._enroll()
        self.client.logout()
        self.client.force_login(self.user)
        device = TOTPDevice.objects.get(user=self.user, name='primary')
        current_time = int(timezone.now().timestamp())
        next_time_step = (
            (current_time - device.t0) // device.step + 1
        ) * device.step + device.t0
        generator = TOTP(
            device.bin_key,
            step=device.step,
            t0=device.t0,
            digits=device.digits,
            drift=device.drift,
        )
        generator.time = next_time_step
        token = f'{generator.token():0{device.digits}d}'

        with patch(
            'django_otp.plugins.otp_totp.models.time.time',
            return_value=next_time_step,
        ):
            first = self.client.post(
                reverse('accounts:Module_Auth_mfa_verify'),
                {'token': token},
            )
        self.assertEqual(first.status_code, 302)
        self.client.logout()
        self.client.force_login(self.user)
        with patch(
            'django_otp.plugins.otp_totp.models.time.time',
            return_value=next_time_step,
        ):
            replay = self.client.post(
                reverse('accounts:Module_Auth_mfa_verify'),
                {'token': token},
            )

        self.assertEqual(replay.status_code, 200)
        self.assertContains(replay, 'was not accepted')

    def test_sensitive_action_requires_recent_mfa_again(self):
        self._enroll()
        session = self.client.session
        session['mfa_verified_at'] = int(timezone.now().timestamp()) - 301
        session.save()

        sensitive_urls = (
            reverse('branch:Module_Branch_day_end_reopen'),
            reverse('accounts:Module_Auth_edit_role', args=[999]),
            reverse('accounting:Module_Accounting_journal_reverse', args=[999]),
        )
        for url in sensitive_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('accounts:Module_Auth_mfa_verify'), response['Location'])

        reversal_url = reverse('collections:Module_Collections_sheet_reversal_request', args=[999])
        ajax = self.client.post(reversal_url, HTTP_ACCEPT='application/json')
        self.assertEqual(ajax.status_code, 403)
        self.assertIn('mfa_url', ajax.json())

    @override_settings(MFA_FAILURE_LIMIT=2)
    def test_failed_mfa_attempts_are_locked_out(self):
        response = self.client.get(reverse('accounts:Module_Auth_mfa_setup'))
        self.assertEqual(response.status_code, 200)
        setup_url = reverse('accounts:Module_Auth_mfa_setup')
        self.client.post(setup_url, {'token': '000000'})
        self.client.post(setup_url, {'token': '000000'})
        locked = self.client.post(setup_url, {'token': '000000'})

        self.assertEqual(locked.status_code, 429)

    def test_another_privileged_admin_can_reset_mfa_with_reason_and_audit(self):
        target = User.objects.create_superuser(
            username='mfa-reset-target',
            email='mfa-reset-target@example.invalid',
            password='Temporary-test-password-123!',
        )
        self._enroll()
        response = self.client.post(
            reverse('accounts:Module_Auth_mfa_reset', args=[target.pk]),
            {'reason': 'Lost authenticator device'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=target).exists())
        audit = AuditLog.objects.get(
            action='MFAReset', entity_name='CustomUser', entity_id=str(target.pk)
        )
        self.assertEqual(audit.remarks, 'Lost authenticator device')
        target_client = Client()
        login = target_client.post(
            reverse('accounts:Module_Auth_login'),
            {'username': target.username, 'password': 'Temporary-test-password-123!'},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn(reverse('accounts:Module_Auth_mfa_setup'), login['Location'])

    def test_server_command_resets_only_superuser_mfa_and_audits_operator(self):
        self._enroll()
        recovery_codes = RecoveryCode.objects.filter(user=self.user)
        self.assertTrue(recovery_codes.exists())
        output = StringIO()

        call_command(
            'reset_user_mfa',
            username=self.user.username,
            reason='Authenticator lost during server recovery',
            operator='on-call-operator',
            stdout=output,
        )

        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())
        audit = AuditLog.objects.get(
            action='MFAReset',
            entity_name='CustomUser',
            entity_id=str(self.user.pk),
        )
        self.assertIsNone(audit.user)
        self.assertEqual(audit.user_name, 'server-command:on-call-operator')
        self.assertEqual(audit.remarks, 'Authenticator lost during server recovery')
        self.assertTrue(audit.new_values['mfa_enrollment_required'])
        self.assertIn('enrollment is required', output.getvalue())

        self.client.force_login(self.user)
        setup = self.client.get('/')
        self.assertEqual(setup.status_code, 302)
        self.assertIn(reverse('accounts:Module_Auth_mfa_setup'), setup['Location'])

    def test_role_with_user_admin_permission_requires_mfa(self):
        role = Role.objects.create(name='MFA privileged role')
        permission = Permission.objects.create(
            route_name='Module_Auth_list_users',
            url_pattern='/accounts/users/',
        )
        RolePermission.objects.create(role=role, permission=permission)
        target = User.objects.create_user(
            username='mfa-role-user',
            password='Temporary-test-password-123!',
        )
        UserRole.objects.create(user=target, role=role)
        client = Client()
        client.force_login(target)

        response = client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:Module_Auth_mfa_setup'), response['Location'])
