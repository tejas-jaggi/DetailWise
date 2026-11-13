"""Tests for the Ollama client (plan Task 5, D4, D6).

No test uses the network or a model: ``guidance.llm.urlopen`` is patched in
every test that sends a request.
"""

import datetime
import io
import json
import socket
from datetime import date, time
from http.client import IncompleteRead, RemoteDisconnected
from unittest import mock
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from bookings.models import Service
from guidance import llm
from guidance.facts import RAIN_PROBABILITY_NOTE, build_facts
from guidance.schema import OUTPUT_SCHEMA
from guidance.tests.fixtures import forecast_payload

TODAY = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.timezone.utc)
NOV_12 = date(2026, 11, 12)

MODEL_OUTPUT = {
    "rain_level": "possible",
    "wind_level": "breezy",
    "temperature_level": "mild",
    "confidence": "higher",
    "outlook": "favorable",
    "summary": "The highest hourly rain probability on this date is 20%.",
    "service_explanation": "Rain can make an exterior wash dirty again sooner.",
    "uncertainty_note": "",
}


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def ollama_body(content=None, **envelope):
    """An Ollama /api/chat response body (stream false) as bytes."""
    if content is None:
        content = json.dumps(MODEL_OUTPUT)
    body = {
        "model": "llama3",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        **envelope,
    }
    return json.dumps(body).encode("utf-8")


def respond_with(body):
    return mock.patch("guidance.llm.urlopen", return_value=FakeResponse(body))


def make_facts(at=time(10, 0), hour_rain=20):
    """Facts for Thu, Nov 12. ``hour_rain=None`` removes the appointment-hour rain value."""
    payload = forecast_payload(
        hourly={"precipitation_probability": {"2026-11-12T11:00": hour_rain}}
    )
    service = Service(name="Exterior Wash", slug="exterior-wash",
                      weather_sensitivity="exterior")
    with mock.patch("django.utils.timezone.now", return_value=TODAY):
        return build_facts(payload, service, NOV_12, at)


def guidance_with(**changes):
    return override_settings(GUIDANCE={**settings.GUIDANCE, **changes})


class LLMTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.facts = make_facts()

    def send(self, facts=None, body=None):
        """Call request_explanation with a mocked reply; return (result, request, timeout)."""
        with respond_with(body or ollama_body()) as fake_urlopen:
            result = llm.request_explanation(facts or self.facts)
        fake_urlopen.assert_called_once()
        call = fake_urlopen.call_args
        return result, call.args[0], call.kwargs.get("timeout")

    def sent_body(self, facts=None):
        _, request, _ = self.send(facts)
        return json.loads(request.data)

    def assertKind(self, kind, *, body=None, error=None):
        patch = (mock.patch("guidance.llm.urlopen", side_effect=error) if error
                 else respond_with(body))
        with patch, self.assertRaises(llm.LLMUnavailable) as caught:
            llm.request_explanation(self.facts)
        self.assertEqual(caught.exception.kind, kind)
        return caught.exception


class RequestTests(LLMTestCase):
    def test_request_url_and_method(self):
        _, request, _ = self.send()
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_base_url_setting_used_and_trailing_slash_ignored(self):
        with guidance_with(OLLAMA_BASE_URL="http://127.0.0.1:11999/"):
            _, request, _ = self.send()
        self.assertEqual(request.full_url, "http://127.0.0.1:11999/api/chat")

    def test_request_body_and_timeout(self):
        _, request, timeout = self.send()
        body = json.loads(request.data)
        self.assertEqual(timeout, 45)
        self.assertEqual(body["model"], "llama3")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], OUTPUT_SCHEMA)
        self.assertEqual(body["options"], {"temperature": 0, "num_predict": 220})
        self.assertEqual(body["keep_alive"], "30m")
        self.assertEqual(body["messages"], llm.build_messages(self.facts))
        self.assertEqual(set(body), {"model", "messages", "stream", "format", "options",
                                     "keep_alive"})

    def test_model_setting_used(self):
        with guidance_with(OLLAMA_MODEL="llama3:8b"):
            body = self.sent_body()
        self.assertEqual(body["model"], "llama3:8b")

    def test_timeout_setting_overridable(self):
        with guidance_with(LLM_TIMEOUT=10):
            _, _, timeout = self.send()
        self.assertEqual(timeout, 10)

    def test_prompt_version(self):
        self.assertEqual(llm.PROMPT_VERSION, "v1")


