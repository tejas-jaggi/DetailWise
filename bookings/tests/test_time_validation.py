"""Central Time rules for appointment validation.

`django.utils.timezone.now` is patched to a fixed instant so the tests never
depend on the real clock.
"""

import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from bookings.forms import BookingForm
from bookings.models import Booking, Service
from bookings.timeutils import (
    combine_central,
    is_nonexistent_central,
    is_past_central,
)

CT = ZoneInfo("America/Chicago")
UTC = datetime.timezone.utc


def at_central(*args):
    """A fixed 'now' expressed in Central Time."""
    return datetime.datetime(*args, tzinfo=CT)


def frozen(now):
    return mock.patch("django.utils.timezone.now", return_value=now.astimezone(UTC))


class TimeUtilsTests(TestCase):
    def test_summer_offset_is_cdt(self):
        dt = combine_central(datetime.date(2027, 7, 1), datetime.time(12, 0))
        self.assertEqual(dt.utcoffset(), datetime.timedelta(hours=-5))

    def test_winter_offset_is_cst(self):
        dt = combine_central(datetime.date(2027, 1, 15), datetime.time(12, 0))
        self.assertEqual(dt.utcoffset(), datetime.timedelta(hours=-6))

    def test_spring_forward_gap_time_is_nonexistent(self):
        # 2027-03-14: clocks jump from 2:00 to 3:00 AM in Central Time.
        self.assertTrue(is_nonexistent_central(datetime.date(2027, 3, 14), datetime.time(2, 30)))
        self.assertFalse(is_nonexistent_central(datetime.date(2027, 3, 14), datetime.time(3, 30)))

    def test_fall_back_repeated_time_exists(self):
        # 2027-11-07: 1:00-1:59 AM happens twice; it is valid, not nonexistent.
        self.assertFalse(is_nonexistent_central(datetime.date(2027, 11, 7), datetime.time(1, 30)))

    def test_is_past_compares_full_datetime(self):
        now = at_central(2026, 11, 10, 15, 0)
        self.assertTrue(is_past_central(datetime.date(2026, 11, 10), datetime.time(14, 59), now=now))
        self.assertTrue(is_past_central(datetime.date(2026, 11, 10), datetime.time(15, 0), now=now))
        self.assertFalse(is_past_central(datetime.date(2026, 11, 10), datetime.time(15, 1), now=now))

    def test_is_past_uses_current_time_by_default(self):
        with frozen(at_central(2026, 11, 10, 15, 0)):
            self.assertTrue(is_past_central(datetime.date(2026, 11, 10), datetime.time(9, 0)))
            self.assertFalse(is_past_central(datetime.date(2026, 11, 10), datetime.time(16, 0)))


