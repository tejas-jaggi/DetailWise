"""Tests for exact-date weather facts (plan Task 3, D1, D2, D9).

No test uses the network or a model. "Today" is frozen by patching
``django.utils.timezone.now``, which ``bookings.timeutils.central_now`` reads.
Unless a test says otherwise, today is 2026-11-10 in Central Time, the first
date of the default fixture payload (2026-11-10 to 2026-11-25).
"""

import dataclasses
import datetime
import json
from datetime import date, time
from unittest import mock

from django.test import SimpleTestCase, TestCase

from bookings.models import Service
from guidance import classify
from guidance.facts import OutOfRange, WeatherFacts, build_facts
from guidance.tests.fixtures import forecast_payload
from guidance.weather import WeatherUnavailable

UTC = datetime.timezone.utc
# 18:00 UTC is 12:00 in Central Time (CST) on the same date.
TODAY_NOV_10 = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
NOV_12 = date(2026, 11, 12)

DAILY_KEY = {
    "temp_high_f": "temperature_2m_max",
    "temp_low_f": "temperature_2m_min",
    "peak_rain_chance_pct": "precipitation_probability_max",
    "precipitation_in": "precipitation_sum",
    "wind_max_mph": "wind_speed_10m_max",
    "gust_max_mph": "wind_gusts_10m_max",
}
APPOINTMENT_FIELDS = ("appt_temp_f", "appt_wind_mph", "appt_rain_chance_pct")
VALUE_FIELDS = tuple(DAILY_KEY) + APPOINTMENT_FIELDS


def frozen(moment):
    return mock.patch("django.utils.timezone.now", return_value=moment)


def service(sensitivity="exterior"):
    """An unsaved service; build_facts reads only its name and weather sensitivity."""
    return Service(name=f"Test {sensitivity}", slug=f"test-{sensitivity}",
                   weather_sensitivity=sensitivity)


def daily(day, **values):
    """Fixture overrides for one date, keyed by WeatherFacts field name."""
    return {DAILY_KEY[field]: {day.isoformat(): value} for field, value in values.items()}


def json_round_trip(payload):
    """Parse the payload the way fetch_forecast does (json.loads accepts NaN/Infinity)."""
    return json.loads(json.dumps(payload))


def drop_hour(payload, stamp):
    """Remove one hourly stamp and its values."""
    hourly = payload["hourly"]
    index = hourly["time"].index(stamp)
    for values in hourly.values():
        del values[index]
    return payload


class FactsTestCase(SimpleTestCase):
    today = TODAY_NOV_10

    def setUp(self):
        patcher = frozen(self.today)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, payload=None, day=NOV_12, at=None, sensitivity="exterior"):
        payload = forecast_payload() if payload is None else payload
        return build_facts(payload, service(sensitivity), day, at)


class HorizonTests(FactsTestCase):
    def test_today_is_available_with_lead_zero(self):
        facts = self.build(day=date(2026, 11, 10))
        self.assertEqual(facts.date, date(2026, 11, 10))
        self.assertEqual(facts.lead_days, 0)
        self.assertEqual(facts.confidence, "higher")
        self.assertEqual(facts.temp_high_f, 50)

    def test_final_available_date_is_used(self):
        facts = self.build(day=date(2026, 11, 25))
        self.assertEqual(facts.lead_days, 15)
        self.assertEqual(facts.confidence, "lower")
        self.assertEqual(facts.temp_high_f, 65)  # index 15 in the fixture
        self.assertEqual(facts.last_forecast_date, date(2026, 11, 25))

    def test_day_after_final_date_is_out_of_range(self):
        with self.assertRaises(OutOfRange) as caught:
            self.build(day=date(2026, 11, 26))
        self.assertEqual(caught.exception.last_forecast_date, date(2026, 11, 25))
        self.assertFalse(caught.exception.within_range)

    def test_gap_inside_range_is_out_of_range_not_neighbour(self):
        payload = forecast_payload(drop_dates=("2026-11-18",))
        with self.assertRaises(OutOfRange) as caught:
            self.build(payload, day=date(2026, 11, 18))
        self.assertEqual(caught.exception.last_forecast_date, date(2026, 11, 25))
        self.assertTrue(caught.exception.within_range)
        # The neighbours keep their own values; nothing moves into the gap.
        self.assertEqual(self.build(payload, day=date(2026, 11, 17)).temp_high_f, 57)
        self.assertEqual(self.build(payload, day=date(2026, 11, 19)).temp_high_f, 59)

    def test_malformed_last_date_raises_weather_unavailable(self):
        payload = forecast_payload()
        payload["daily"]["time"][-1] = "not-a-date"
        with self.assertRaises(WeatherUnavailable):
            self.build(payload)


