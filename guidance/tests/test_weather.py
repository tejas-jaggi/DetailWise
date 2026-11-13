"""Tests for the guidance settings and the Open-Meteo client.

No test uses the network: ``guidance.weather.urlopen`` is patched in every test
that fetches.
"""

import io
import json
import logging
import socket
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import guidance_settings
from guidance import weather
from guidance.tests.fixtures import forecast_payload


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def respond_with(payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return mock.patch("guidance.weather.urlopen", return_value=FakeResponse(body))


class GuidanceSettingsTests(SimpleTestCase):
    def test_settings_have_safe_local_defaults(self):
        config = guidance_settings({})
        self.assertEqual(config["LATITUDE"], 40.11)
        self.assertEqual(config["LONGITUDE"], -88.21)
        self.assertEqual(config["TIMEZONE"], "America/Chicago")
        self.assertEqual(config["FORECAST_URL"], "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(config["FORECAST_DAYS"], 16)
        self.assertEqual(config["WEATHER_TIMEOUT"], 5)
        self.assertEqual(config["CACHE_SECONDS"], 1800)
        self.assertEqual(config["OLLAMA_BASE_URL"], "http://127.0.0.1:11434")
        self.assertEqual(config["OLLAMA_MODEL"], "llama3")
        self.assertEqual(config["LLM_TIMEOUT"], 45)

    def test_environment_overrides_ollama_settings(self):
        config = guidance_settings(
            {
                "OLLAMA_BASE_URL": "http://127.0.0.1:11999",
                "OLLAMA_MODEL": "llama3:8b",
                "GUIDANCE_LLM_TIMEOUT": "30",
            }
        )
        self.assertEqual(config["OLLAMA_BASE_URL"], "http://127.0.0.1:11999")
        self.assertEqual(config["OLLAMA_MODEL"], "llama3:8b")
        self.assertEqual(config["LLM_TIMEOUT"], 30)

    def test_invalid_llm_timeout_is_rejected(self):
        for bad in ("abc", "0", "-5", "4.5"):
            with self.subTest(value=bad), self.assertRaises(ImproperlyConfigured):
                guidance_settings({"GUIDANCE_LLM_TIMEOUT": bad})

    def test_blank_environment_values_use_defaults(self):
        config = guidance_settings(
            {"OLLAMA_BASE_URL": "  ", "OLLAMA_MODEL": "", "GUIDANCE_LLM_TIMEOUT": ""}
        )
        self.assertEqual(config["OLLAMA_BASE_URL"], "http://127.0.0.1:11434")
        self.assertEqual(config["OLLAMA_MODEL"], "llama3")
        self.assertEqual(config["LLM_TIMEOUT"], 45)

    def test_app_installed_and_settings_loaded(self):
        self.assertIn("guidance", settings.INSTALLED_APPS)
        self.assertEqual(settings.GUIDANCE["FORECAST_DAYS"], 16)
        self.assertEqual(settings.GUIDANCE["WEATHER_TIMEOUT"], 5)


class FetchForecastTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Expected failure warnings would otherwise reach stderr through logging's
        # last-resort handler. assertLogs still captures them where a test checks them.
        quiet = logging.NullHandler()
        weather_logger = logging.getLogger("guidance.weather")
        weather_logger.addHandler(quiet)
        self.addCleanup(weather_logger.removeHandler, quiet)

    def test_valid_payload_returned(self):
        payload = forecast_payload()
        with respond_with(payload):
            result = weather.fetch_forecast()
        self.assertEqual(result, payload)
        self.assertEqual(result["daily"]["time"][0], "2026-11-10")
        self.assertEqual(len(result["hourly"]["time"]), 16 * 24)

    def test_request_parameters_and_timeout(self):
        with respond_with(forecast_payload()) as fake_urlopen:
            weather.fetch_forecast()
        fake_urlopen.assert_called_once()
        url = fake_urlopen.call_args.args[0]
        self.assertTrue(url.startswith("https://api.open-meteo.com/v1/forecast?"))
        for fragment in (
            "latitude=40.11",
            "longitude=-88.21",
            "timezone=America%2FChicago",
            "temperature_unit=fahrenheit",
            "wind_speed_unit=mph",
            "precipitation_unit=inch",
            "forecast_days=16",
        ):
            self.assertIn(fragment, url)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["daily"][0].split(","), list(weather.DAILY_KEYS))
        self.assertEqual(query["hourly"][0].split(","), list(weather.HOURLY_KEYS))
        self.assertEqual(fake_urlopen.call_args.kwargs["timeout"], 5)

    def test_timeout_raises_weather_unavailable(self):
        for error in (TimeoutError("timed out"), socket.timeout("timed out")):
            with self.subTest(error=type(error).__name__):
                with mock.patch("guidance.weather.urlopen", side_effect=error):
                    with self.assertRaises(weather.WeatherUnavailable):
                        weather.fetch_forecast()

    def test_http_error_raises_weather_unavailable(self):
        error = HTTPError("https://api.open-meteo.com", 503, "Service Unavailable", {}, None)
        with mock.patch("guidance.weather.urlopen", side_effect=error):
            with self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()

    def test_connection_error_raises_weather_unavailable(self):
        for error in (URLError("name resolution failed"), ConnectionRefusedError()):
            with self.subTest(error=type(error).__name__):
                with mock.patch("guidance.weather.urlopen", side_effect=error):
                    with self.assertRaises(weather.WeatherUnavailable):
                        weather.fetch_forecast()

    def test_invalid_json_raises_weather_unavailable(self):
        for body in (b"<html>busy</html>", b"", b"\xff\xfe\x00", b"[1, 2, 3]", b"null"):
            with self.subTest(body=body):
                with respond_with(body), self.assertRaises(weather.WeatherUnavailable):
                    weather.fetch_forecast()

    def test_oversized_response_raises(self):
        # A valid payload padded with JSON whitespace: only the size cap can reject it.
        valid = json.dumps(forecast_payload()).encode("utf-8")
        body = valid + b" " * (weather.MAX_RESPONSE_BYTES + 1 - len(valid))
        self.assertEqual(json.loads(body)["timezone"], "America/Chicago")
        with respond_with(body), self.assertRaises(weather.WeatherUnavailable):
            weather.fetch_forecast()

    def test_missing_daily_key_raises(self):
        payload = forecast_payload()
        del payload["daily"]["precipitation_probability_max"]
        with respond_with(payload), self.assertRaises(weather.WeatherUnavailable):
            weather.fetch_forecast()

    def test_missing_hourly_key_or_block_raises(self):
        without_key = forecast_payload()
        del without_key["hourly"]["precipitation_probability"]
        without_block = forecast_payload()
        del without_block["hourly"]
        for payload in (without_key, without_block):
            with respond_with(payload), self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()

    def test_mismatched_array_lengths_raise(self):
        short_daily = forecast_payload()
        short_daily["daily"]["wind_speed_10m_max"].pop()
        short_hourly = forecast_payload()
        short_hourly["hourly"]["temperature_2m"].pop()
        not_a_list = forecast_payload()
        not_a_list["daily"]["temperature_2m_max"] = "55"
        for payload in (short_daily, short_hourly, not_a_list):
            with respond_with(payload), self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()

    def test_empty_time_array_raises(self):
        payload = forecast_payload()
        for key in payload["daily"]:
            payload["daily"][key] = []
        with respond_with(payload), self.assertRaises(weather.WeatherUnavailable):
            weather.fetch_forecast()

    def test_wrong_timezone_raises(self):
        for timezone in ("UTC", "GMT", None):
            with self.subTest(timezone=timezone):
                with respond_with(forecast_payload(timezone=timezone)):
                    with self.assertRaises(weather.WeatherUnavailable):
                        weather.fetch_forecast()

    def test_wrong_units_raise(self):
        celsius = forecast_payload()
        celsius["daily_units"]["temperature_2m_max"] = "°C"
        kmh = forecast_payload()
        kmh["hourly_units"]["wind_speed_10m"] = "km/h"
        millimetres = forecast_payload()
        millimetres["daily_units"]["precipitation_sum"] = "mm"
        no_units = forecast_payload()
        del no_units["hourly_units"]
        for payload in (celsius, kmh, millimetres, no_units):
            with respond_with(payload), self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()

    def test_second_call_served_from_cache(self):
        with respond_with(forecast_payload()) as fake_urlopen:
            first = weather.fetch_forecast()
            second = weather.fetch_forecast()
        self.assertEqual(fake_urlopen.call_count, 1)
        self.assertEqual(first, second)

    def test_cache_timeout_is_30_minutes(self):
        with respond_with(forecast_payload()):
            with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
                weather.fetch_forecast()
        cache_set.assert_called_once()
        self.assertEqual(cache_set.call_args.args[0], "guidance:forecast:v1")
        self.assertEqual(cache_set.call_args.args[2], 1800)

    def test_failures_are_not_cached(self):
        responses = [URLError("down"), FakeResponse(json.dumps(forecast_payload()).encode())]
        with mock.patch("guidance.weather.urlopen", side_effect=responses) as fake_urlopen:
            with self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()
            result = weather.fetch_forecast()
        self.assertEqual(fake_urlopen.call_count, 2)
        self.assertEqual(result["timezone"], "America/Chicago")

    def test_invalid_payload_is_not_cached(self):
        with respond_with(forecast_payload(timezone="UTC")):
            with self.assertRaises(weather.WeatherUnavailable):
                weather.fetch_forecast()
        self.assertIsNone(cache.get("guidance:forecast:v1"))

    def test_failure_log_names_exception_class_only(self):
        secret_detail = "internal-host.example:1234 refused"
        with mock.patch("guidance.weather.urlopen", side_effect=URLError(secret_detail)):
            with self.assertLogs("guidance.weather", level="WARNING") as logs:
                with self.assertRaises(weather.WeatherUnavailable) as raised:
                    weather.fetch_forecast()
        output = "\n".join(logs.output)
        self.assertIn("URLError", output)
        self.assertNotIn(secret_detail, output)
        self.assertNotIn(secret_detail, str(raised.exception))
