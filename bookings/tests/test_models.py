import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from bookings.models import Booking, Service

User = get_user_model()


def make_service(**overrides):
    values = {
        "name": "Test Polish",
        "slug": "test-polish",
        "description": "A service used only in tests.",
        "price": Decimal("50.00"),
        "weather_sensitivity": Service.WeatherSensitivity.EXTERIOR,
    }
    values.update(overrides)
    return Service.objects.create(**values)


def make_booking(customer, service, **overrides):
    values = {
        "customer": customer,
        "service": service,
        "date": datetime.date(2030, 6, 1),
        "time": datetime.time(10, 0),
    }
    values.update(overrides)
    return Booking.objects.create(**values)


class CustomUserModelTests(TestCase):
    def test_auth_user_model_is_accounts_user(self):
        self.assertEqual(User._meta.label, "accounts.User")


class ServiceModelTests(TestCase):
    def test_service_creation_defaults(self):
        service = make_service()
        self.assertTrue(service.is_active)
        self.assertEqual(service.price, Decimal("50.00"))
        self.assertEqual(str(service), "Test Polish")

    def test_negative_price_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_service(price=Decimal("-1.00"))

    def test_zero_price_allowed(self):
        self.assertEqual(make_service(price=Decimal("0.00")).price, Decimal("0.00"))

    def test_service_name_and_slug_unique(self):
        make_service()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_service(slug="another-slug")  # same name
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_service(name="Another Name")  # same slug

    def test_service_with_bookings_cannot_be_deleted(self):
        service = make_service()
        customer = User.objects.create_user("casey", password="pw-not-used-1")
        make_booking(customer, service)
        with self.assertRaises(ProtectedError):
            service.delete()

    def test_service_without_bookings_can_be_deleted(self):
        service = make_service()
        service.delete()
        self.assertFalse(Service.objects.filter(slug="test-polish").exists())


class BookingModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("casey", password="pw-not-used-1")
        self.service = make_service()

    def test_booking_relationships(self):
        booking = make_booking(self.customer, self.service)
        self.assertEqual(booking.customer, self.customer)
        self.assertEqual(booking.service, self.service)
        self.assertIn(booking, self.customer.bookings.all())
        self.assertIn(booking, self.service.bookings.all())

    def test_new_booking_is_saved_status(self):
        booking = make_booking(self.customer, self.service)
        self.assertEqual(booking.status, Booking.Status.SAVED)

    def test_reference_derived_from_primary_key(self):
        booking = make_booking(self.customer, self.service)
        self.assertEqual(booking.reference, f"DW-{booking.pk:04d}")

    def test_reference_format_example(self):
        booking = Booking(pk=7, customer=self.customer, service=self.service)
        self.assertEqual(booking.reference, "DW-0007")

    def test_unsaved_booking_has_no_reference(self):
        self.assertEqual(Booking(service=self.service).reference, "")

    def test_price_snapshot_taken_on_creation(self):
        booking = make_booking(self.customer, self.service)
        self.assertEqual(booking.price_at_booking, Decimal("50.00"))

    def test_price_snapshot_survives_service_price_change(self):
        booking = make_booking(self.customer, self.service)
        self.service.price = Decimal("80.00")
        self.service.save()
        booking.refresh_from_db()
        booking.save()  # re-saving must not overwrite the snapshot
        booking.refresh_from_db()
        self.assertEqual(booking.price_at_booking, Decimal("50.00"))

    def test_deleting_customer_deletes_their_bookings(self):
        make_booking(self.customer, self.service)
        self.customer.delete()
        self.assertEqual(Booking.objects.count(), 0)

    def test_appointment_at_is_aware_central_time(self):
        booking = make_booking(self.customer, self.service)
        self.assertEqual(str(booking.appointment_at.tzinfo), "America/Chicago")
        self.assertEqual(booking.appointment_at.hour, 10)

    def test_is_past_uses_central_time_now(self):
        from unittest import mock
        from zoneinfo import ZoneInfo

        booking = make_booking(
            self.customer, self.service,
            date=datetime.date(2026, 11, 10), time=datetime.time(14, 0),
        )
        now = datetime.datetime(2026, 11, 10, 15, 0, tzinfo=ZoneInfo("America/Chicago"))
        with mock.patch("django.utils.timezone.now", return_value=now):
            self.assertTrue(booking.is_past)
        with mock.patch("django.utils.timezone.now", return_value=now - datetime.timedelta(hours=2)):
            self.assertFalse(booking.is_past)