class BookingFormTimeValidationTests(TestCase):
    def setUp(self):
        self.service = Service.objects.get(slug="exterior-wash")

    def form(self, date, time, service=None):
        return BookingForm(data={
            "service": (service or self.service).pk,
            "date": date,
            "time": time,
        })

    def test_future_appointment_accepted(self):
        with frozen(at_central(2026, 11, 10, 15, 0)):
            form = self.form("2026-11-12", "10:00")
            self.assertTrue(form.is_valid(), form.errors)

    def test_past_date_rejected(self):
        with frozen(at_central(2026, 11, 10, 15, 0)):
            form = self.form("2026-11-09", "10:00")
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors["date"], ["Choose today or a later date (Central Time)."])

    def test_same_day_past_time_rejected(self):
        with frozen(at_central(2026, 11, 10, 15, 0)):
            form = self.form("2026-11-10", "14:30")
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors["time"],
                ["That time has already passed today. Choose a later time (Central Time)."],
            )

    def test_same_day_later_time_accepted(self):
        with frozen(at_central(2026, 11, 10, 15, 0)):
            self.assertTrue(self.form("2026-11-10", "15:30").is_valid())

    def test_uses_central_time_not_utc(self):
        # 11:30 PM CT on Nov 10 is already 05:30 UTC on Nov 11.
        with frozen(at_central(2026, 11, 10, 23, 30)):
            # Still Nov 10 in Central Time, so 11:45 PM tonight is in the future...
            self.assertTrue(self.form("2026-11-10", "23:45").is_valid())
            # ...and 11:00 PM tonight is in the past, even though UTC says "tomorrow".
            self.assertFalse(self.form("2026-11-10", "23:00").is_valid())

    def test_central_date_not_server_date_early_morning(self):
        # 00:30 UTC on Nov 11 is still 6:30 PM on Nov 10 in Central Time.
        now = datetime.datetime(2026, 11, 11, 0, 30, tzinfo=UTC)
        with mock.patch("django.utils.timezone.now", return_value=now):
            self.assertTrue(self.form("2026-11-10", "19:00").is_valid())

    def test_rejects_nonexistent_dst_time(self):
        with frozen(at_central(2027, 3, 1, 9, 0)):
            form = self.form("2027-03-14", "02:30")
            self.assertFalse(form.is_valid())
            self.assertIn("daylight saving", form.errors["time"][0])

    def test_accepts_repeated_fall_back_time(self):
        with frozen(at_central(2027, 10, 1, 9, 0)):
            self.assertTrue(self.form("2027-11-07", "01:30").is_valid())

    def test_inactive_service_rejected(self):
        inactive = Service.objects.get(slug="full-detail")
        inactive.is_active = False
        inactive.save()
        with frozen(at_central(2026, 11, 10, 15, 0)):
            form = self.form("2026-11-12", "10:00", service=inactive)
            self.assertFalse(form.is_valid())
            self.assertEqual(form.errors["service"], ["Select an available service."])

    def test_required_fields_have_clear_messages(self):
        form = BookingForm(data={})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["service"], ["Choose a service."])
        self.assertEqual(form.errors["date"], ["Choose a date."])
        self.assertEqual(form.errors["time"], ["Choose a time."])

    def test_form_only_exposes_service_date_time(self):
        self.assertEqual(list(BookingForm().fields), ["service", "date", "time"])


# On 2026-11-01 clocks fall back, so 1:00-1:59 AM happens twice. A booked time in
# that hour means the first occurrence (CDT, UTC-5), e.g. 1:30 AM = 06:30 UTC.
FALL_BACK_DATE = datetime.date(2026, 11, 1)
FIRST_115_AM = datetime.datetime(2026, 11, 1, 6, 15, tzinfo=UTC)   # 1:15 AM CDT
SECOND_115_AM = datetime.datetime(2026, 11, 1, 7, 15, tzinfo=UTC)  # 1:15 AM CST


class FallBackRepeatedHourTests(TestCase):
    """Past/future checks must compare real instants during the repeated hour."""

    def setUp(self):
        self.service = Service.objects.get(slug="exterior-wash")

    def form(self, time):
        return BookingForm(data={"service": self.service.pk, "date": FALL_BACK_DATE.isoformat(), "time": time})

    def test_first_occurrence_is_past_during_second_occurrence(self):
        # 1:30 AM CDT (06:30 UTC) ended 45 minutes before 1:15 AM CST (07:15 UTC).
        with frozen(SECOND_115_AM):
            self.assertTrue(is_past_central(FALL_BACK_DATE, datetime.time(1, 30)))

    def test_later_time_is_future_during_first_occurrence(self):
        # 1:45 AM CDT (06:45 UTC) is still ahead of 1:15 AM CDT (06:15 UTC).
        with frozen(FIRST_115_AM):
            self.assertFalse(is_past_central(FALL_BACK_DATE, datetime.time(1, 45)))

    def test_form_rejects_first_occurrence_after_it_passed(self):
        with frozen(SECOND_115_AM):
            form = self.form("01:30")
            self.assertFalse(form.is_valid())
            self.assertEqual(
                form.errors["time"],
                ["That time has already passed today. Choose a later time (Central Time)."],
            )

    def test_form_accepts_later_time_after_fall_back(self):
        # 2:30 AM CST is 08:30 UTC, still in the future at 07:15 UTC.
        with frozen(SECOND_115_AM):
            form = self.form("02:30")
            self.assertTrue(form.is_valid(), form.errors)

    def test_booking_is_past_uses_real_instants(self):
        customer = get_user_model().objects.create_user("casey", password="detail-wise-Test-9")
        booking = Booking.objects.create(
            customer=customer, service=self.service, date=FALL_BACK_DATE, time=datetime.time(1, 30)
        )
        with frozen(SECOND_115_AM):
            self.assertTrue(booking.is_past)
        with frozen(FIRST_115_AM):
            self.assertFalse(booking.is_past)
