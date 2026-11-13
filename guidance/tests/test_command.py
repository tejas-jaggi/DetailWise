"""Tests for ``manage.py guidance_check`` (plan Task 9).

Network and model are mocked: the weather, the Ollama model list and the Ollama
chat each have their ``urlopen`` patched. "Today" is frozen at 2026-11-10 (Central).
"""

import datetime
import io
import json
from unittest import mock
from urllib.error import URLError

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from bookings.models import Service
from guidance import llm
from guidance.management.commands import guidance_check
from guidance.tests.fixtures import forecast_payload

TODAY = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=datetime.timezone.utc)  # 12:00 CST
SECRET = "http://10.0.0.5:11434 internal-host-detail"
ACCEPTED_SUMMARY = "The highest hourly rain probability on this date is 20%."
REJECTED_SUMMARY = "We guarantee your car will stay dry with a ceramic coating."


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def json_response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def tags(*names):
    return json_response({"models": [{"name": name} for name in names]})


def chat(summary=ACCEPTED_SUMMARY, content=None):
    output = {
        "rain_level": "possible", "wind_level": "breezy", "temperature_level": "mild",
        "confidence": "higher", "outlook": "favorable", "summary": summary,
        "service_explanation": "Rain can make an exterior wash dirty again sooner.",
        "uncertainty_note": "",
    }
    content = json.dumps(output) if content is None else content
    return json_response({"model": "llama3", "done": True,
                          "message": {"role": "assistant", "content": content}})


class GuidanceCheckTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patches = (
            mock.patch("django.utils.timezone.now", return_value=TODAY),
            mock.patch("guidance.weather.urlopen",
                       side_effect=lambda *a, **k: json_response(forecast_payload())),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_check(self, *args, tag_reply=None, chat_replies=None, chat_error=None,
                  tag_error=None):
        """Run the command; return (stdout, CommandError or None, tags mock, chat mock)."""
        tag_patch = mock.patch(
            "guidance.management.commands.guidance_check.urlopen",
            side_effect=tag_error if tag_error else [tag_reply or tags("llama3:latest")],
        )
        chat_patch = mock.patch(
            "guidance.llm.urlopen",
            side_effect=chat_error if chat_error else list(chat_replies or [chat()]),
        )
        out, err = io.StringIO(), io.StringIO()
        args = args or ("--service", "exterior-wash", "--date", "2026-11-12",
                        "--time", "10:00")
        error = None
        with tag_patch as fake_tags, chat_patch as fake_chat:
            try:
                call_command("guidance_check", *args, stdout=out, stderr=err)
            except CommandError as exc:
                error = exc
        return out.getvalue() + err.getvalue(), error, fake_tags, fake_chat


class OutcomeTests(GuidanceCheckTestCase):
    def test_command_reports_timings_and_outcome(self):
        output, error, _, fake_chat = self.run_check()
        self.assertIsNone(error)  # exit status 0
        fake_chat.assert_called_once()
        for expected in (
            "Forecast: fetched in", "cache miss",
            "Date: Thu, Nov 12 at 10:00 AM", "Lead days: 2", "Confidence: higher",
            "Rain: possible", "Wind: breezy", "Temperature: mild", "Outlook: favorable",
            "Ollama: reachable", "Model llama3: installed",
            "Run 1: accepted", "Summary: 1 of 1 runs accepted",
            "Customer sections (AI explanation)", "Conditions:", "Recommendation:",
            ACCEPTED_SUMMARY,
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, output)
        self.assertRegex(output, r"Run 1: accepted in \d+ ms")

    def test_rejected_run_reports_reasons_and_exit_status_2(self):
        output, error, _, _ = self.run_check(chat_replies=[chat(REJECTED_SUMMARY)])
        self.assertEqual(error.returncode, 2)
        self.assertRegex(output, r"Run 1: rejected in \d+ ms \(reasons: [^)]*certainty")
        self.assertIn("Customer sections (Standard guidance)", output)
        self.assertNotIn(REJECTED_SUMMARY, output)
        self.assertNotIn("ceramic", output)

    def test_runs_option_and_mixed_results(self):
        output, error, _, fake_chat = self.run_check(
            "--service", "exterior-wash", "--date", "2026-11-12", "--time", "10:00",
            "--runs", "3",
            chat_replies=[chat(), chat(REJECTED_SUMMARY), chat(content="not json")],
        )
        self.assertEqual(fake_chat.call_count, 3)
        self.assertIn("Run 1: accepted", output)
        self.assertIn("Run 2: rejected", output)
        self.assertRegex(output, r"Run 3: unavailable \(malformed\) after \d+ ms")
        self.assertIn("Summary: 1 of 3 runs accepted", output)
        self.assertEqual(error.returncode, 2)

    def test_each_run_calls_the_model_even_when_an_answer_is_cached(self):
        _, _, _, fake_chat = self.run_check(
            "--service", "exterior-wash", "--date", "2026-11-12", "--runs", "2",
            chat_replies=[chat(), chat()],
        )
        self.assertEqual(fake_chat.call_count, 2)


class OllamaAvailabilityTests(GuidanceCheckTestCase):
    def test_ollama_unreachable_skips_runs_and_shows_fallback(self):
        output, error, _, fake_chat = self.run_check(
            tag_error=URLError(ConnectionRefusedError(10061, SECRET)))
        fake_chat.assert_not_called()
        self.assertEqual(error.returncode, 2)
        self.assertIn("Ollama: not reachable (unreachable)", output)
        self.assertIn("Customer sections (Standard guidance)", output)
        self.assertNotIn("10.0.0.5", output)

    def test_ollama_timeout_reported_as_timeout(self):
        output, error, _, _ = self.run_check(tag_error=TimeoutError(SECRET))
        self.assertIn("Ollama: not reachable (timeout)", output)
        self.assertEqual(error.returncode, 2)

    def test_model_not_installed_never_downloads(self):
        output, error, fake_tags, fake_chat = self.run_check(tag_reply=tags("mistral:latest"))
        fake_chat.assert_not_called()
        self.assertEqual(error.returncode, 2)
        self.assertIn("Model llama3: not installed", output)
        self.assertIn("ollama pull llama3", output)  # advice only
        self.assertIn("not run by this command", output)
        request = fake_tags.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.endswith("/api/tags"))

    def test_unreadable_model_list_reported_as_malformed(self):
        output, error, _, fake_chat = self.run_check(
            tag_reply=FakeResponse(b"<html>not json</html>"))
        fake_chat.assert_not_called()
        self.assertIn("Ollama: not reachable (malformed)", output)
        self.assertEqual(error.returncode, 2)

    def test_model_name_matching(self):
        installed = guidance_check.model_installed
        self.assertTrue(installed("llama3", ["llama3:latest"]))
        self.assertTrue(installed("llama3:latest", ["llama3:latest"]))
        self.assertTrue(installed("llama3:8b", ["llama3:8b"]))
        self.assertFalse(installed("llama3:8b", ["llama3:latest"]))
        self.assertFalse(installed("llama3", ["llama3.1:latest", "llama3-gradient:latest"]))
        self.assertFalse(installed("llama3", []))