class CachedPayloadTests(FactsTestCase):
    today = datetime.datetime(2026, 11, 11, 18, 0, tzinfo=UTC)

    def test_cached_payload_starting_yesterday_still_exact(self):
        facts = self.build(forecast_payload(start=date(2026, 11, 10)), day=date(2026, 11, 11))
        self.assertEqual(facts.lead_days, 0)
        # Nov 11 is index 1 of a payload starting Nov 10.
        self.assertEqual((facts.temp_high_f, facts.temp_low_f, facts.peak_rain_chance_pct),
                         (51, 36, 15))

    def test_past_central_date_rejected(self):
        # The request form rejects past dates before any lookup (D1); reaching
        # build_facts with one is a caller error, not a forecast condition.
        with self.assertRaisesRegex(ValueError, "before today in Central Time"):
            self.build(forecast_payload(start=date(2026, 11, 10)), day=date(2026, 11, 10))


class CentralTimeTests(FactsTestCase):
    # 00:30 UTC on Nov 11 is 18:30 on Nov 10 in Central Time.
    today = datetime.datetime(2026, 11, 11, 0, 30, tzinfo=UTC)

    def test_lead_days_use_central_date_not_utc(self):
        self.assertEqual(self.build(day=date(2026, 11, 10)).lead_days, 0)
        self.assertEqual(self.build(day=date(2026, 11, 11)).lead_days, 1)


