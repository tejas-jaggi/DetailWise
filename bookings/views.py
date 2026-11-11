from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.permissions import customer_required

from .forms import BookingForm
from .models import Booking, Service
from .selection import active_service_from_slug
from .timeutils import central_now, is_past_central


def catalog(request):
    """S01 Service Catalog: public list of active services."""
    services = Service.objects.filter(is_active=True)
    return render(request, "bookings/catalog.html", {"services": services})


@customer_required
def booking_create(request):
    """S04 Create Booking: validate in Central Time, then save for this user."""
    if request.method == "POST":
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.customer = request.user  # never trust a customer id from the browser
            booking.save()  # the model snapshots price_at_booking
            messages.success(request, f"Booking saved. Your reference is {booking.reference}.")
            return redirect("bookings:my_bookings")
    else:
        initial = {}
        selected = active_service_from_slug(request.GET.get("service"))
        if selected:
            initial["service"] = selected.pk
        form = BookingForm(initial=initial)

    return render(request, "bookings/booking_form.html", {"form": form})


@customer_required
def my_bookings(request):
    """S05 My Bookings: only the signed-in customer's records."""
    bookings = Booking.objects.filter(customer=request.user).select_related("service")
    now = central_now()
    upcoming, history = [], []
    for booking in bookings:
        is_upcoming = (
            booking.status == Booking.Status.SAVED
            and not is_past_central(booking.date, booking.time, now=now)
        )
        (upcoming if is_upcoming else history).append(booking)
    history.reverse()  # most recent first

    return render(request, "bookings/my_bookings.html", {
        "upcoming": upcoming,
        "history": history,
        "has_bookings": bool(upcoming or history),
    })


@customer_required
def booking_detail(request, pk):
    """One booking, visible only to its owner; anything else is 'not found'."""
    booking = (
        Booking.objects.select_related("service")
        .filter(pk=pk, customer=request.user)
        .first()
    )
    if booking is None:
        return render(request, "bookings/booking_not_found.html", status=404)
    return render(request, "bookings/booking_detail.html", {"booking": booking})
