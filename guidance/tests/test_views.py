"""Tests for the customer-only guidance JSON endpoints (plan Task 7, D7).

The service layer is mocked where a test is about the HTTP contract. Tests about
real outcomes (horizon, external failures) mock only the network: the weather and
Ollama ``urlopen`` calls. "Today" is frozen at 2026-11-10 (Central).
"""

import datetime
import io
import json
from unittest import mock
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bookings.forms import BookingForm
from bookings.models import Booking, Service
from guidance import service as guidance_service
from guidance.tests.fixtures import forecast_payload

User = get_user_model()
PASSWORD = "detail-wise-Test-9"
TODAY = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.timezone.utc)  # 12:00 CST
FORECAST_URL = reverse("guidance:forecast")
EXPLAIN_URL = reverse("guidance:explain")
SECRET = "http://10.0.0.5:11434 internal-host-detail"


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def weather_ok(*args, **kwargs):
    return FakeResponse(json.dumps(forecast_payload()).encode("utf-8"))


def stub_result(status="available"):
    return guidance_service.GuidanceResult(status, message="stub message")


class GuidanceViewTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patch = mock.patch("django.utils.timezone.now", return_value=TODAY)
        patch.start()
        self.addCleanup(patch.stop)
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.service = Service.objects.get(slug="exterior-wash")
        self.client.force_login(self.customer)

    def data(self, **changes):
        data = {"service": str(self.service.pk), "date": "2026-11-12", "time": "10:00"}
        data.update(changes)
        return {key: value for key, value in data.items() if value is not None}

    def get_forecast(self, client=None, **changes):
        return (client or self.client).get(FORECAST_URL, self.data(**changes))

    def post_explain(self, client=None, **changes):
        return (client or self.client).post(EXPLAIN_URL, self.data(**changes))

    def assertJson(self, response, status_code):
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(response["Content-Type"], "application/json")
        return response.json()


class AccessTests(GuidanceViewTestCase):
    def test_anonymous_gets_401_json(self):
        anonymous = Client()
        for response in (self.get_forecast(anonymous), self.post_explain(anonymous)):
            with self.subTest(url=response.request["PATH_INFO"]):
                self.assertEqual(self.assertJson(response, 401), {"status": "auth_required"})

    def test_staff_get_403_json(self):
        staff = Client()
        staff.force_login(User.objects.create_user("sam", password=PASSWORD, is_staff=True))
        for response in (self.get_forecast(staff), self.post_explain(staff)):
            with self.subTest(url=response.request["PATH_INFO"]):
                self.assertEqual(self.assertJson(response, 403), {"status": "forbidden"})

    def test_anonymous_and_staff_never_reach_the_service(self):
        staff = Client()
        staff.force_login(User.objects.create_user("sam", password=PASSWORD, is_staff=True))
        with mock.patch.object(guidance_service, "get_forecast") as get_forecast, \
                mock.patch.object(guidance_service, "get_explanation") as get_explanation:
            for client in (Client(), staff):
                self.get_forecast(client)
                self.post_explain(client)
        get_forecast.assert_not_called()
        get_explanation.assert_not_called()


class SuccessTests(GuidanceViewTestCase):
    def test_customer_forecast_success(self):
        result = stub_result()
        with mock.patch.object(guidance_service, "get_forecast", return_value=result) as fake:
            response = self.get_forecast()
        self.assertEqual(self.assertJson(response, 200), result.to_json())
        fake.assert_called_once_with(self.service, datetime.date(2026, 11, 12),
                                     datetime.time(10, 0))

    def test_customer_explain_success(self):
        result = stub_result()
        with mock.patch.object(guidance_service, "get_explanation",
                               return_value=result) as fake:
            response = self.post_explain()
        self.assertEqual(self.assertJson(response, 200), result.to_json())
        fake.assert_called_once_with(self.service, datetime.date(2026, 11, 12),
                                     datetime.time(10, 0))

    def test_time_is_optional(self):
        for changes in (dict(time=None), dict(time="")):
            with self.subTest(changes=changes):
                with mock.patch.object(guidance_service, "get_forecast",
                                       return_value=stub_result()) as forecast, \
                        mock.patch.object(guidance_service, "get_explanation",
                                          return_value=stub_result()) as explain:
                    self.assertEqual(self.get_forecast(**changes).status_code, 200)
                    self.assertEqual(self.post_explain(**changes).status_code, 200)
                self.assertIsNone(forecast.call_args.args[2])
                self.assertIsNone(explain.call_args.args[2])

    def test_today_is_accepted(self):
        # "Now" is 12:00 CST on Nov 10: a later time, or no time, is accepted.
        with mock.patch.object(guidance_service, "get_forecast",
                               return_value=stub_result()):
            for time_value in ("12:01", "23:59", None):
                with self.subTest(time=time_value):
                    response = self.get_forecast(date="2026-11-10", time=time_value)
                    self.assertEqual(response.status_code, 200)

    def test_responses_are_not_cached_by_browsers(self):
        with mock.patch.object(guidance_service, "get_forecast", return_value=stub_result()):
            response = self.get_forecast()
        self.assertIn("no-store", response["Cache-Control"])

    def test_browser_cannot_choose_model_url_or_weather(self):
        # Extra fields are ignored; only service, date and time reach the service.
        with mock.patch.object(guidance_service, "get_explanation",
                               return_value=stub_result()) as fake:
            self.client.post(EXPLAIN_URL, {**self.data(), "model": "evil",
                                           "OLLAMA_BASE_URL": SECRET, "prompt": "x",
                                           "peak_rain_chance_pct": "99"})
        self.assertEqual(len(fake.call_args.args), 3)
        self.assertEqual(fake.call_args.kwargs, {})


