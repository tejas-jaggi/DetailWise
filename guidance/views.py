"""Customer-only JSON endpoints for weather guidance (plan Task 7, D7).

* ``GET  /guidance/forecast/?service=<pk>&date=YYYY-MM-DD[&time=HH:MM]``
* ``POST /guidance/explain/`` with the same fields (CSRF enforced by middleware)

Both return ``GuidanceResult.to_json()`` with HTTP 200, whatever the forecast or
model outcome. Errors are JSON: 400 invalid input, 401 signed out, 403 staff,
429 explanation limit reached, 503 quota storage unavailable.
Only explanation quota history is written; the browser chooses only the service, date
and time, never a model, URL, prompt or weather value.
"""

from functools import wraps

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from bookings.timeutils import central_now
from guidance import service as guidance_service
from guidance.forms import PAST_DATE_MESSAGE, GuidanceRequestForm
from guidance.rate_limit import RateLimitUnavailable, reserve_explanation


def customer_json_required(view_func):
    """401 JSON when signed out, 403 JSON for staff; customers proceed (D7).

    ``accounts.permissions.customer_required`` redirects and renders HTML, which
    a fetch() caller cannot use, so the JSON endpoints use this instead.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"status": "auth_required"}, status=401)
        if request.user.is_staff:
            return JsonResponse({"status": "forbidden"}, status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


@require_GET
@never_cache
@customer_json_required
def forecast(request):
    return _respond(GuidanceRequestForm(request.GET), guidance_service.get_forecast)


@transaction.non_atomic_requests
@require_POST
@never_cache
@customer_json_required
def explain(request):
    return _respond(
        GuidanceRequestForm(request.POST), guidance_service.get_explanation,
        user_id=request.user.pk,
    )


def _respond(form, get_result, user_id=None):
    if not form.is_valid():
        return _invalid(form.error_dict())
    if user_id is not None:
        try:
            retry_after = reserve_explanation(user_id)
        except RateLimitUnavailable:
            return JsonResponse({
                "status": "unavailable",
                "message": "AI explanations are temporarily unavailable. You can still save your booking.",
            }, status=503)
        if retry_after:
            response = JsonResponse({
                "status": "rate_limited",
                "message": "AI explanation request limit reached. Please try again later. "
                           "You can still save your booking.",
                "retry_after": retry_after,
            }, status=429)
            response["Retry-After"] = str(retry_after)
            return response
    data = form.cleaned_data
    try:
        result = get_result(data["service"], data["date"], data["time"])
    except ValueError:
        # build_facts() rejects a date before today. The form checked that a moment
        # ago, so this happens only when Central midnight passes in between. Any
        # other ValueError is a bug and is re-raised.
        if data["date"] < central_now().date():
            return _invalid({"date": [PAST_DATE_MESSAGE]})
        raise
    return JsonResponse(result.to_json())


def _invalid(errors: dict) -> JsonResponse:
    return JsonResponse({"status": "invalid", "errors": errors}, status=400)