class ValueTests(FactsTestCase):
    def test_extracts_and_rounds_values(self):
        payload = forecast_payload(
            daily=daily(NOV_12, temp_high_f=54.5, temp_low_f=32.4, peak_rain_chance_pct=36.5,
                        precipitation_in=0.123, wind_max_mph=19.5, gust_max_mph=27.49),
            hourly={
                "temperature_2m": {"2026-11-12T10:00": 44.5},
                "wind_speed_10m": {"2026-11-12T10:00": 9.5},
                "precipitation_probability": {"2026-11-12T11:00": 20.5},
            },
        )
        facts = self.build(payload, at=time(10, 30))
        self.assertEqual(
            (facts.temp_high_f, facts.temp_low_f, facts.peak_rain_chance_pct,
             facts.wind_max_mph, facts.gust_max_mph),
            (55, 32, 37, 20, 27),
        )
        self.assertEqual((facts.appt_temp_f, facts.appt_wind_mph, facts.appt_rain_chance_pct),
                         (45, 10, 21))
        for field in VALUE_FIELDS:
            if field != "precipitation_in":
                with self.subTest(field=field):
                    self.assertIsInstance(getattr(facts, field), int)
        self.assertEqual(facts.precipitation_in, 0.123)  # inches are not rounded
        self.assertEqual(facts.missing, ())
        # Classes use the displayed (rounded) values: low 32 is a freezing risk,
        # wind 20 is windy.
        self.assertEqual(facts.temperature_level, "freezing risk")
        self.assertEqual(facts.wind_level, "windy")
        self.assertEqual(facts.rain_level, "possible")

    def test_missing_daily_value_is_none_and_listed(self):
        facts = self.build(forecast_payload(daily=daily(NOV_12, precipitation_in=None)))
        self.assertIsNone(facts.precipitation_in)
        self.assertEqual(facts.missing, ("precipitation_in",))
        self.assertEqual((facts.temp_high_f, facts.wind_max_mph), (52, 10))

    def test_non_numeric_value_treated_as_missing(self):
        facts = self.build(forecast_payload(daily=daily(NOV_12, wind_max_mph="12 mph")))
        self.assertIsNone(facts.wind_max_mph)
        self.assertEqual(facts.wind_level, "unknown")
        self.assertEqual(facts.missing, ("wind_max_mph",))

    def test_all_core_values_missing_raises_weather_unavailable(self):
        core = dict(temp_high_f=None, temp_low_f=None, peak_rain_chance_pct=None,
                    wind_max_mph=None)
        with self.assertRaises(WeatherUnavailable):
            self.build(forecast_payload(daily=daily(NOV_12, **core)))
        # One usable core value is enough.
        for field in core:
            others = {name: None for name in core if name != field}
            with self.subTest(usable=field):
                facts = self.build(forecast_payload(daily=daily(NOV_12, **others)))
                self.assertIsNotNone(getattr(facts, field))
                self.assertEqual(set(facts.missing), set(others))

    def test_invalid_values_become_missing(self):
        not_numbers = (True, float("nan"), float("inf"), "55", [5])
        hourly_key = {
            "appt_temp_f": ("temperature_2m", "2026-11-12T10:00"),
            "appt_wind_mph": ("wind_speed_10m", "2026-11-12T10:00"),
            "appt_rain_chance_pct": ("precipitation_probability", "2026-11-12T11:00"),
        }
        cases = [(field, bad) for field in VALUE_FIELDS for bad in not_numbers]
        cases += [
            ("peak_rain_chance_pct", 120), ("peak_rain_chance_pct", -5),
            ("appt_rain_chance_pct", 101), ("wind_max_mph", -3), ("gust_max_mph", -1),
            ("precipitation_in", -0.2), ("appt_wind_mph", -0.5),
        ]
        for field, bad in cases:
            if field in hourly_key:
                key, stamp = hourly_key[field]
                payload = forecast_payload(hourly={key: {stamp: bad}})
            else:
                payload = forecast_payload(daily=daily(NOV_12, **{field: bad}))
            with self.subTest(field=field, value=bad):
                facts = self.build(json_round_trip(payload), at=time(10, 0))
                self.assertIsNone(getattr(facts, field))
                self.assertEqual(facts.missing, (field,))

    def test_very_large_integer_does_not_leak_overflow(self):
        # math.isfinite() raises OverflowError for an int too large for a float.
        # Integers are always finite, so only the range rules decide.
        huge = 10 ** 400
        hourly_key = {
            "appt_wind_mph": ("wind_speed_10m", "2026-11-12T10:00"),
            "appt_rain_chance_pct": ("precipitation_probability", "2026-11-12T11:00"),
        }
        cases = [
            ("peak_rain_chance_pct", huge, None),  # above 100
            ("peak_rain_chance_pct", -huge, None),  # below 0
            ("wind_max_mph", -huge, None),
            ("gust_max_mph", -huge, None),
            ("precipitation_in", -huge, None),
            ("precipitation_in", huge, huge),  # finite and not negative: kept, not rounded
            ("appt_rain_chance_pct", huge, None),
            ("appt_wind_mph", -huge, None),
        ]
        for field, value, expected in cases:
            if field in hourly_key:
                key, stamp = hourly_key[field]
                payload = forecast_payload(hourly={key: {stamp: value}})
            else:
                payload = forecast_payload(daily=daily(NOV_12, **{field: value}))
            with self.subTest(field=field, sign="-" if value < 0 else "+"):
                facts = self.build(json_round_trip(payload), at=time(10, 0))
                self.assertEqual(getattr(facts, field), expected)
                self.assertEqual(facts.missing, (field,) if expected is None else ())

    def test_extreme_finite_values_are_kept_and_classified(self):
        # No upper limit exists for temperature, wind or gust, so huge finite values
        # are kept, rounded and classified; nothing raises a numeric exception.
        huge = 10 ** 400
        max_float = 1.7976931348623157e308
        cases = {
            "huge integers": (
                dict(temp_high_f=huge, temp_low_f=-huge, wind_max_mph=huge, gust_max_mph=huge),
                {"temperature_2m": huge, "wind_speed_10m": huge},
                dict(temp_high_f=huge, temp_low_f=-huge, wind_max_mph=huge, gust_max_mph=huge,
                     appt_temp_f=huge, appt_wind_mph=huge),
                ("freezing risk", "very windy"),
            ),
            "huge floats": (
                dict(temp_high_f=1e300, temp_low_f=1e28, wind_max_mph=max_float,
                     gust_max_mph=1e300),
                {"temperature_2m": -1e300, "wind_speed_10m": 1e300},
                dict(temp_high_f=10 ** 300, temp_low_f=10 ** 28,
                     wind_max_mph=17976931348623157 * 10 ** 292, gust_max_mph=10 ** 300,
                     appt_temp_f=-(10 ** 300), appt_wind_mph=10 ** 300),
                ("warm", "very windy"),
            ),
        }
        for label, (daily_values, hour_values, expected, classes) in cases.items():
            payload = forecast_payload(
                daily=daily(NOV_12, **daily_values),
                hourly={key: {"2026-11-12T10:00": value} for key, value in hour_values.items()},
            )
            with self.subTest(case=label):
                facts = self.build(json_round_trip(payload), at=time(10, 0))
                for field, value in expected.items():
                    self.assertTrue(getattr(facts, field) == value, field)
                self.assertEqual((facts.temperature_level, facts.wind_level), classes)
                self.assertEqual(facts.missing, ())
                self.assertIn("wind", facts.concerns)
                # Every consumer of the facts copes with the values too.
                allowed = facts.allowed_numbers()
                self.assertIn(str(expected["wind_max_mph"]), allowed["wind"])
                json.dumps(facts.as_prompt_dict())
                json.dumps(facts.as_public_dict())

    def test_allowed_numbers_keep_every_digit_of_large_integers(self):
        value = 10 ** 30 + 1  # more digits than the default decimal precision (28)
        facts = self.build(forecast_payload(daily=daily(NOV_12, wind_max_mph=value)))
        self.assertIn("1000000000000000000000000000001", facts.allowed_numbers()["wind"])

    def test_boundary_values_are_kept(self):
        payload = forecast_payload(
            daily=daily(NOV_12, peak_rain_chance_pct=100, wind_max_mph=0, gust_max_mph=0,
                        precipitation_in=0, temp_low_f=-12.5),
            hourly={"precipitation_probability": {"2026-11-12T11:00": 0}},
        )
        facts = self.build(payload, at=time(10, 0))
        self.assertEqual(facts.missing, ())
        self.assertEqual((facts.peak_rain_chance_pct, facts.appt_rain_chance_pct), (100, 0))
        self.assertEqual((facts.wind_max_mph, facts.gust_max_mph, facts.precipitation_in),
                         (0, 0, 0))
        self.assertEqual(facts.temp_low_f, -13)  # half-up rounds -12.5 away from zero

    def test_invalid_field_keeps_known_concerns(self):
        payload = forecast_payload(
            daily=daily(NOV_12, peak_rain_chance_pct=150, wind_max_mph=35, temp_low_f=25)
        )
        facts = self.build(payload)
        self.assertEqual(facts.concerns, ("wind", "freezing"))
        self.assertEqual(facts.outlook, "concerns")
        self.assertEqual(facts.missing, ("peak_rain_chance_pct",))

    def test_all_core_values_invalid_raises_weather_unavailable(self):
        payload = forecast_payload(
            daily=daily(NOV_12, temp_high_f="hot", temp_low_f=float("nan"),
                        peak_rain_chance_pct=150, wind_max_mph=-3)
        )
        with self.assertRaises(WeatherUnavailable):
            self.build(json_round_trip(payload))

    def test_low_above_high_makes_both_temperatures_missing(self):
        payload = forecast_payload(
            daily=daily(NOV_12, temp_low_f=50, temp_high_f=40, peak_rain_chance_pct=60,
                        wind_max_mph=35, gust_max_mph=45, precipitation_in=0.3)
        )
        facts = self.build(payload)
        self.assertIsNone(facts.temp_low_f)
        self.assertIsNone(facts.temp_high_f)
        self.assertEqual(facts.missing, ("temp_high_f", "temp_low_f"))
        self.assertEqual(facts.temperature_level, "unknown")
        self.assertEqual(facts.peak_rain_chance_pct, 60)
        self.assertEqual(facts.wind_max_mph, 35)
        self.assertEqual(facts.gust_max_mph, 45)
        self.assertEqual(facts.precipitation_in, 0.3)
        self.assertEqual(facts.concerns, ("rain", "wind"))
        self.assertEqual(facts.outlook, "concerns")

    def test_low_above_high_keeps_appointment_hour_values(self):
        payload = forecast_payload(daily=daily(NOV_12, temp_low_f=50, temp_high_f=40))
        facts = self.build(payload, at=time(10, 0))
        self.assertEqual((facts.appt_temp_f, facts.appt_wind_mph, facts.appt_rain_chance_pct),
                         (50, 10, 11))

    def test_low_equal_to_high_is_kept(self):
        facts = self.build(forecast_payload(daily=daily(NOV_12, temp_low_f=40, temp_high_f=40)))
        self.assertEqual((facts.temp_low_f, facts.temp_high_f), (40, 40))
        self.assertEqual(facts.missing, ())
        self.assertEqual(facts.temperature_level, "cold")

    def test_low_above_high_with_other_core_values_missing_raises_weather_unavailable(self):
        payload = forecast_payload(
            daily=daily(NOV_12, temp_low_f=50, temp_high_f=40, peak_rain_chance_pct=None,
                        wind_max_mph=None)
        )
        with self.assertRaises(WeatherUnavailable):
            self.build(payload)

    def test_missing_values_never_replaced_from_other_dates(self):
        payload = forecast_payload(
            daily=daily(NOV_12, temp_high_f=None, peak_rain_chance_pct=None),
            hourly={"temperature_2m": {"2026-11-12T10:00": None}},
        )
        facts = self.build(payload, at=time(10, 0))
        self.assertIsNone(facts.temp_high_f)
        self.assertIsNone(facts.peak_rain_chance_pct)
        self.assertIsNone(facts.appt_temp_f)
        self.assertEqual(facts.rain_level, "unknown")
        self.assertEqual(facts.missing, ("temp_high_f", "peak_rain_chance_pct", "appt_temp_f"))
        # The neighbouring dates still have their own values.
        self.assertEqual(self.build(payload, day=date(2026, 11, 11)).temp_high_f, 51)
        self.assertEqual(self.build(payload, day=date(2026, 11, 13)).temp_high_f, 53)