class PromptTests(LLMTestCase):
    def test_messages_are_one_system_and_one_user_message(self):
        messages = llm.build_messages(self.facts)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertTrue(all(set(m) == {"role", "content"} for m in messages))

    def test_user_message_contains_only_fact_json(self):
        user = llm.build_messages(self.facts)[1]["content"]
        self.assertEqual(json.loads(user), self.facts.as_prompt_dict())

    def test_user_message_has_no_internal_values(self):
        # Raw (unrounded) values and the allowed-number lists are validator-only.
        user = json.loads(llm.build_messages(self.facts)[1]["content"])
        for key in ("raw_values", "allowed_numbers", "missing", "last_forecast_date"):
            with self.subTest(key=key):
                self.assertNotIn(key, user)

    def test_system_prompt_rules_present(self):
        system = llm.build_messages(self.facts)[0]["content"]
        for rule in (
            "only source of weather information",
            "Copy rain_level, wind_level, temperature_level, confidence and outlook exactly",
            "Never write a number that is not in the facts",
            "at most 2 short sentences",
            "plain customer language",
            "explain only the provided service_consideration",
            "no products, techniques or instructions",
            "Make no promises",
            "never suggest changing, moving or cancelling the booking",
            "When lead_days is 3 or more, uncertainty_note must say the forecast may change",
            "highest chance of rain for any single hour",
            "never the chance of rain all day",
            '"the highest hourly rain probability"',
            "appointment_hour_rain_probability_pct only for the appointment hour, and only "
            "when it is present",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, system)

    def test_system_prompt_is_the_same_for_all_facts(self):
        # Facts travel only in the user message, so the system prompt never varies.
        other = make_facts(at=None)
        self.assertEqual(llm.build_messages(self.facts)[0], llm.build_messages(other)[0])

    def test_prompt_facts_name_rain_values_unambiguously(self):
        with_hour = json.loads(llm.build_messages(self.facts)[1]["content"])
        self.assertEqual(with_hour["peak_hourly_rain_probability_pct"],
                         self.facts.peak_rain_chance_pct)
        self.assertEqual(with_hour["appointment_hour_rain_probability_pct"], 20)
        self.assertEqual(with_hour["rain_probability_note"], RAIN_PROBABILITY_NOTE)
        for facts in (make_facts(hour_rain=None), make_facts(at=None)):
            with self.subTest(time=facts.time):
                user = json.loads(llm.build_messages(facts)[1]["content"])
                self.assertIn("peak_hourly_rain_probability_pct", user)
                self.assertIn("rain_probability_note", user)
                self.assertNotIn("appointment_hour_rain_probability_pct", user)


class ResponseTests(LLMTestCase):
    def test_returns_parsed_model_object(self):
        result, _, _ = self.send()
        self.assertEqual(result, MODEL_OUTPUT)

    def test_returns_object_without_validating_it(self):
        # Validation belongs to guidance.validation; the client passes the object through.
        unchecked = {"rain_level": "sunny", "extra": 1, "summary": "<b>60 days</b>"}
        result, _, _ = self.send(body=ollama_body(json.dumps(unchecked)))
        self.assertEqual(result, unchecked)

    def test_content_with_surrounding_whitespace_is_parsed(self):
        result, _, _ = self.send(body=ollama_body("\n  " + json.dumps(MODEL_OUTPUT) + "\n"))
        self.assertEqual(result, MODEL_OUTPUT)