class InputAndForecastTests(GuidanceCheckTestCase):
    def assertInputError(self, *args):
        output, error, _, fake_chat = self.run_check(*args)
        self.assertIsNotNone(error)
        self.assertEqual(error.returncode, 1)
        fake_chat.assert_not_called()
        return str(error)

    def test_invalid_inputs(self):
        Service.objects.filter(slug="full-detail").update(is_active=False)
        cases = (
            (("--service", "nope", "--date", "2026-11-12"), "No active service"),
            (("--service", "full-detail", "--date", "2026-11-12"), "No active service"),
            (("--service", "exterior-wash", "--date", "2026-02-30"), "Enter a valid date."),
            (("--service", "exterior-wash", "--date", "2026-11-09"),
             "Choose today or a later date"),
            (("--service", "exterior-wash", "--date", "2026-11-10", "--time", "11:00"),
             "That time has already passed today"),
            (("--service", "exterior-wash", "--date", "2026-11-12", "--time", "25:00"),
             "Enter a valid time."),
            (("--service", "exterior-wash", "--date", "2026-11-12", "--runs", "0"),
             "--runs must be between 1 and 10"),
            (("--service", "exterior-wash", "--date", "2026-11-12", "--runs", "11"),
             "--runs must be between 1 and 10"),
        )
        for args, message in cases:
            with self.subTest(args=args):
                self.assertIn(message, self.assertInputError(*args))

    def test_weather_unavailable_exit_status_1(self):
        with mock.patch("guidance.weather.urlopen", side_effect=URLError(SECRET)):
            output, error, fake_tags, fake_chat = self.run_check()
        self.assertEqual(error.returncode, 1)
        self.assertIn("Forecast: unavailable", output)
        fake_chat.assert_not_called()
        self.assertNotIn("10.0.0.5", output + str(error))

    def test_out_of_range_exit_status_1(self):
        output, error, _, fake_chat = self.run_check(
            "--service", "exterior-wash", "--date", "2026-11-26")
        self.assertEqual(error.returncode, 1)
        self.assertIn("Forecasts are available through Wed, Nov 25", output + str(error))
        fake_chat.assert_not_called()


class PrivacyTests(GuidanceCheckTestCase):
    def test_never_prints_prompt_raw_output_url_or_exception_text(self):
        for kwargs in (dict(chat_replies=[chat(REJECTED_SUMMARY)]),
                       dict(chat_error=URLError(SECRET)),
                       dict(chat_replies=[chat(content="Traceback (most recent call last)")])):
            with self.subTest(case=repr(kwargs)[:50]):
                output, _, _, _ = self.run_check(**kwargs)
                for forbidden in (llm.SYSTEM_PROMPT[:40], "rain_probability_note",
                                  REJECTED_SUMMARY, "Traceback", "10.0.0.5", "11434",
                                  "http://", "URLError"):
                    self.assertNotIn(forbidden, output)

    def test_no_database_writes(self):
        with CaptureQueriesContext(connection) as queries:
            self.run_check()
        writes = [q["sql"] for q in queries.captured_queries
                  if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(writes, [])