class HourlyTests(FactsTestCase):
    def test_hour_values_for_appointment_time(self):
        payload = forecast_payload(hourly={
            "temperature_2m": {"2026-11-12T10:00": 61, "2026-11-12T11:00": 99},
            "wind_speed_10m": {"2026-11-12T10:00": 13, "2026-11-12T11:00": 99},
            "precipitation_probability": {"2026-11-12T10:00": 99, "2026-11-12T11:00": 27},
        })
        facts = self.build(payload, at=time(10, 30))
        self.assertEqual(facts.time, time(10, 30))
        self.assertEqual((facts.appt_temp_f, facts.appt_wind_mph, facts.appt_rain_chance_pct),
                         (61, 13, 27))

    def test_appointment_rain_uses_following_stamp_at_2300(self):
        payload = forecast_payload(hourly={
            "precipitation_probability": {"2026-11-12T23:00": 7, "2026-11-13T00:00": 42},
        })
        facts = self.build(payload, at=time(23, 0))
        self.assertEqual(facts.appt_rain_chance_pct, 42)
        self.assertEqual(facts.appt_temp_f, 63)  # 2026-11-12T23:00
        # On the final date the following stamp does not exist.
        last = self.build(payload, day=date(2026, 11, 25), at=time(23, 0))
        self.assertIsNone(last.appt_rain_chance_pct)
        self.assertEqual(last.missing, ("appt_rain_chance_pct",))
        self.assertEqual(last.appt_temp_f, 63)

    def test_peak_and_appointment_rain_kept_separate(self):
        payload = forecast_payload(
            daily=daily(NOV_12, peak_rain_chance_pct=60),
            hourly={"precipitation_probability": {"2026-11-12T11:00": 20}},
        )
        facts = self.build(payload, at=time(10, 0))
        self.assertEqual(facts.peak_rain_chance_pct, 60)
        self.assertEqual(facts.appt_rain_chance_pct, 20)
        self.assertEqual(facts.rain_level, "likely")

    def test_no_hour_values_without_time(self):
        facts = self.build()
        self.assertIsNone(facts.time)
        for field in APPOINTMENT_FIELDS:
            with self.subTest(field=field):
                self.assertIsNone(getattr(facts, field))
        self.assertEqual(facts.missing, ())

    def test_missing_hour_stamp_gives_daily_only(self):
        payload = drop_hour(forecast_payload(), "2026-11-12T10:00")
        facts = self.build(payload, at=time(10, 0))
        self.assertIsNone(facts.appt_temp_f)
        self.assertIsNone(facts.appt_wind_mph)
        self.assertEqual(facts.missing, ("appt_temp_f", "appt_wind_mph"))
        self.assertEqual(facts.appt_rain_chance_pct, 11)  # the T11:00 stamp still exists
        self.assertEqual((facts.temp_high_f, facts.peak_rain_chance_pct), (52, 20))

    def test_null_hour_value_listed_missing(self):
        payload = forecast_payload(hourly={"wind_speed_10m": {"2026-11-12T10:00": None}})
        facts = self.build(payload, at=time(10, 0))
        self.assertIsNone(facts.appt_wind_mph)
        self.assertEqual(facts.missing, ("appt_wind_mph",))
        self.assertEqual(facts.appt_temp_f, 50)


