"""Staff-only dashboard and CSV export; neither endpoint modifies bookings."""

import csv
from urllib.parse import urlencode

from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.permissions import staff_required

from .reporting import booking_charts, booking_summary, filtered_bookings, spreadsheet_safe
from .staff_forms import BookingDateRangeForm


@never_cache
@staff_required
@require_safe
def dashboard(request):
    form = BookingDateRangeForm(request.GET)
    context = {"form": form}
    if not form.is_valid():
        return render(request, "bookings/staff_dashboard.html", context, status=400)

    bookings = filtered_bookings(form.cleaned_data)
    context.update(
        summary=booking_summary(bookings),
        charts=booking_charts(bookings),
        filter_query=urlencode({
            key: value.isoformat() for key, value in form.cleaned_data.items() if value
        }),
    )
    return render(request, "bookings/staff_dashboard.html", context)


class _CSVBuffer:
    def write(self, value):
        return value


@never_cache
@staff_required
@require_safe
def booking_export(request):
    form = BookingDateRangeForm(request.GET)
    if not form.is_valid():
        return render(request, "bookings/staff_dashboard.html", {"form": form}, status=400)

    # One joined query, no customer data and no per-booking service lookups.
    rows = filtered_bookings(form.cleaned_data).order_by("date", "time", "pk").values_list(
        "pk", "service__name", "date", "time", "status", "price_at_booking",
    )

    def content():
        writer = csv.writer(_CSVBuffer(), quoting=csv.QUOTE_ALL)
        yield "\ufeff"  # UTF-8 BOM lets spreadsheet applications recognize Unicode.
        yield writer.writerow([
            "Reference", "Service", "Appointment date", "Appointment time (America/Chicago)",
            "Status", "Estimated price (USD)",
        ])
        for pk, service, date, time, status, price in rows.iterator(chunk_size=2000):
            yield writer.writerow([spreadsheet_safe(value) for value in [
                f"DW-{pk:04d}", service, date.isoformat(), time.isoformat(), status, f"{price:.2f}",
            ]])

    response = StreamingHttpResponse(content(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="detailwise-bookings.csv"'
    return response
