import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

request_id_var = ContextVar('request_id', default='')
_SECRET_VALUE = re.compile(
    r'(?i)\b(password|token|secret|national[_ -]?id|passport[_ -]?number|phone)\b'
    r'(\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^,\s;]+)'
)
_LONG_NUMBER = re.compile(r'\b\d{5,}\b')
_DEVELOPMENT_SECRET = re.compile(
    r'(?i)\b(password|token|secret)\b(\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^,\s;]+)'
)


class SafeJSONFormatter(logging.Formatter):
    def format(self, record):
        message = _SECRET_VALUE.sub(r'\1\2[REDACTED]', record.getMessage())
        message = _LONG_NUMBER.sub('[REDACTED_NUMBER]', message)
        return json.dumps(
            {
                'timestamp': datetime.now(UTC).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'request_id': request_id_var.get() or '-',
                'message': message,
            },
            ensure_ascii=True,
        )


class DevelopmentFormatter(logging.Formatter):
    def format(self, record):
        return _DEVELOPMENT_SECRET.sub(r'\1\2[REDACTED]', super().format(record))


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = request_id
            return response
        finally:
            request_id_var.reset(token)