class FallBackDayTests(FactsTestCase):
    today = datetime.datetime(2026, 11, 1, 18, 0, tzinfo=UTC)

    def test_fall_back_day_uses_single_01_stamp(self):
        payload = forecast_payload(start=date(2026, 11, 1), days=3)
        stamps = [s for s in payload["hourly"]["time"] if s.startswith("2026-11-01T")]
        self.assertEqual(len(stamps), 24)
        self.assertEqual(len(set(stamps)), 24)
        facts = self.build(payload, day=date(2026, 11, 1), at=time(1, 30))
        self.assertEqual(facts.appt_temp_f, 41)  # the single T01:00 stamp
        self.assertEqual(facts.appt_rain_chance_pct, 2)  # T02:00
        self.assertEqual(facts.missing, ())


class SpringForwardTests(FactsTestCase):
    today = datetime.datetime(2027, 3, 10, 18, 0, tzinfo=UTC)

    def test_nonexistent_spring_forward_time_gives_daily_only(self):
        payload = forecast_payload(start=date(2027, 3, 10), days=7)
        facts = self.build(payload, day=date(2027, 3, 14), at=time(2, 30))
        for field in APPOINTMENT_FIELDS:
            with self.subTest(field=field):
                self.assertIsNone(getattr(facts, field))
        self.assertEqual(facts.missing, APPOINTMENT_FIELDS)
        self.assertEqual(facts.temp_high_f, 54)  # daily values still used
        # A real time on the same date uses its hour values.
        later = self.build(payload, day=date(2027, 3, 14), at=time(3, 30))
        self.assertEqual(later.appt_temp_f, 43)
        self.assertEqual(later.missing, ())