class MethodAndCsrfTests(GuidanceViewTestCase):
    def test_methods_enforced(self):
        self.assertEqual(self.client.post(FORECAST_URL, self.data()).status_code, 405)
        self.assertEqual(self.client.get(EXPLAIN_URL, self.data()).status_code, 405)
        self.assertEqual(self.client.put(EXPLAIN_URL).status_code, 405)

    def test_explain_without_csrf_token_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        with mock.patch.object(guidance_service, "get_explanation") as fake:
            response = self.post_explain(client)
        self.assertEqual(response.status_code, 403)
        fake.assert_not_called()

    def test_explain_with_csrf_token_accepted(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        client.get(reverse("bookings:create"))  # sets the csrftoken cookie
        token = client.cookies["csrftoken"].value
        with mock.patch.object(guidance_service, "get_explanation",
                               return_value=stub_result()):
            response = client.post(EXPLAIN_URL, self.data(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)


class InputValidationTests(GuidanceViewTestCase):
    def assertInvalid(self, field, message, **changes):
        with mock.patch.object(guidance_service, "get_forecast") as forecast, \
                mock.patch.object(guidance_service, "get_explanation") as explain:
            responses = (self.get_forecast(**changes), self.post_explain(**changes))
        forecast.assert_not_called()
        explain.assert_not_called()
        for response in responses:
            body = self.assertJson(response, 400)
            self.assertEqual(body["status"], "invalid")
            self.assertEqual(body["errors"][field], [message])

    def test_invalid_service_ids_400(self):
        Service.objects.filter(slug="full-detail").update(is_active=False)
        inactive = Service.objects.get(slug="full-detail")
        self.assertInvalid("service", "Choose a service.", service=None)
        for value in ("abc", "999999", str(inactive.pk), "-1", "1.5"):
            with self.subTest(service=value):
                self.assertInvalid("service", "Select an available service.", service=value)

    def test_invalid_dates_400(self):
        self.assertInvalid("date", "Choose a date.", date=None)
        self.assertInvalid("date", "Choose a date.", date="")
        for value in ("2026-13-01", "2026-02-30", "tomorrow", "11/12/2026", "2026-11-12T10:00"):
            with self.subTest(date=value):
                self.assertInvalid("date", "Enter a valid date.", date=value)
        self.assertInvalid("date", "Choose today or a later date (Central Time).",
                           date="2026-11-09")

    def test_invalid_time_400(self):
        for value in ("25:00", "noon", "10:61", "10"):
            with self.subTest(time=value):
                self.assertInvalid("time", "Enter a valid time.", time=value)

    def test_past_time_today_400_like_the_booking_form(self):
        # "Now" is 12:00 CST on Nov 10; the booking form rejects 12:00 and earlier.
        message = "That time has already passed today. Choose a later time (Central Time)."
        for value in ("00:00", "11:59", "12:00"):
            with self.subTest(time=value):
                self.assertInvalid("time", message, date="2026-11-10", time=value)
        booking_form = BookingForm(data={"service": self.service.pk, "date": "2026-11-10",
                                         "time": "11:59"})
        self.assertFalse(booking_form.is_valid())
        self.assertEqual(booking_form.errors["time"], [message])

    def test_early_time_on_a_later_date_accepted(self):
        with mock.patch.object(guidance_service, "get_forecast", return_value=stub_result()):
            self.assertEqual(self.get_forecast(date="2026-11-11", time="00:00").status_code,
                             200)

    def test_error_messages_do_not_echo_input(self):
        payload = "<script>alert(1)</script>"
        for changes in (dict(service=payload), dict(date=payload), dict(time=payload)):
            with self.subTest(changes=changes):
                for response in (self.get_forecast(**changes), self.post_explain(**changes)):
                    self.assertEqual(response.status_code, 400)
                    self.assertNotIn("script", response.content.decode())


class DateBoundaryTests(GuidanceViewTestCase):
    def test_date_passing_midnight_during_request_is_invalid_not_500(self):
        # The form accepts Nov 10 at 23:59:59 CST; the facts are built after midnight.
        clock = [datetime.datetime(2026, 11, 11, 5, 59, 59, tzinfo=datetime.timezone.utc)]

        def past_midnight(*args):
            clock[0] = datetime.datetime(2026, 11, 11, 6, 0, 1, tzinfo=datetime.timezone.utc)
            raise ValueError("the date is before today in Central Time")

        with mock.patch("django.utils.timezone.now", side_effect=lambda: clock[0]):
            for name in ("get_forecast", "get_explanation"):
                with self.subTest(view=name), \
                        mock.patch.object(guidance_service, name, side_effect=past_midnight):
                    clock[0] = datetime.datetime(2026, 11, 11, 5, 59, 59,
                                                 tzinfo=datetime.timezone.utc)
                    send = self.get_forecast if name == "get_forecast" else self.post_explain
                    # No time: at 23:59:59 any earlier time would be rejected by the
                    # form itself, and this test is about the date passing midnight.
                    body = self.assertJson(send(date="2026-11-10", time=None), 400)
                    self.assertEqual(body, {"status": "invalid", "errors": {
                        "date": ["Choose today or a later date (Central Time)."]}})

    def test_other_value_errors_are_not_disguised(self):
        client = Client(raise_request_exception=True)
        client.force_login(self.customer)
        with mock.patch.object(guidance_service, "get_explanation",
                               side_effect=ValueError("programming error")), \
                self.assertRaises(ValueError):
            self.post_explain(client)

    def test_unexpected_error_is_a_500_without_details(self):
        client = Client(raise_request_exception=False)
        client.force_login(self.customer)
        with mock.patch.object(guidance_service, "get_explanation",
                               side_effect=RuntimeError(SECRET)), \
                self.assertLogs("django.request", "ERROR"):
            response = self.post_explain(client)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("10.0.0.5", response.content.decode())


class OutcomeTests(GuidanceViewTestCase):
    """Real service and facts; only the network is mocked."""

    def test_final_date_and_beyond_horizon(self):
        with mock.patch("guidance.weather.urlopen", side_effect=weather_ok):
            final = self.assertJson(self.get_forecast(date="2026-11-25", time=None), 200)
            beyond = self.assertJson(self.get_forecast(date="2026-11-26", time=None), 200)
        self.assertEqual(final["status"], "available")
        self.assertEqual(final["facts"]["date"], "2026-11-25")
        self.assertEqual(beyond["status"], "out_of_range")
        self.assertEqual(beyond["message"], "No forecast for this date yet. Forecasts are "
                                            "available through Wed, Nov 25.")

    def test_external_failures_return_safe_json(self):
        rejected = {"model": "llama3", "done": True, "message": {"role": "assistant",
                    "content": json.dumps({"summary": "We guarantee dry weather."})}}
        cases = (
            ("weather down", URLError(SECRET), None, "weather_unavailable", None),
            ("llm down", weather_ok, URLError(SECRET), "available", "ai_unavailable"),
            ("llm rejected", weather_ok,
             lambda *a, **k: FakeResponse(json.dumps(rejected).encode()), "available",
             "ai_rejected"),
        )
        for name, weather, llm, status, reason in cases:
            with self.subTest(case=name):
                cache.clear()
                with mock.patch("guidance.weather.urlopen", side_effect=weather), \
                        mock.patch("guidance.llm.urlopen", side_effect=llm):
                    response = self.post_explain()
                body = self.assertJson(response, 200)
                self.assertEqual(body["status"], status)
                self.assertEqual(body["fallback_reason"], reason)
                text = response.content.decode()
                for forbidden in ("10.0.0.5", "Traceback", "URLError", "guarantee",
                                  "certainty", "schema", "prompt", "LLMUnavailable"):
                    self.assertNotIn(forbidden, text)


class IsolationTests(GuidanceViewTestCase):
    def test_no_database_writes(self):
        before = Booking.objects.count()
        with mock.patch("guidance.weather.urlopen", side_effect=weather_ok), \
                mock.patch("guidance.llm.urlopen", side_effect=URLError("down")), \
                CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.get_forecast().status_code, 200)
            self.assertEqual(self.post_explain().status_code, 200)
            self.assertEqual(self.post_explain(service="abc").status_code, 400)
        writes = [q["sql"] for q in queries.captured_queries
                  if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(writes, [])
        self.assertEqual(Booking.objects.count(), before)

    def test_booking_create_unchanged_by_guidance_failure(self):
        with mock.patch("guidance.weather.urlopen", side_effect=URLError("down")), \
                mock.patch("guidance.llm.urlopen", side_effect=URLError("down")):
            self.post_explain()
            response = self.client.post(reverse("bookings:create"), self.data())
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        booking = Booking.objects.get(customer=self.customer)
        self.assertEqual((booking.service, booking.date, booking.time),
                         (self.service, datetime.date(2026, 11, 12), datetime.time(10, 0)))
