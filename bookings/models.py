from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .timeutils import combine_central, is_past_central


class Service(models.Model):
    """A detailing service offered by the shop (maintained in Django admin)."""

    class WeatherSensitivity(models.TextChoices):
        # Drives future weather guidance: rain matters for exterior work.
        EXTERIOR = "exterior", "Exterior"
        INTERIOR = "interior", "Interior"
        MIXED = "mixed", "Mixed (exterior and interior)"

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.CharField(max_length=255)
    price = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Listed price in US dollars.",
    )
    weather_sensitivity = models.CharField(
        max_length=10, choices=WeatherSensitivity.choices
    )
    is_active = models.BooleanField(
        default=True, help_text="Inactive services are hidden and cannot be booked."
    )
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0), name="service_price_nonnegative"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Booking(models.Model):
    """A customer's saved booking request for one service at a date and time.

    "Saved" means the record exists. It does not mean capacity is confirmed
    (slot availability is outside the project scope).
    """

    class Status(models.TextChoices):
        SAVED = "saved", "Saved"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings"
    )
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="bookings"
    )
    date = models.DateField(help_text="Appointment date (Central Time).")
    time = models.TimeField(help_text="Appointment time (Central Time).")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SAVED
    )
    # Snapshot of the listed price when the booking was created, so the
    # estimated value stays correct if the service price changes later.
    price_at_booking = models.DecimalField(
        max_digits=7, decimal_places=2, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "time"]
        indexes = [
            models.Index(fields=["customer", "date"], name="booking_customer_date_idx"),
            models.Index(fields=["status", "date"], name="booking_status_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(price_at_booking__gte=0),
                name="booking_price_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference or 'New booking'}: {self.service} on {self.date}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.price_at_booking is None:
            self.price_at_booking = self.service.price
        super().save(*args, **kwargs)

    @property
    def reference(self) -> str:
        """Readable booking reference such as DW-0042 (empty until saved)."""
        return f"DW-{self.pk:04d}" if self.pk else ""

    @property
    def appointment_at(self):
        """The appointment as an aware Central Time datetime."""
        return combine_central(self.date, self.time)

    @property
    def is_past(self) -> bool:
        """True once the appointment time has passed in Central Time."""
        return is_past_central(self.date, self.time)