class ClassificationTests(FactsTestCase):
    def test_classes_come_from_classify_rules(self):
        payload = forecast_payload(daily={
            "precipitation_probability_max": {"2026-11-13": None},
            "temperature_2m_min": {"2026-11-14": 28},
            "wind_speed_10m_max": {"2026-11-15": 30},  # wind is the only concern
        })
        for offset in range(16):
            day = date(2026, 11, 10) + datetime.timedelta(days=offset)
            for sensitivity in ("exterior", "interior", "mixed"):
                facts = self.build(payload, day=day, sensitivity=sensitivity)
                rain = classify.rain_level(facts.peak_rain_chance_pct)
                wind = classify.wind_level(facts.wind_max_mph)
                temperature = classify.temperature_level(facts.temp_low_f, facts.temp_high_f)
                with self.subTest(day=day, sensitivity=sensitivity):
                    self.assertEqual((facts.rain_level, facts.wind_level,
                                      facts.temperature_level),
                                     (rain, wind, temperature))
                    self.assertEqual(facts.concerns, classify.concerns(rain, wind, temperature))
                    self.assertEqual(facts.outlook,
                                     classify.outlook(sensitivity, rain, wind, temperature))
                    self.assertEqual(facts.confidence, classify.confidence(offset))

    def test_outlook_with_missing_rain_keeps_known_concerns(self):
        payload = forecast_payload(
            daily=daily(NOV_12, peak_rain_chance_pct=None, wind_max_mph=35, temp_low_f=25)
        )
        facts = self.build(payload)
        self.assertEqual(facts.outlook, "concerns")
        self.assertEqual(facts.concerns, ("wind", "freezing"))
        self.assertIn("peak_rain_chance_pct", facts.missing)
        interior = self.build(payload, sensitivity="interior")
        self.assertEqual(interior.outlook, "weather_minor")
        self.assertEqual(interior.concerns, ("wind", "freezing"))

    def test_weather_facts_is_frozen(self):
        facts = self.build()
        self.assertIsInstance(facts, WeatherFacts)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            facts.outlook = "favorable"


