import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bookings.models import Booking, Service
from bookings.timeutils import central_now

User = get_user_model()
PASSWORD = "detail-wise-Test-9"


def future_date(days=7):
    return central_now().date() + datetime.timedelta(days=days)


class CatalogViewTests(TestCase):
    url = reverse("bookings:catalog")

    def test_catalog_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_catalog_lists_three_seeded_services_with_prices(self):
        response = self.client.get(self.url)
        for name, price in [("Exterior Wash", "$35"), ("Interior Clean", "$60"), ("Full Detail", "$95")]:
            self.assertContains(response, name)
            self.assertContains(response, price)
        self.assertEqual(len(response.context["services"]), 3)

    def test_catalog_excludes_inactive_services(self):
        Service.objects.filter(slug="full-detail").update(is_active=False)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Full Detail")
        self.assertEqual(len(response.context["services"]), 2)

    def test_book_link_keeps_selected_service(self):
        response = self.client.get(self.url)
        self.assertContains(response, reverse("bookings:create") + "?service=exterior-wash")


class CreateBookingViewTests(TestCase):
    url = reverse("bookings:create")

    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.service = Service.objects.get(slug="exterior-wash")

    def valid_data(self, **extra):
        data = {"service": self.service.pk, "date": future_date().isoformat(), "time": "10:00"}
        data.update(extra)
        return data

    def test_anonymous_user_redirected_to_sign_in_with_next(self):
        response = self.client.get(self.url + "?service=exterior-wash")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login") + "?next="))
        self.assertIn("service%3Dexterior-wash", response.url)

    def test_anonymous_post_creates_nothing(self):
        self.client.post(self.url, self.valid_data())
        self.assertEqual(Booking.objects.count(), 0)

    def test_customer_sees_booking_form(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_selected_service_is_preselected(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url, {"service": "interior-clean"})
        self.assertEqual(
            response.context["form"].initial["service"],
            Service.objects.get(slug="interior-clean").pk,
        )

    def test_unknown_or_inactive_service_param_is_ignored(self):
        Service.objects.filter(slug="full-detail").update(is_active=False)
        self.client.force_login(self.customer)
        for slug in ["does-not-exist", "full-detail"]:
            response = self.client.get(self.url, {"service": slug})
            self.assertNotIn("service", response.context["form"].initial)

    def test_customer_creates_booking_and_it_is_persisted(self):
        self.client.force_login(self.customer)
        response = self.client.post(self.url, self.valid_data(), follow=True)
        booking = Booking.objects.get()
        self.assertEqual(booking.customer, self.customer)
        self.assertEqual(booking.service, self.service)
        self.assertEqual(booking.status, Booking.Status.SAVED)
        self.assertEqual(booking.price_at_booking, Decimal("35.00"))
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        messages = [str(m) for m in response.context["messages"]]
        self.assertIn(f"Booking saved. Your reference is {booking.reference}.", messages)
        self.assertContains(response, booking.reference)

    def test_post_cannot_choose_customer_or_price(self):
        other = User.objects.create_user("other", password=PASSWORD)
        self.client.force_login(self.customer)
        self.client.post(self.url, self.valid_data(customer=other.pk, price_at_booking="1.00"))
        booking = Booking.objects.get()
        self.assertEqual(booking.customer, self.customer)
        self.assertEqual(booking.price_at_booking, Decimal("35.00"))

    def test_invalid_post_shows_errors_and_saves_nothing(self):
        self.client.force_login(self.customer)
        yesterday = (central_now().date() - datetime.timedelta(days=1)).isoformat()
        response = self.client.post(self.url, self.valid_data(date=yesterday))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose today or a later date (Central Time).")
        self.assertEqual(Booking.objects.count(), 0)

    def test_inactive_service_cannot_be_booked(self):
        Service.objects.filter(pk=self.service.pk).update(is_active=False)
        self.client.force_login(self.customer)
        response = self.client.post(self.url, self.valid_data())
        self.assertContains(response, "Select an available service.")
        self.assertEqual(Booking.objects.count(), 0)

    def test_staff_cannot_create_bookings(self):
        staff = User.objects.create_user("sam", password=PASSWORD, is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        response = self.client.post(self.url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Booking.objects.count(), 0)

    def test_post_without_csrf_token_rejected(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        response = client.post(self.url, self.valid_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Booking.objects.count(), 0)


class MyBookingsViewTests(TestCase):
    url = reverse("bookings:my_bookings")

    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.other = User.objects.create_user("riley", password=PASSWORD)
        self.service = Service.objects.get(slug="full-detail")

    def book(self, customer, **extra):
        values = {"customer": customer, "service": self.service, "date": future_date(), "time": datetime.time(9, 0)}
        values.update(extra)
        return Booking.objects.create(**values)

    def test_anonymous_redirected_to_sign_in(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_empty_state(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertContains(response, "No bookings yet")

    def test_customer_sees_only_own_bookings(self):
        mine = self.book(self.customer)
        theirs = self.book(self.other)
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertContains(response, mine.reference)
        self.assertNotContains(response, theirs.reference)

    def test_past_and_cancelled_bookings_listed_separately(self):
        upcoming = self.book(self.customer)
        past = self.book(self.customer, date=central_now().date() - datetime.timedelta(days=3))
        cancelled = self.book(self.customer, status=Booking.Status.CANCELLED)
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertEqual(list(response.context["upcoming"]), [upcoming])
        self.assertCountEqual(response.context["history"], [past, cancelled])

    def test_fall_back_first_occurrence_listed_as_past(self):
        # 1:30 AM CDT on 2026-11-01 is 06:30 UTC; at 07:15 UTC (1:15 AM CST) it has passed.
        booking = self.book(self.customer, date=datetime.date(2026, 11, 1), time=datetime.time(1, 30))
        self.client.force_login(self.customer)
        now = datetime.datetime(2026, 11, 1, 7, 15, tzinfo=datetime.timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=now):
            response = self.client.get(self.url)
        self.assertEqual(list(response.context["upcoming"]), [])
        self.assertEqual(list(response.context["history"]), [booking])

    def test_staff_get_403(self):
        staff = User.objects.create_user("sam", password=PASSWORD, is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class BookingDetailViewTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.other = User.objects.create_user("riley", password=PASSWORD)
        self.booking = Booking.objects.create(
            customer=self.customer,
            service=Service.objects.get(slug="interior-clean"),
            date=future_date(),
            time=datetime.time(13, 30),
        )
        self.url = reverse("bookings:detail", args=[self.booking.pk])

    def test_owner_can_view_booking(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertContains(response, self.booking.reference)
        self.assertContains(response, "Interior Clean")

    def test_other_customer_gets_booking_not_found(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Booking not found", status_code=404)
        self.assertNotContains(response, "Interior Clean", status_code=404)

    def test_missing_booking_gets_booking_not_found(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("bookings:detail", args=[99999]))
        self.assertContains(response, "Booking not found", status_code=404)

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
