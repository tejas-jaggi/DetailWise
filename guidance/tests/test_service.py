"""Tests for the guidance service: forecast, explanation, fallback and cache (plan Task 6, D6).

Only the network is replaced: ``guidance.weather.urlopen`` returns the fixture
forecast and ``guidance.llm.urlopen`` returns a scripted Ollama reply or raises.
Every other layer (facts, client, validator, fallback) is the real code.
"Today" is frozen at 2026-11-10 (Central); the default request is an exterior
service on Thu, Nov 12 at 10:00, where the fixture gives peak hourly rain 20%,
wind 10 mph and a high of 52°F (rain "possible", outlook "favorable").
"""

import datetime
import io
import json
import socket
from datetime import date, time
from unittest import mock
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from bookings.models import Service
from guidance import classify, llm, service
from guidance.fallback import fallback_sections
from guidance.tests.fixtures import forecast_payload

TODAY = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.timezone.utc)
NOV_12 = date(2026, 11, 12)
NOV_25 = date(2026, 11, 25)  # the fixture's last forecast date
TEN = time(10, 0)

EXTERIOR = Service(name="Exterior Wash", slug="exterior-wash", weather_sensitivity="exterior")
OTHER_EXTERIOR = Service(name="Wheel Detail", slug="wheel-detail",
                         weather_sensitivity="exterior")

ACCEPTED_SUMMARY = "The highest hourly rain probability on this date is 20%."
ACCEPTED_SERVICE = "Rain can make an exterior wash dirty again sooner."
REJECTED_SUMMARY = "We guarantee your car will stay dry with a ceramic coating."


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def model_output(**changes):
    output = {
        "rain_level": "possible",
        "wind_level": "breezy",
        "temperature_level": "mild",
        "confidence": "higher",
        "outlook": "favorable",
        "summary": ACCEPTED_SUMMARY,
        "service_explanation": ACCEPTED_SERVICE,
        "uncertainty_note": "",
    }
    output.update(changes)
    return output


def ollama_reply(output=None, content=None):
    if content is None:
        content = json.dumps(output if output is not None else model_output())
    body = {"model": "llama3", "message": {"role": "assistant", "content": content},
            "done": True}
    return FakeResponse(json.dumps(body).encode("utf-8"))