class AllowedNumberTests(FactsTestCase):
    def test_allowed_numbers_by_category(self):
        day = date(2026, 11, 22)  # fixture index 12: wind 20, gust 27, high 62, low 47
        payload = forecast_payload(daily=daily(day, peak_rain_chance_pct=36))
        facts = self.build(payload, day=day, at=time(10, 0))
        allowed = facts.allowed_numbers()
        self.assertEqual(
            set(allowed),
            {"rain_peak", "rain_appointment", "wind", "temperature", "precipitation",
             "calendar", "all"},
        )
        self.assertIn("36", allowed["rain_peak"])
        self.assertNotIn("36", allowed["wind"])
        self.assertNotIn("36", allowed["rain_appointment"])
        self.assertEqual(allowed["rain_appointment"], {"11"})  # the T11:00 stamp
        self.assertTrue({"20", "27", "10"} <= allowed["wind"])
        self.assertTrue({"62", "47", "50"} <= allowed["temperature"])
        self.assertIn("0.12", allowed["precipitation"])
        self.assertIn("2026", allowed["calendar"])
        self.assertIn("22", allowed["calendar"])
        self.assertIn("11", allowed["calendar"])  # the month
        self.assertIn("12", allowed["calendar"])  # lead days
        self.assertIn("10", allowed["calendar"])  # the appointment hour
        self.assertIn("00", allowed["calendar"])  # the appointment minutes
        union = set().union(*(v for k, v in allowed.items() if k != "all"))
        self.assertEqual(allowed["all"], union)

    def test_allowed_numbers_include_raw_and_rounded(self):
        payload = forecast_payload(daily=daily(NOV_12, wind_max_mph=19.5, temp_high_f=54.6))
        allowed = self.build(payload).allowed_numbers()
        self.assertTrue({"19.5", "20"} <= allowed["wind"])
        self.assertTrue({"54.6", "55"} <= allowed["temperature"])

    def test_allowed_numbers_keep_the_sign_of_negative_values(self):
        payload = forecast_payload(daily=daily(NOV_12, temp_low_f=-12.5, temp_high_f=-3))
        temperature = self.build(payload).allowed_numbers()["temperature"]
        self.assertTrue({"-12.5", "-13", "-3"} <= temperature)
        self.assertFalse({"12.5", "13", "3"} & temperature)

    def test_allowed_numbers_skip_missing_and_absent_values(self):
        payload = forecast_payload(daily=daily(NOV_12, peak_rain_chance_pct=None))
        allowed = self.build(payload).allowed_numbers()
        self.assertEqual(allowed["rain_peak"], set())
        self.assertEqual(allowed["rain_appointment"], set())  # no appointment time


