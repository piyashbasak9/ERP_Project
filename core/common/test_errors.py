import json
import logging

from django.test import Client, RequestFactory, TestCase, override_settings

from core.common.errors import csrf_failure
from core.common.structured_logging import DevelopmentFormatter


@override_settings(ROOT_URLCONF="core.common.test_urls", DEBUG=True)
class DevelopmentErrorLoggingTests(TestCase):
    def test_unhandled_view_exception_logs_traceback_and_returns_debug_json(self):
        client = Client(raise_request_exception=False)
        with self.assertLogs("core.common.errors", level="ERROR") as captured:
            response = client.get(
                "/health/",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.content)
        self.assertEqual(payload["debug"]["type"], "ValueError")
        self.assertIn("unhandled development view failure", payload["debug"]["message"])
        self.assertIn("Traceback", captured.output[0])
        self.assertNotIn("password", captured.output[0].lower())
        self.assertNotIn("token", captured.output[0].lower())

    def test_csrf_failure_logs_reason_and_returns_debug_envelope_for_ajax(self):
        request = RequestFactory().post(
            "/health/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        with self.assertLogs("core.common.errors", level="WARNING") as captured:
            response = csrf_failure(request, reason="CSRF cookie not set.")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["debug"]["type"], "CSRFError")
        self.assertIn("CSRF cookie not set", captured.output[0])
        self.assertNotIn("password", captured.output[0].lower())
        self.assertNotIn("token", captured.output[0].lower())

    def test_development_formatter_redacts_password_and_token_values(self):
        record = logging.LogRecord(
            "core.test",
            logging.ERROR,
            __file__,
            1,
            "password=hunter2 token=abc123",
            (),
            None,
        )

        rendered = DevelopmentFormatter("%(message)s").format(record)

        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertIn("[REDACTED]", rendered)
