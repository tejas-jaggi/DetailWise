"""Rolling-window admission, HTTP security and real database contention."""

from concurrent.futures import ThreadPoolExecutor
import datetime
from threading import Barrier
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.cache import cache
from django.db import OperationalError, close_old_connections, connection
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from config.settings import guidance_rate_limit_settings
from guidance.models import ExplanationQuota
from guidance.rate_limit import RateLimitUnavailable, reserve_explanation
from guidance.tests.test_views import GuidanceViewTestCase, stub_result


class PolicyTests(SimpleTestCase):
    def test_defaults_and_overrides(self):
        self.assertEqual(guidance_rate_limit_settings({}), {"REQUESTS": 5, "WINDOW_SECONDS": 600})
        self.assertEqual(guidance_rate_limit_settings({
            "GUIDANCE_EXPLAIN_LIMIT": "2", "GUIDANCE_EXPLAIN_WINDOW_SECONDS": "30",
        }), {"REQUESTS": 2, "WINDOW_SECONDS": 30})

    def test_invalid_configuration_fails(self):
        for key in ["GUIDANCE_EXPLAIN_LIMIT", "GUIDANCE_EXPLAIN_WINDOW_SECONDS"]:
            for value in ["0", "-1", "1.5", "no", " "]:
                with self.subTest(key=key, value=value), self.assertRaises(ImproperlyConfigured):
                    guidance_rate_limit_settings({key: value})


@override_settings(GUIDANCE_RATE_LIMIT={"REQUESTS": 5, "WINDOW_SECONDS": 600})
class RateLimitViewTests(GuidanceViewTestCase):
    def setUp(self):
        super().setUp()
        clock = mock.patch("guidance.rate_limit._timestamp", return_value=1000)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        explanation = mock.patch(
            "guidance.service.get_explanation", return_value=stub_result(),
        )
        self.explanation = explanation.start()
        self.addCleanup(explanation.stop)

    def exhaust(self):
        for _ in range(5):
            self.assertEqual(self.post_explain().status_code, 200)

    def test_first_five_allowed_then_429_with_retry_after(self):
        self.exhaust()
        response = self.post_explain()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["status"], "rate_limited")
        self.assertIn("limit reached", response.json()["message"])
        self.assertEqual(response.json()["retry_after"], 600)
        self.assertEqual(response["Retry-After"], "600")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.explanation.call_count, 5)

    def test_sliding_expiration_not_fixed_buckets_and_denials_do_not_extend(self):
        for stamp in [1000, 1100, 1200, 1300, 1400]:
            self.clock.return_value = stamp
            self.assertEqual(self.post_explain().status_code, 200)
        self.clock.return_value = 1599.1
        self.assertEqual(self.post_explain()["Retry-After"], "1")
        self.assertEqual(self.post_explain()["Retry-After"], "1")
        self.clock.return_value = 1600  # exactly ten minutes after the first request
        self.assertEqual(self.post_explain().status_code, 200)
        self.assertEqual(self.post_explain()["Retry-After"], "100")
        self.clock.return_value = 2200
        self.assertEqual(self.post_explain().status_code, 200)
        self.assertEqual(ExplanationQuota.objects.get(user=self.customer).timestamps, [2200])

    def test_users_are_independent_even_on_same_ip_and_posted_user_id_is_ignored(self):
        self.exhaust()
        other = get_user_model().objects.create_user("riley")
        self.assertEqual(self.post_explain(user_id=other.pk).status_code, 429)
        self.client.force_login(other)
        self.exhaust()
        self.assertEqual(self.post_explain().status_code, 429)
        self.assertEqual(ExplanationQuota.objects.count(), 2)

    def test_new_session_and_different_ip_do_not_reset_quota(self):
        self.exhaust()
        client = Client()
        client.force_login(self.customer)
        response = client.post(reverse("guidance:explain"), self.data(), REMOTE_ADDR="203.0.113.1")
        self.assertEqual(response.status_code, 429)

    def test_clearing_response_cache_does_not_reset_quota(self):
        self.exhaust()
        cache.clear()
        self.assertEqual(self.post_explain().status_code, 429)

    @override_settings(GUIDANCE_RATE_LIMIT={"REQUESTS": 2, "WINDOW_SECONDS": 30})
    def test_configurable_policy(self):
        self.assertEqual(self.post_explain().status_code, 200)
        self.assertEqual(self.post_explain().status_code, 200)
        self.assertEqual(self.post_explain()["Retry-After"], "30")

    def test_lowered_limit_waits_until_enough_reservations_expire(self):
        for stamp in [1000, 1100, 1200, 1300, 1400]:
            self.clock.return_value = stamp
            self.post_explain()
        with override_settings(GUIDANCE_RATE_LIMIT={"REQUESTS": 2, "WINDOW_SECONDS": 600}):
            self.assertEqual(self.post_explain()["Retry-After"], "500")
            self.clock.return_value = 1900
            self.assertEqual(self.post_explain().status_code, 200)

    def test_invalid_requests_do_not_consume_quota_even_when_exhausted(self):
        for _ in range(6):
            self.assertEqual(self.post_explain(service="invalid").status_code, 400)
        self.assertFalse(ExplanationQuota.objects.exists())
        self.exhaust()
        self.assertEqual(self.post_explain(date="bad").status_code, 400)
        self.assertEqual(self.post_explain().status_code, 429)

    def test_malformed_body_does_not_consume_quota(self):
        response = self.client.post(reverse("guidance:explain"), "{broken", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ExplanationQuota.objects.exists())

    def test_service_exception_does_not_refund_reservation(self):
        self.explanation.side_effect = RuntimeError("test error")
        with self.assertRaises(RuntimeError):
            self.post_explain()
        self.assertEqual(len(ExplanationQuota.objects.get(user=self.customer).timestamps), 1)

    def test_anonymous_and_staff_do_not_create_quota(self):
        self.client.logout()
        self.assertEqual(self.post_explain().status_code, 401)
        staff = get_user_model().objects.create_user("staff", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.post_explain().status_code, 403)
        self.assertFalse(ExplanationQuota.objects.exists())
        self.explanation.assert_not_called()

    def test_csrf_and_method_checks_precede_quota(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.customer)
        self.assertEqual(self.post_explain(client).status_code, 403)
        self.assertEqual(self.client.get(reverse("guidance:explain")).status_code, 405)
        self.assertFalse(ExplanationQuota.objects.exists())
        client.get(reverse("bookings:create"))
        token = client.cookies["csrftoken"].value
        for _ in range(5):
            self.assertEqual(client.post(reverse("guidance:explain"), self.data(),
                                        HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(client.post(reverse("guidance:explain"), self.data(),
                                    HTTP_X_CSRFTOKEN=token).status_code, 429)

    def test_forecasts_and_booking_save_remain_available_after_limit(self):
        self.exhaust()
        with mock.patch("guidance.service.get_forecast", return_value=stub_result()) as forecast:
            for _ in range(8):
                self.assertEqual(self.get_forecast().status_code, 200)
            self.assertEqual(forecast.call_count, 8)
        response = self.client.post(reverse("bookings:create"), self.data())
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        self.assertEqual(len(ExplanationQuota.objects.get(user=self.customer).timestamps), 5)

    def test_fallback_and_cached_results_still_consume_quota(self):
        # The gate runs before the service, regardless of the cached/fallback result.
        self.explanation.return_value = stub_result("weather_unavailable")
        self.exhaust()
        self.assertEqual(self.post_explain().status_code, 429)

    def test_storage_failure_returns_safe_503_without_model_call(self):
        with mock.patch("guidance.views.reserve_explanation", side_effect=RateLimitUnavailable):
            response = self.post_explain()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "unavailable")
        self.assertIn("save your booking", response.json()["message"])
        self.explanation.assert_not_called()


class StorageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("quota-user")

    def test_database_clock_is_used_not_application_clock(self):
        wrong_time = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=wrong_time):
            reserve_explanation(self.user.pk)
        row = ExplanationQuota.objects.get(user=self.user)
        self.assertEqual(len(row.timestamps), 1)
        self.assertGreater(row.timestamps[0], wrong_time.timestamp() + 86400)

    def test_storage_errors_fail_closed_and_lock_retries_are_bounded(self):
        with mock.patch("guidance.rate_limit._reserve", side_effect=OperationalError("database is locked")) as reserve, \
                mock.patch("guidance.rate_limit.time.sleep") as sleep:
            with self.assertRaises(RateLimitUnavailable):
                reserve_explanation(self.user.pk)
        expected = 6 if connection.vendor == "sqlite" else 1
        self.assertEqual(reserve.call_count, expected)
        self.assertEqual(sleep.call_count, expected - 1)

    def test_other_database_errors_are_not_retried(self):
        with mock.patch("guidance.rate_limit._reserve", side_effect=OperationalError("private connection details")), \
                mock.patch("guidance.rate_limit.time.sleep") as sleep:
            with self.assertRaises(RateLimitUnavailable):
                reserve_explanation(self.user.pk)
        sleep.assert_not_called()

    def test_account_deletion_removes_history(self):
        reserve_explanation(self.user.pk)
        self.user.delete()
        self.assertFalse(ExplanationQuota.objects.exists())