class DictTests(FactsTestCase):
    def test_prompt_dict_names_rain_values_unambiguously(self):
        payload = forecast_payload(
            daily=daily(NOV_12, peak_rain_chance_pct=60, gust_max_mph=None),
            hourly={"precipitation_probability": {"2026-11-12T11:00": 20}},
        )
        with_time = self.build(payload, at=time(10, 0)).as_prompt_dict()
        self.assertEqual(with_time["peak_hourly_rain_probability_pct"], 60)
        self.assertEqual(with_time["appointment_hour_rain_probability_pct"], 20)
        self.assertEqual(
            with_time["rain_probability_note"],
            "peak_hourly_rain_probability_pct is the highest chance of rain for any single "
            "hour of the date. It is not the chance of rain all day.",
        )
        self.assertEqual(with_time["appointment_time"], "10:00")
        self.assertNotIn("max_gust_mph", with_time)  # missing values are left out
        self.assertEqual(with_time["not_available"], ["wind gust speed"])
        self.assertNotIn(None, with_time.values())
        for key in ("rain_level", "wind_level", "temperature_level", "confidence", "outlook",
                    "lead_days", "service_consideration"):
            with self.subTest(key=key):
                self.assertIn(key, with_time)
        without_time = self.build(payload).as_prompt_dict()
        self.assertNotIn("appointment_hour_rain_probability_pct", without_time)
        self.assertNotIn("appointment_time", without_time)
        json.dumps(with_time)

    def test_public_dict_is_json_ready(self):
        facts = self.build(forecast_payload(daily=daily(NOV_12, gust_max_mph=None)),
                           at=time(9, 15))
        public = facts.as_public_dict()
        self.assertEqual(public["date"], "2026-11-12")
        self.assertEqual(public["time"], "09:15")
        self.assertEqual(public["last_forecast_date"], "2026-11-25")
        self.assertIsNone(public["gust_max_mph"])
        self.assertEqual(public["missing"], ["gust_max_mph"])
        self.assertEqual(public["concerns"], [])
        for field in VALUE_FIELDS + ("rain_level", "outlook", "service_name"):
            with self.subTest(field=field):
                self.assertIn(field, public)
        json.dumps(public)


class SeededServiceTests(TestCase):
    def test_service_context_from_seeded_service(self):
        expected = {"exterior-wash": "exterior", "interior-clean": "interior",
                    "full-detail": "mixed"}
        with frozen(TODAY_NOV_10):
            for slug, sensitivity in expected.items():
                seeded = Service.objects.get(slug=slug)
                facts = build_facts(forecast_payload(), seeded, NOV_12)
                with self.subTest(slug=slug):
                    self.assertEqual(facts.service_name, seeded.name)
                    self.assertEqual(facts.weather_sensitivity, sensitivity)
                    self.assertEqual(facts.service_consideration,
                                     classify.service_consideration(sensitivity))
                    if sensitivity == "interior":
                        self.assertEqual(facts.outlook, "weather_minor")
