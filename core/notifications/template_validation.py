from string import Formatter

from django.core.exceptions import ValidationError

EVENT_PLACEHOLDERS = {
    "installment_due": {
        "branch_name",
        "due_date",
        "amount",
        "member_name",
        "reference",
        "days",
    },
    "overdue": {
        "branch_name",
        "due_date",
        "amount",
        "member_name",
        "reference",
        "days",
    },
    "approval_waiting": {"branch_name", "reference", "submitted_date"},
    "kyc_expiry": {"branch_name", "member_name", "document_type", "expiry_date"},
}


def validate_template(event_key, *texts):
    allowed = EVENT_PLACEHOLDERS.get(event_key)
    if allowed is None:
        raise ValidationError({"event_key": "Select a supported notification event."})
    formatter = Formatter()
    errors = []
    for text in texts:
        try:
            fields = {
                field_name
                for _, field_name, _, _ in formatter.parse(text)
                if field_name is not None
            }
        except ValueError as exc:
            raise ValidationError("Template contains invalid placeholder syntax.") from exc
        if fields - allowed:
            errors.append(f"Unsupported placeholder(s): {', '.join(sorted(fields - allowed))}.")
    if errors:
        raise ValidationError(errors)