@override_settings(GUIDANCE_RATE_LIMIT={"REQUESTS": 5, "WINDOW_SECONDS": 600})
class ConcurrentAdmissionTests(TransactionTestCase):
    serialized_rollback = True

    def run_concurrent(self, existing):
        user = get_user_model().objects.create_user("concurrent-user")
        if existing:
            ExplanationQuota.objects.create(user=user)
        barrier = Barrier(12)

        def reserve(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reserve_explanation(user.pk)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(reserve, range(12)))
        self.assertEqual(results.count(0), 5)
        self.assertEqual(sum(value > 0 for value in results), 7)
        self.assertEqual(ExplanationQuota.objects.count(), 1)
        self.assertEqual(len(ExplanationQuota.objects.get(user=user).timestamps), 5)

    def test_simultaneous_first_requests_do_not_exceed_limit(self):
        self.run_concurrent(existing=False)

    def test_simultaneous_requests_to_existing_row_do_not_exceed_limit(self):
        self.run_concurrent(existing=True)

    def test_service_runs_after_quota_transaction_commits(self):
        from bookings.models import Service
        from bookings.timeutils import central_now
        from guidance.views import explain

        user = get_user_model().objects.create_user("outside-transaction")
        service = Service.objects.get(slug="exterior-wash")
        request = RequestFactory().post(reverse("guidance:explain"), {
            "service": service.pk,
            "date": (central_now().date() + datetime.timedelta(days=1)).isoformat(),
        })
        request.user = user

        def result(*args):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(len(ExplanationQuota.objects.get(user=user).timestamps), 1)
            return stub_result()

        self.assertIn("default", explain._non_atomic_requests)
        with mock.patch("guidance.service.get_explanation", side_effect=result):
            self.assertEqual(explain(request).status_code, 200)