class ServiceTestCase(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patches = (
            mock.patch("django.utils.timezone.now", return_value=TODAY),
            mock.patch("guidance.weather.urlopen", side_effect=self.weather_reply),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.forecast = forecast_payload()

    def weather_reply(self, *args, **kwargs):
        return FakeResponse(json.dumps(self.forecast).encode("utf-8"))

    def explain(self, *, replies=None, error=None, svc=EXTERIOR, day=NOV_12, at=TEN):
        """Call get_explanation with the model scripted; return (result, llm urlopen mock)."""
        if error is not None:
            patch = mock.patch("guidance.llm.urlopen", side_effect=error)
        else:
            patch = mock.patch("guidance.llm.urlopen",
                               side_effect=list(replies or [ollama_reply()]))
        with patch as fake_llm:
            result = service.get_explanation(svc, day, at)
        return result, fake_llm

    def assertFallback(self, result, reason):
        self.assertEqual(result.status, "available")
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.fallback_reason, reason)
        self.assertEqual(result.sections, fallback_sections(result.facts))
        self.assertIsNone(result.message)


class ForecastTests(ServiceTestCase):
    def test_forecast_available_without_llm_call(self):
        with mock.patch("guidance.llm.urlopen") as fake_llm:
            result = service.get_forecast(EXTERIOR, NOV_12, TEN)
        fake_llm.assert_not_called()
        self.assertEqual(result.status, "available")
        self.assertEqual(result.facts.date, NOV_12)
        self.assertEqual(result.facts.time, TEN)
        self.assertEqual(result.facts.service_name, "Exterior Wash")
        self.assertEqual(result.sections, [])
        self.assertIsNone(result.source)
        self.assertIsNone(result.fallback_reason)
        self.assertIsNone(result.message)

    def test_forecast_out_of_range_message_uses_last_date(self):
        result = service.get_forecast(EXTERIOR, NOV_25 + datetime.timedelta(days=1))
        self.assertEqual(result.status, "out_of_range")
        self.assertEqual(
            result.message,
            "No forecast for this date yet. Forecasts are available through Wed, Nov 25.",
        )
        self.assertIsNone(result.facts)
        self.assertEqual(result.sections, [])

    def test_forecast_final_date_available(self):
        self.assertEqual(service.get_forecast(EXTERIOR, NOV_25).status, "available")

    def test_forecast_weather_unavailable(self):
        with mock.patch("guidance.weather.urlopen", side_effect=URLError("down")):
            result = service.get_forecast(EXTERIOR, NOV_12)
        self.assertEqual(result.status, "weather_unavailable")
        self.assertEqual(result.message,
                         "Forecast unavailable right now. You can still save your booking.")
        self.assertIsNone(result.facts)
        self.assertEqual(result.sections, [])

    def test_forecast_all_core_values_missing_is_weather_unavailable(self):
        day = NOV_12.isoformat()
        self.forecast = forecast_payload(daily={
            key: {day: None} for key in ("temperature_2m_max", "temperature_2m_min",
                                         "precipitation_probability_max",
                                         "wind_speed_10m_max")
        })
        self.assertEqual(service.get_forecast(EXTERIOR, NOV_12).status, "weather_unavailable")


class ExplanationOutcomeTests(ServiceTestCase):
    def test_explanation_ai_accepted(self):
        result, fake_llm = self.explain()
        fake_llm.assert_called_once()
        self.assertEqual(result.status, "available")
        self.assertEqual(result.source, "ai")
        self.assertIsNone(result.fallback_reason)
        self.assertIsNone(result.message)
        self.assertEqual([s["label"] for s in result.sections],
                         ["Conditions", "For your service", "Forecast confidence",
                          "Recommendation"])
        self.assertEqual(result.sections[0]["text"], ACCEPTED_SUMMARY)
        self.assertEqual(result.sections[1]["text"], ACCEPTED_SERVICE)

    def test_explanation_rejected_uses_fallback_and_hides_text(self):
        result, _ = self.explain(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))])
        self.assertFallback(result, "ai_rejected")
        payload = json.dumps(result.to_json())
        for fragment in (REJECTED_SUMMARY, "guarantee", "ceramic"):
            self.assertNotIn(fragment, payload)

    def test_explanation_enum_mismatch_uses_fallback(self):
        result, _ = self.explain(replies=[ollama_reply(model_output(rain_level="low"))])
        self.assertFallback(result, "ai_rejected")

    def test_explanation_llm_unreachable_uses_fallback(self):
        result, _ = self.explain(error=URLError(ConnectionRefusedError(10061, "refused")))
        self.assertFallback(result, "ai_unavailable")

    def test_explanation_llm_timeout_uses_fallback(self):
        for error in (socket.timeout("timed out"), URLError(TimeoutError("timed out"))):
            with self.subTest(error=repr(error)):
                result, _ = self.explain(error=error)
                self.assertFallback(result, "ai_unavailable")

    def test_explanation_llm_http_error_uses_fallback(self):
        error = HTTPError("http://127.0.0.1:11434/api/chat", 404, "Not Found", {}, None)
        result, _ = self.explain(error=error)
        self.assertFallback(result, "ai_unavailable")

    def test_explanation_malformed_output_uses_fallback(self):
        for content in ("not json", "", "[]"):
            with self.subTest(content=content):
                result, _ = self.explain(replies=[ollama_reply(content=content)])
                self.assertFallback(result, "ai_unavailable")

    def test_explanation_weather_unavailable_skips_llm(self):
        with mock.patch("guidance.weather.urlopen", side_effect=URLError("down")):
            result, fake_llm = self.explain()
        fake_llm.assert_not_called()
        self.assertEqual(result.status, "weather_unavailable")
        self.assertIsNone(result.source)
        self.assertEqual(result.sections, [])

    def test_explanation_out_of_range_skips_llm(self):
        result, fake_llm = self.explain(day=NOV_25 + datetime.timedelta(days=1))
        fake_llm.assert_not_called()
        self.assertEqual(result.status, "out_of_range")

    def test_python_recommendation_in_every_outcome(self):
        outcomes = {
            "ai": dict(),
            "rejected": dict(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))]),
            "unavailable": dict(error=URLError("down")),
        }
        for name, kwargs in outcomes.items():
            with self.subTest(outcome=name):
                cache.clear()
                result, _ = self.explain(**kwargs)
                facts = result.facts
                expected = classify.recommendation(facts.outlook, facts.concerns,
                                                   facts.missing, facts.confidence)
                self.assertEqual(result.sections[-1],
                                 {"label": "Recommendation", "text": expected})

    def test_model_cannot_write_the_recommendation(self):
        # An extra "recommendation" field is a schema error, never shown text.
        result, _ = self.explain(replies=[ollama_reply(model_output(
            recommendation="Cancel your booking."))])
        self.assertFallback(result, "ai_rejected")
        self.assertNotIn("Cancel", json.dumps(result.to_json()))


