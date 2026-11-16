"""Customer booking changes, including authorization and Central Time edges."""

import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from bookings.models import Booking, Service
from bookings.forms import BookingForm
from bookings.tests.test_time_validation import at_central, frozen

User = get_user_model()


class BookingManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user("casey")
        cls.other = User.objects.create_user("riley")
        cls.staff = User.objects.create_user("sam", is_staff=True)
        cls.service = Service.objects.get(slug="exterior-wash")
        cls.alternative = Service.objects.get(slug="interior-clean")
        cls.booking = Booking.objects.create(
            customer=cls.customer, service=cls.service,
            date=datetime.date(2026, 11, 20), time=datetime.time(10),
        )

    def setUp(self):
        clock = frozen(at_central(2026, 11, 10, 15, 0))
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_login(self.customer)
        self.edit_url = reverse("bookings:edit", args=[self.booking.pk])
        self.cancel_url = reverse("bookings:cancel", args=[self.booking.pk])
        self.detail_url = reverse("bookings:detail", args=[self.booking.pk])

    def data(self, **extra):
        values = {"service": self.alternative.pk, "date": "2026-11-21", "time": "13:30"}
        values.update(extra)
        return values

    def snapshot(self):
        return Booking.objects.values().get(pk=self.booking.pk)

    def test_edit_form_is_prefilled_and_posts_to_edit(self):
        before = self.snapshot()
        response = self.client.get(self.edit_url)
        self.assertEqual(response.context["form"].instance.pk, self.booking.pk)
        self.assertEqual(response.context["form"].initial["service"], self.service.pk)
        self.assertContains(response, 'value="2026-11-20"')
        self.assertContains(response, 'value="10:00"')
        self.assertContains(response, f'action="{self.edit_url}"')
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertEqual(self.snapshot(), before)

    def test_edit_updates_service_date_time_and_price(self):
        created_at = self.booking.created_at
        response = self.client.post(self.edit_url, self.data(), follow=True)
        self.assertRedirects(response, self.detail_url)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.service, self.alternative)
        self.assertEqual(self.booking.date, datetime.date(2026, 11, 21))
        self.assertEqual(self.booking.time, datetime.time(13, 30))
        self.assertEqual(self.booking.price_at_booking, self.alternative.price)
        self.assertEqual(self.booking.created_at, created_at)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertContains(response, f"Booking {self.booking.reference} updated.")

    def test_rescheduling_keeps_price_snapshot(self):
        Service.objects.filter(pk=self.service.pk).update(price=Decimal("75.00"))
        self.client.post(self.edit_url, self.data(service=self.service.pk))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.price_at_booking, Decimal("35.00"))

    def test_post_cannot_override_protected_fields(self):
        self.client.post(self.edit_url, self.data(
            customer=self.other.pk, status="cancelled", price_at_booking="0.01",
            id=99999, created_at="2000-01-01",
        ))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.customer, self.customer)
        self.assertEqual(self.booking.status, Booking.Status.SAVED)
        self.assertEqual(self.booking.price_at_booking, self.alternative.price)

    def test_invalid_edits_leave_entire_record_unchanged(self):
        cases = [
            ({"service": ""}, "service"), ({"service": "99999"}, "service"),
            ({"service": "invalid"}, "service"),
            ({"date": ""}, "date"), ({"date": "2026-02-30"}, "date"),
            ({"date": "2026-11-09"}, "date"),
            ({"time": ""}, "time"), ({"time": "25:00"}, "time"),
            ({"date": "2026-11-10", "time": "14:59"}, "time"),
            ({"date": "2026-11-10", "time": "15:00"}, "time"),
            ({"date": "2027-03-14", "time": "02:30"}, "time"),
        ]
        before = self.snapshot()
        for values, field in cases:
            with self.subTest(values=values):
                response = self.client.post(self.edit_url, self.data(**values))
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(self.snapshot(), before)

    def test_inactive_service_rejected_even_if_current_service(self):
        Service.objects.filter(pk=self.service.pk).update(is_active=False)
        before = self.snapshot()
        response = self.client.post(self.edit_url, self.data(service=self.service.pk))
        self.assertFormError(response.context["form"], "service", "Select an available service.")
        self.assertEqual(self.snapshot(), before)
        self.assertRedirects(self.client.post(self.edit_url, self.data()), self.detail_url)

    def test_same_day_future_edit_uses_central_date_not_utc(self):
        with frozen(at_central(2026, 11, 10, 23, 30)):
            response = self.client.post(self.edit_url, self.data(date="2026-11-10", time="23:45"))
        self.assertRedirects(response, self.detail_url)

    def test_fall_back_first_occurrence_can_be_booked(self):
        response = self.client.post(self.edit_url, self.data(date="2027-11-07", time="01:30"))
        self.assertRedirects(response, self.detail_url)

    def test_cancel_changes_only_status_and_updated_at_and_moves_to_history(self):
        before = self.snapshot()
        response = self.client.post(self.cancel_url, self.data(customer=self.other.pk), follow=True)
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        after = self.snapshot()
        self.assertEqual(after.pop("status"), Booking.Status.CANCELLED)
        before.pop("status")
        after.pop("updated_at")
        before.pop("updated_at")
        self.assertEqual(after, before)
        self.assertEqual(list(response.context["upcoming"]), [])
        self.assertEqual(list(response.context["history"]), [self.booking])
        self.assertContains(response, f"Booking {self.booking.reference} cancelled.")

    def test_repeated_cancellation_and_stale_edit_after_cancel_are_rejected(self):
        self.client.get(self.edit_url)
        self.client.post(self.cancel_url)
        before = self.snapshot()
        for url in [self.edit_url, self.cancel_url]:
            self.assertEqual(self.client.post(url, self.data()).status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_anonymous_requests_redirect_without_mutation(self):
        self.client.logout()
        before = self.snapshot()
        for method, url in [("get", self.edit_url), ("post", self.edit_url), ("post", self.cancel_url)]:
            response = getattr(self.client, method)(url, self.data())
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("accounts:login") + "?next="))
        self.assertEqual(self.snapshot(), before)

    def test_staff_and_other_customers_cannot_access_or_modify(self):
        before = self.snapshot()
        for user, status in [(self.staff, 403), (self.other, 404)]:
            self.client.force_login(user)
            for method, url in [("get", self.edit_url), ("post", self.edit_url), ("post", self.cancel_url)]:
                with self.subTest(user=user, method=method, url=url):
                    response = getattr(self.client, method)(url, self.data())
                    self.assertEqual(response.status_code, status)
                    if status == 404:
                        self.assertTemplateUsed(response, "bookings/booking_not_found.html")
                        self.assertNotContains(response, self.booking.reference, status_code=404)
                    self.assertEqual(self.snapshot(), before)

    def test_missing_booking_returns_same_not_found_page(self):
        for action in ["edit", "cancel"]:
            response = self.client.post(reverse(f"bookings:{action}", args=[99999]), self.data())
            self.assertContains(response, "Booking not found", status_code=404)

    def test_past_cancelled_and_exact_start_bookings_cannot_be_changed(self):
        for changes in [
            {"status": Booking.Status.CANCELLED},
            {"date": datetime.date(2026, 11, 9)},
            {"date": datetime.date(2026, 11, 10), "time": datetime.time(14, 59)},
            {"date": datetime.date(2026, 11, 10), "time": datetime.time(15)},
        ]:
            Booking.objects.filter(pk=self.booking.pk).update(
                status=Booking.Status.SAVED, date=datetime.date(2026, 11, 20), time=datetime.time(10),
            )
            Booking.objects.filter(pk=self.booking.pk).update(**changes)
            before = self.snapshot()
            for method, url in [("get", self.edit_url), ("post", self.edit_url), ("post", self.cancel_url)]:
                with self.subTest(changes=changes, method=method, url=url):
                    response = getattr(self.client, method)(url, self.data())
                    self.assertContains(response, "Booking cannot be changed", status_code=403)
                    self.assertEqual(self.snapshot(), before)
            response = self.client.get(self.detail_url)
            self.assertNotContains(response, self.edit_url)
            self.assertNotContains(response, self.cancel_url)

    def test_stale_form_cannot_reschedule_booking_after_start(self):
        self.client.get(self.edit_url)
        with frozen(at_central(2026, 11, 20, 10, 0)):
            before = self.snapshot()
            self.assertEqual(self.client.post(self.edit_url, self.data()).status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_original_appointment_starting_during_validation_rejects_edit(self):
        before = self.snapshot()
        original_clean = BookingForm.clean
        with frozen(at_central(2026, 11, 20, 9, 59)) as clock:
            def clean_and_advance(form):
                cleaned = original_clean(form)
                clock.return_value = at_central(2026, 11, 20, 10, 0)
                return cleaned

            with mock.patch.object(BookingForm, "clean", clean_and_advance):
                response = self.client.post(self.edit_url, self.data())
        self.assertContains(response, "Booking cannot be changed", status_code=403)
        self.assertEqual(self.snapshot(), before)

    def test_proposed_appointment_starting_during_validation_rejects_edit(self):
        before = self.snapshot()
        original_clean = BookingForm.clean
        with frozen(at_central(2026, 11, 10, 15, 0)) as clock:
            def clean_and_advance(form):
                cleaned = original_clean(form)
                clock.return_value = at_central(2026, 11, 10, 15, 1)
                return cleaned

            with mock.patch.object(BookingForm, "clean", clean_and_advance):
                response = self.client.post(
                    self.edit_url, self.data(date="2026-11-10", time="15:01"),
                )
        self.assertEqual(response.status_code, 200)
        self.assertIn("time", response.context["form"].errors)
        self.assertEqual(self.snapshot(), before)

    def test_fall_back_booking_is_past_during_second_occurrence(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            date=datetime.date(2026, 11, 1), time=datetime.time(1, 30),
        )
        now = datetime.datetime(2026, 11, 1, 7, 15, tzinfo=datetime.timezone.utc)
        with frozen(now):
            before = self.snapshot()
            for url in [self.edit_url, self.cancel_url]:
                self.assertEqual(self.client.post(url, self.data()).status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_unsupported_methods_do_not_mutate(self):
        before = self.snapshot()
        for method in ["get", "head", "put", "patch", "delete"]:
            self.assertEqual(getattr(self.client, method)(self.cancel_url).status_code, 405)
        for method in ["put", "patch", "delete"]:
            self.assertEqual(getattr(self.client, method)(self.edit_url).status_code, 405)
        self.assertEqual(self.snapshot(), before)

    def test_csrf_required_and_valid_token_allows_edit_and_cancel(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        before = self.snapshot()
        for url in [self.edit_url, self.cancel_url]:
            for token in [None, "invalid"]:
                data = self.data()
                if token:
                    data["csrfmiddlewaretoken"] = token
                self.assertEqual(client.post(url, data).status_code, 403)
                self.assertEqual(self.snapshot(), before)
        response = client.get(self.detail_url)
        self.assertContains(response, f'action="{self.cancel_url}"')
        self.assertContains(response, f'href="{self.edit_url}"')
        token = client.cookies["csrftoken"].value
        self.assertRedirects(client.post(self.edit_url, self.data(csrfmiddlewaretoken=token)), self.detail_url)
        self.assertRedirects(
            client.post(self.cancel_url, {"csrfmiddlewaretoken": token}), reverse("bookings:my_bookings"),
        )
