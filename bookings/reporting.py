"""Read-only booking reports. Date ranges refer to Central appointment dates."""

import datetime
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import Booking
from .timeutils import central_now


def filtered_bookings(cleaned_data):
    bookings = Booking.objects.all()
    if cleaned_data.get("start_date"):
        bookings = bookings.filter(date__gte=cleaned_data["start_date"])
    if cleaned_data.get("end_date"):
        bookings = bookings.filter(date__lte=cleaned_data["end_date"])
    return bookings


def booking_summary(bookings):
    """Aggregate in SQL without loading individual bookings or customers."""
    now = central_now()
    later_today = Q(time__gt=now.time())
    if now.fold:
        # Bookings in the repeated 1 AM hour mean its FIRST occurrence.
        # During the second occurrence, all of those appointments are past.
        later_today = Q(time__gte=datetime.time(2))
    upcoming = Q(status=Booking.Status.SAVED) & (
        Q(date__gt=now.date()) | (Q(date=now.date()) & later_today)
    )
    return bookings.aggregate(
        total=Count("pk"),
        upcoming=Count("pk", filter=upcoming),
        cancelled=Count("pk", filter=Q(status=Booking.Status.CANCELLED)),
        revenue=Sum(
            "price_at_booking", filter=Q(status=Booking.Status.SAVED),
            default=Decimal("0.00"),
        ),
    )


def booking_charts(bookings):
    trends = list(
        bookings.order_by("date").values("date").annotate(count=Count("pk"))
    )
    popularity = list(
        bookings.order_by().values("service__name").annotate(count=Count("pk"))
        .order_by("-count", "service__name")
    )
    return {
        "trends": [{"date": row["date"].isoformat(), "count": row["count"]} for row in trends],
        "popularity": [{"service": row["service__name"], "count": row["count"]} for row in popularity],
    }


def spreadsheet_safe(value):
    """Keep formula-like text literal, including whitespace-prefixed formulas.

    CSV quoting alone does not prevent a spreadsheet from executing formulas.
    The apostrophe is intentionally part of the exported cell value.
    """
    text = str(value)
    candidate = text
    while candidate and (
        candidate[0].isspace() or ord(candidate[0]) < 32 or candidate[0] == "\ufeff"
    ):
        candidate = candidate[1:]
    if text.startswith(("\t", "\r", "\n")) or candidate.startswith(
        ("=", "+", "-", "@", "＝", "＋", "－", "＠")
    ):
        return "'" + text
    return text