class CacheTests(ServiceTestCase):
    def test_accepted_explanation_cached(self):
        first, _ = self.explain()
        with mock.patch("guidance.llm.urlopen") as fake_llm:
            second = service.get_explanation(EXTERIOR, NOV_12, TEN)
        fake_llm.assert_not_called()
        self.assertEqual(second.source, "ai")
        self.assertEqual(second.sections, first.sections)

    def test_cache_lifetime_is_30_minutes(self):
        with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
            self.explain()
        ai_sets = [c for c in cache_set.call_args_list if c.args[0].startswith("guidance:ai:")]
        self.assertEqual(len(ai_sets), 1)
        self.assertEqual(ai_sets[0].args[2], 30 * 60)

    def test_cached_explanation_expires_after_30_minutes(self):
        start = 1_800_000_000.0
        with mock.patch("time.time", return_value=start):
            self.explain()
        with mock.patch("time.time", return_value=start + 30 * 60 - 1):
            _, fake_llm = self.explain()
        fake_llm.assert_not_called()
        # The Task 1 forecast cache also expires at 30 min, so it is refetched too.
        with mock.patch("time.time", return_value=start + 30 * 60 + 1):
            result, fake_llm = self.explain()
        fake_llm.assert_called_once()
        self.assertEqual(result.source, "ai")

    def test_rejected_or_failed_not_cached(self):
        for name, kwargs in (
            ("rejected", dict(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))])),
            ("unavailable", dict(error=URLError("down"))),
            ("malformed", dict(replies=[ollama_reply(content="not json")])),
        ):
            with self.subTest(outcome=name):
                cache.clear()
                self.explain(**kwargs)
                self.assertIsNone(cache.get(service.cache_key(self.facts())))
                result, fake_llm = self.explain()
                fake_llm.assert_called_once()
                self.assertEqual(result.source, "ai")

    def test_cache_key_changes_with_facts(self):
        base = self.facts()
        self.forecast = forecast_payload(daily={"precipitation_probability_max":
                                                {NOV_12.isoformat(): 21}})
        cache.clear()  # otherwise the Task 1 forecast cache serves the first forecast
        changed = self.facts()
        self.assertEqual(changed.peak_rain_chance_pct, 21)
        self.assertNotEqual(service.cache_key(changed), service.cache_key(base))
        # Same rounded value, different raw value: still a different key, because
        # the validator's allowed numbers include the raw values.
        self.forecast = forecast_payload(daily={"temperature_2m_max":
                                                {NOV_12.isoformat(): 52.4}})
        cache.clear()
        raw_only = self.facts()
        self.assertEqual(raw_only.temp_high_f, base.temp_high_f)
        self.assertNotEqual(service.cache_key(raw_only), service.cache_key(base))

    def test_different_services_and_times_do_not_share_cache(self):
        self.explain()
        for name, kwargs in (("service", dict(svc=OTHER_EXTERIOR)),
                             ("time", dict(at=time(14, 0))),
                             ("no time", dict(at=None)),
                             ("date", dict(day=date(2026, 11, 13)))):
            with self.subTest(differs_by=name):
                output = model_output() if name != "date" else model_output(
                    rain_level="possible", confidence="moderate",
                    summary="The highest hourly rain probability on this date is 25%.",
                    uncertainty_note="The forecast may change before your appointment.")
                result, fake_llm = self.explain(replies=[ollama_reply(output)], **kwargs)
                fake_llm.assert_called_once()
                self.assertEqual(result.source, "ai")

    def test_prompt_version_change_invalidates_cache(self):
        self.explain()
        with mock.patch.object(llm, "PROMPT_VERSION", "v2"):
            _, fake_llm = self.explain()
        fake_llm.assert_called_once()

    def test_model_change_invalidates_cache(self):
        self.explain()
        with override_settings(GUIDANCE={**settings.GUIDANCE, "OLLAMA_MODEL": "llama3:8b"}):
            _, fake_llm = self.explain()
        fake_llm.assert_called_once()

    def test_cache_key_format_and_privacy(self):
        key = service.cache_key(self.facts())
        prefix, digest = key.rsplit(":", 1)
        self.assertEqual(prefix, "guidance:ai:v1")
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("Exterior", key)

    def test_cached_output_is_revalidated_before_use(self):
        # A cached entry that fails the current validator is never shown.
        cache.set(service.cache_key(self.facts()), model_output(summary=REJECTED_SUMMARY), 60)
        result, fake_llm = self.explain()
        fake_llm.assert_called_once()
        self.assertEqual(result.source, "ai")
        self.assertEqual(result.sections[0]["text"], ACCEPTED_SUMMARY)

    def test_cached_explanation_keeps_python_recommendation(self):
        self.explain()
        with mock.patch("guidance.llm.urlopen") as fake_llm:
            result = service.get_explanation(EXTERIOR, NOV_12, TEN)
        fake_llm.assert_not_called()
        facts = result.facts
        self.assertEqual(result.sections[-1]["text"], classify.recommendation(
            facts.outlook, facts.concerns, facts.missing, facts.confidence))

    def facts(self, svc=EXTERIOR, day=NOV_12, at=TEN):
        return service.get_forecast(svc, day, at).facts


