from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from core.common.middleware import ContentSecurityPolicyMiddleware


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
