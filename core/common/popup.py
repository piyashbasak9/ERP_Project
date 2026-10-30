import uuid

from django.http import JsonResponse
from django.shortcuts import render


def is_popup_request(request):
    return (
        request.GET.get("popup") == "1"
        and request.headers.get("x-requested-with") == "XMLHttpRequest"
    )


def popup_json_response(request, *, message, data=None, errors=None, status=200):
    if not is_popup_request(request):
        return None
    return JsonResponse(
        {
            "success": status < 400,
            "message": message,
            "data": data,
            "errors": errors,
            "request_id": getattr(request, "request_id", None)
            or request.headers.get("x-request-id")
            or uuid.uuid4().hex[:10],
        },
        status=status,
    )


def render_popup_form(request, template_name, context, *, status=200):
    form = context.get("form")
    errors = {}
    if form is not None and form.errors:
        errors.update(
            {
                name: [str(error) for error in field_errors]
                for name, field_errors in form.errors.items()
            }
        )
    for formset in context.values():
        if not hasattr(formset, "forms"):
            continue
        for child_form in formset.forms:
            for name, field_errors in child_form.errors.items():
                errors[child_form.add_prefix(name)] = [
                    str(error) for error in field_errors
                ]
        if formset.non_form_errors():
            errors["__all__"] = [
                str(error) for error in formset.non_form_errors()
            ]
    if request.method == "POST" and errors:
        response = popup_json_response(
            request,
            message="Please correct the highlighted fields.",
            errors=errors,
            status=400,
        )
        if response is not None:
            return response
    return render(request, template_name, context, status=status)