class JsonAndLoggingTests(ServiceTestCase):
    def test_to_json_shapes(self):
        accepted, _ = self.explain()
        data = accepted.to_json()
        self.assertEqual(set(data), {"status", "facts", "sections", "source",
                                     "fallback_reason", "message"})
        self.assertEqual(data["facts"], accepted.facts.as_public_dict())
        self.assertEqual((data["source"], data["fallback_reason"]), ("ai", None))
        json.dumps(data)  # JSON-ready
        for reason, kwargs in (
            ("ai_rejected", dict(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))])),
            ("ai_unavailable", dict(error=URLError("down"))),
        ):
            with self.subTest(reason=reason):
                cache.clear()
                fallback, _ = self.explain(**kwargs)
                data = fallback.to_json()
                self.assertEqual((data["source"], data["fallback_reason"]), ("fallback", reason))
                self.assertEqual(data["sections"], fallback_sections(fallback.facts))
        out_of_range = service.get_forecast(EXTERIOR, NOV_25 + datetime.timedelta(days=1))
        self.assertEqual(out_of_range.to_json(), {
            "status": "out_of_range", "facts": None, "sections": [], "source": None,
            "fallback_reason": None,
            "message": "No forecast for this date yet. Forecasts are available through "
                       "Wed, Nov 25.",
        })

    def test_to_json_has_no_internal_details(self):
        secret = "http://10.0.0.5:11434 internal-host-detail"
        cases = (
            dict(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))]),
            dict(error=URLError(secret)),
            dict(error=TimeoutError(secret)),
            dict(replies=[ollama_reply(content="Traceback (most recent call last)")]),
        )
        for kwargs in cases:
            with self.subTest(case=repr(kwargs)[:60]):
                cache.clear()
                result, _ = self.explain(**kwargs)
                payload = json.dumps(result.to_json())
                for forbidden in ("certainty", "advice", "LLMUnavailable", "URLError",
                                  "TimeoutError", "prompt", "Traceback", "10.0.0.5",
                                  "raw_values", "kind", "reasons"):
                    self.assertNotIn(forbidden, payload)

    def test_logs_outcome_kind_reasons_and_latency_only(self):
        cases = (
            ("ai", dict(), ["source=ai"]),
            ("rejected", dict(replies=[ollama_reply(model_output(summary=REJECTED_SUMMARY))]),
             ["source=fallback", "fallback_reason=ai_rejected", "certainty", "advice"]),
            ("unavailable", dict(error=URLError(ConnectionRefusedError(10061, "secret"))),
             ["source=fallback", "fallback_reason=ai_unavailable", "kind=unreachable"]),
            ("timeout", dict(error=socket.timeout("secret timed out")),
             ["fallback_reason=ai_unavailable", "kind=timeout"]),
        )
        for name, kwargs, expected in cases:
            with self.subTest(outcome=name):
                cache.clear()
                with self.assertLogs("guidance.service", "DEBUG") as logs:
                    self.explain(**kwargs)
                self.assertTrue(all(r.levelname == "INFO" for r in logs.records))
                text = "\n".join(logs.output)
                self.assertRegex(text, r"latency_ms=\d+")
                for fragment in expected:
                    self.assertIn(fragment, text)
                for forbidden in (REJECTED_SUMMARY, ACCEPTED_SUMMARY, "ceramic", "secret",
                                  "Exterior Wash", "2026-11-12", "10:00", "llama3",
                                  "You explain", "Traceback", settings.SECRET_KEY):
                    self.assertNotIn(forbidden, text)

    def test_cache_hit_logged_without_details(self):
        self.explain()
        with mock.patch("guidance.llm.urlopen"), \
                self.assertLogs("guidance.service", "INFO") as logs:
            service.get_explanation(EXTERIOR, NOV_12, TEN)
        text = "\n".join(logs.output)
        self.assertIn("cache_hit", text)
        self.assertNotIn(ACCEPTED_SUMMARY, text)
