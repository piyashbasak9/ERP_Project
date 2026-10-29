from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_KYC_SIGNATURES = {
    'image/jpeg': (b'\xff\xd8\xff',),
    'image/png': (b'\x89PNG\r\n\x1a\n',),
    'application/pdf': (b'%PDF-',),
}


def max_upload_bytes():
    return int(getattr(settings, 'MAX_UPLOAD_MB', 2)) * 1024 * 1024


def detect_upload_mime(uploaded_file):
    head = uploaded_file.read(16)
    uploaded_file.seek(0)
    for mime_type, signatures in ALLOWED_KYC_SIGNATURES.items():
        if any(head.startswith(signature) for signature in signatures):
            return mime_type
    return None


def validate_upload_size(uploaded_file):
    if uploaded_file.size > max_upload_bytes():
        raise ValidationError(f'File size must not exceed {settings.MAX_UPLOAD_MB} MB.')


def validate_kyc_file(uploaded_file):
    validate_upload_size(uploaded_file)
    if detect_upload_mime(uploaded_file) is None:
        raise ValidationError('Only JPG, PNG, and PDF files are allowed.')