class FailureTests(LLMTestCase):
    def test_connection_refused_kind_unreachable(self):
        self.assertKind("unreachable", error=URLError(ConnectionRefusedError(10061, "refused")))

    def test_connection_reset_kind_unreachable(self):
        self.assertKind("unreachable", error=ConnectionResetError(10054, "reset"))

    def test_timeout_kind_timeout(self):
        for error in (TimeoutError("timed out"), socket.timeout("timed out"),
                      URLError(TimeoutError("timed out"))):
            with self.subTest(error=repr(error)):
                self.assertKind("timeout", error=error)

    def test_timeout_while_reading_kind_timeout(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = TimeoutError("timed out")
        with mock.patch("guidance.llm.urlopen", return_value=response), \
                self.assertRaises(llm.LLMUnavailable) as caught:
            llm.request_explanation(self.facts)
        self.assertEqual(caught.exception.kind, "timeout")

    def test_http_404_model_missing_kind_http(self):
        error = HTTPError("http://127.0.0.1:11434/api/chat", 404, "Not Found", {},
                          io.BytesIO(b'{"error":"model \\"llama3\\" not found"}'))
        self.assertKind("http", error=error)

    def test_http_500_kind_http(self):
        error = HTTPError("http://127.0.0.1:11434/api/chat", 500, "Server Error", {}, None)
        self.assertKind("http", error=error)

    def test_outer_json_malformed_kind_malformed(self):
        for body in (b"not json", b'{"message": ', b"\xff\xfe", b""):
            with self.subTest(body=body):
                self.assertKind("malformed", body=body)

    def test_missing_message_content_malformed(self):
        for envelope in ({"model": "llama3", "done": True},
                         {"message": {"role": "assistant"}},
                         {"error": "model is loading"}):
            with self.subTest(envelope=envelope):
                self.assertKind("malformed", body=json.dumps(envelope).encode())

    def test_unexpected_response_structure_malformed(self):
        for body in (b"[]", b'"text"', b"null",
                     json.dumps({"message": "text"}).encode(),
                     json.dumps({"message": {"content": 7}}).encode(),
                     json.dumps({"message": {"content": None}}).encode()):
            with self.subTest(body=body):
                self.assertKind("malformed", body=body)

    def test_inner_content_not_json_malformed(self):
        for content in ("Here is the explanation: rain is possible.",
                        '{"rain_level": "possible", "summary": "The high',  # cut off
                        "```json\n{}\n```"):
            with self.subTest(content=content):
                self.assertKind("malformed", body=ollama_body(content))

    def test_inner_content_not_an_object_malformed(self):
        for content in ("[]", '"text"', "null", "42", "true"):
            with self.subTest(content=content):
                self.assertKind("malformed", body=ollama_body(content))

    def test_empty_content_malformed(self):
        for content in ("", "   ", "\n"):
            with self.subTest(content=repr(content)):
                self.assertKind("malformed", body=ollama_body(content))

    def test_oversized_response_malformed(self):
        padding = " " * (llm.MAX_RESPONSE_BYTES + 1)
        self.assertKind("malformed", body=ollama_body() + padding.encode())

    def test_response_at_size_limit_accepted(self):
        body = ollama_body()
        body += b" " * (llm.MAX_RESPONSE_BYTES - len(body))
        result, _, _ = self.send(body=body)
        self.assertEqual(result, MODEL_OUTPUT)

    def test_max_response_bytes_is_64_kb(self):
        self.assertEqual(llm.MAX_RESPONSE_BYTES, 64 * 1024)

    def test_failure_hides_internal_details(self):
        secret = "http://10.0.0.5:11434 internal-host-detail"
        errors = (URLError(secret), HTTPError(secret, 500, secret, {}, None),
                  TimeoutError(secret), OSError(secret))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with mock.patch("guidance.llm.urlopen", side_effect=error), \
                        self.assertRaises(llm.LLMUnavailable) as caught:
                    llm.request_explanation(self.facts)
                exc = caught.exception
                self.assertNotIn(secret, str(exc))
                self.assertNotIn("10.0.0.5", repr(exc))
                self.assertIsNone(exc.__cause__)
                self.assertTrue(exc.__suppress_context__)
                self.assertIn(exc.kind, llm.LLMUnavailable.KINDS)

    def test_server_disconnect_kind_unreachable(self):
        self.assertKind("unreachable", error=RemoteDisconnected("closed without response"))

    def test_broken_http_response_kind_malformed(self):
        self.assertKind("malformed", error=IncompleteRead(b"{\"message\""))

    def test_base_url_without_scheme_kind_unreachable(self):
        # A misconfigured URL must give the fallback, not an unhandled error.
        # "localhost/api/chat" fails in Request(); "127.0.0.1:11434" parses as an
        # unknown scheme and fails in urlopen with URLError instead.
        with guidance_with(OLLAMA_BASE_URL="localhost"), \
                mock.patch("guidance.llm.urlopen") as fake_urlopen, \
                self.assertRaises(llm.LLMUnavailable) as caught:
            llm.request_explanation(self.facts)
        self.assertEqual(caught.exception.kind, "unreachable")
        fake_urlopen.assert_not_called()
        self.assertKind("unreachable", error=URLError("unknown url type: 127.0.0.1"))

    def test_deeply_nested_json_malformed(self):
        # 40 KB: under the size cap, but far deeper than Python's recursion limit.
        nested = "[" * 20_000 + "]" * 20_000
        body = ollama_body(nested)
        self.assertLess(len(body), llm.MAX_RESPONSE_BYTES)
        self.assertKind("malformed", body=body)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            llm.LLMUnavailable("network")
