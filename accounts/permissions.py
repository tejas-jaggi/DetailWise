"""Role checks shared by every app.

Customers are signed-in users without `is_staff`. Staff accounts are created
only by an administrator (Django admin or `createsuperuser`), never through
public registration.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

CUSTOMER_ONLY_MESSAGE = (
    "This page is for customer accounts. Staff accounts cannot create or view "
    "customer bookings here."
)
STAFF_ONLY_MESSAGE = "Staff access required"


def customer_required(view_func):
    """Sign-in required (redirect), then reject staff accounts with 403."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_staff:
            raise PermissionDenied(CUSTOMER_ONLY_MESSAGE)
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def staff_required(view_func):
    """Sign-in required (redirect), then reject non-staff accounts with 403.

    Foundation for the staff dashboard planned for a later milestone.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied(STAFF_ONLY_MESSAGE)
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)
