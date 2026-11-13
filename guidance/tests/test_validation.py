"""Tests for the model output schema and the rule-based validator (plan Task 4, D4, D5).

Facts come from ``build_facts`` with the fixture payload and "today" frozen at
2026-11-10 (Central). Unless a test says otherwise the facts are for Thu, Nov 12
(lead 2) at 10:00, with peak hourly rain 60% and 20% for the hour starting at
10:00 (the T11:00 stamp). The other values come from the fixture: high 52°F,
low 37°F, wind 10 mph, gusts 17 mph, precipitation 0.02 inch, and 50°F with
10 mph wind at 10:00.
"""

import datetime
import json
import time as time_module
from datetime import date, time
from unittest import mock

from django.test import SimpleTestCase

from bookings.models import Service
from guidance import classify, schema, validation
from guidance.facts import build_facts
from guidance.tests.fixtures import forecast_payload

UTC = datetime.timezone.utc
TODAY = datetime.datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
NOV_12 = date(2026, 11, 12)  # lead 2: an uncertainty note is optional
NOV_13 = date(2026, 11, 13)  # lead 3: an uncertainty note is required

DAILY_KEY = {
    "temp_high_f": "temperature_2m_max",
    "temp_low_f": "temperature_2m_min",
    "peak_rain_chance_pct": "precipitation_probability_max",
    "precipitation_in": "precipitation_sum",
    "wind_max_mph": "wind_speed_10m_max",
    "gust_max_mph": "wind_gusts_10m_max",
}
ENUM_FIELDS = ("rain_level", "wind_level", "temperature_level", "confidence", "outlook")
TEXT_FIELDS = ("summary", "service_explanation", "uncertainty_note")
VALID_SUMMARY = (
    "The highest hourly rain probability on this date is 60%. "
    "At your appointment hour it is 20%."
)


def make_facts(day=NOV_12, at=time(10, 0), sensitivity="exterior", hourly=None,
               **daily_values):
    """Facts for one date; peak rain defaults to 60 and the T11:00 rain stamp to 20."""
    daily_values = {"peak_rain_chance_pct": 60, **daily_values}
    hourly_values = {"precipitation_probability": {f"{day.isoformat()}T11:00": 20}}
    for key, stamps in (hourly or {}).items():
        hourly_values.setdefault(key, {}).update(stamps)
    payload = forecast_payload(
        daily={DAILY_KEY[field]: {day.isoformat(): value}
               for field, value in daily_values.items()},
        hourly=hourly_values,
    )
    service = Service(name="Test service", slug="test-service",
                      weather_sensitivity=sensitivity)
    with mock.patch("django.utils.timezone.now", return_value=TODAY):
        return build_facts(payload, service, day, at)


def valid_output(facts, **changes):
    data = {field: getattr(facts, field) for field in ENUM_FIELDS}
    data.update(
        summary=VALID_SUMMARY,
        service_explanation="Rain can make an exterior wash dirty again sooner.",
        uncertainty_note=(
            "" if facts.lead_days < 3 else "The forecast may change before your appointment."
        ),
    )
    data.update(changes)
    return data


class ValidatorTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.facts = make_facts()

    def check(self, facts=None, **changes):
        facts = facts or self.facts
        return validation.validate_output(valid_output(facts, **changes), facts)

    def assertAccepted(self, facts=None, **changes):
        clean, reasons = self.check(facts, **changes)
        self.assertEqual(reasons, [])
        self.assertIsNotNone(clean)
        return clean

    def assertRejected(self, reason, facts=None, **changes):
        clean, reasons = self.check(facts, **changes)
        self.assertIsNone(clean)
        self.assertIn(reason, reasons)
        return reasons


class SchemaTests(SimpleTestCase):
    def test_output_schema_matches_plan(self):
        properties = schema.OUTPUT_SCHEMA["properties"]
        self.assertEqual(schema.OUTPUT_SCHEMA["type"], "object")
        self.assertIs(schema.OUTPUT_SCHEMA["additionalProperties"], False)
        self.assertEqual(tuple(properties), ENUM_FIELDS + TEXT_FIELDS)
        self.assertEqual(schema.OUTPUT_FIELDS, ENUM_FIELDS + TEXT_FIELDS)
        self.assertEqual(schema.OUTPUT_SCHEMA["required"], list(ENUM_FIELDS + TEXT_FIELDS))
        enums = {
            "rain_level": classify.RAIN_LEVELS,
            "wind_level": classify.WIND_LEVELS,
            "temperature_level": classify.TEMPERATURE_LEVELS,
            "confidence": classify.CONFIDENCE_LEVELS,
            "outlook": classify.OUTLOOKS,
        }
        for field, values in enums.items():
            with self.subTest(field=field):
                self.assertEqual(properties[field], {"type": "string", "enum": list(values)})
        self.assertEqual(schema.FIELD_LIMITS,
                         {"summary": 280, "service_explanation": 280, "uncertainty_note": 200})
        for field, limit in schema.FIELD_LIMITS.items():
            with self.subTest(field=field):
                self.assertEqual(properties[field], {"type": "string", "maxLength": limit})
        json.dumps(schema.OUTPUT_SCHEMA)


class AcceptAndSchemaTests(ValidatorTestCase):
    def test_valid_output_accepted(self):
        clean = self.assertAccepted()
        self.assertEqual(clean, valid_output(self.facts))

    def test_non_dict_or_missing_or_extra_keys_rejected_schema(self):
        valid = valid_output(self.facts)
        missing_key = dict(valid)
        del missing_key["uncertainty_note"]
        cases = {
            "none": None,
            "json text": json.dumps(valid),
            "malformed json text": '{"summary": "Rain',
            "list": [valid],
            "empty dict": {},
            "missing key": missing_key,
            "extra key": {**valid, "advice": "Bring an umbrella."},
            "non-text key": {**valid, 1: "x"},
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                self.assertEqual(validation.validate_output(data, self.facts), (None, ["schema"]))

    def test_non_string_field_rejected(self):
        for field in ENUM_FIELDS + TEXT_FIELDS:
            for value in (5, None, True, ["text"], {"text": "x"}):
                with self.subTest(field=field, value=value):
                    self.assertEqual(self.check(**{field: value}), (None, ["schema"]))

    def test_enum_value_outside_allowed_set_rejected(self):
        cases = {"rain_level": "moderate", "wind_level": "Windy", "temperature_level": "hot",
                 "confidence": "high", "outlook": "good"}
        for field, value in cases.items():
            with self.subTest(field=field):
                self.assertEqual(self.check(**{field: value}), (None, ["schema"]))

    def test_enum_not_matching_facts_rejected(self):
        windy = make_facts(wind_max_mph=20)
        self.assertEqual(windy.wind_level, "windy")
        self.assertRejected("enum_mismatch:wind_level", windy, wind_level="light")
        self.assertRejected("enum_mismatch:outlook", outlook="favorable")
        self.assertRejected("enum_mismatch:confidence", confidence="lower")
        self.assertRejected("enum_mismatch:rain_level", rain_level="low")
        self.assertRejected("enum_mismatch:temperature_level", temperature_level="warm")

    def test_validator_never_raises_on_odd_input(self):
        odd = [0, 1.5, b"{}", object(), {"summary": {"nested": True}},
               valid_output(self.facts, summary="9" * 100_000),
               valid_output(self.facts, summary="%" * 10_000)]
        for index, data in enumerate(odd):
            with self.subTest(index=index):
                clean, reasons = validation.validate_output(data, self.facts)
                self.assertIsNone(clean)
                self.assertTrue(reasons)

    def test_long_word_runs_are_validated_quickly(self):
        # A pattern that backtracks from every start position would take minutes here.
        for label, text in (("digits", "9" * 100_000), ("letters", "a" * 100_000),
                            ("mixed", "rain9." * 20_000)):
            for facts in (self.facts, make_facts(sensitivity="interior")):
                with self.subTest(text=label, sensitivity=facts.weather_sensitivity):
                    started = time_module.perf_counter()
                    validation.phrase_reasons(text, facts)
                    validation.number_reasons(text, facts)
                    self.assertLess(time_module.perf_counter() - started, 2.0)

    def test_reasons_are_unique_and_in_order(self):
        reasons = self.assertRejected(
            "markup:summary",
            summary="<b>It will rain</b> <i>all day</i>.",
            service_explanation="<b>Snow</b>",
        )
        self.assertEqual(len(reasons), len(set(reasons)))
        self.assertLess(reasons.index("markup:summary"),
                        reasons.index("markup:service_explanation"))


class FieldContentTests(ValidatorTestCase):
    def test_field_length_limits(self):
        for field, limit in schema.FIELD_LIMITS.items():
            with self.subTest(field=field):
                self.assertAccepted(**{field: "x" * limit})
                self.assertRejected(f"length:{field}", **{field: "x" * (limit + 1)})

    def test_length_measured_after_clean_up(self):
        self.assertAccepted(summary="x" * 279 + "   \n\t ")

    def test_markup_rejected(self):
        for character in "<>{}`":
            for field in TEXT_FIELDS:
                with self.subTest(character=character, field=field):
                    self.assertRejected(f"markup:{field}",
                                        **{field: f"Conditions look normal {character} today."})

    def test_control_chars_stripped_and_whitespace_collapsed(self):
        clean = self.assertAccepted(
            summary=(" The highest\x00 hourly rain\nprobability\t\ton this date is 60%.  "
                     "At your appointment hour\u200b it is\r\n20%.\x07 "),
        )
        self.assertEqual(clean["summary"], VALID_SUMMARY)

    def test_empty_text_rejected(self):
        self.assertRejected("empty:summary", summary="   \n ")
        self.assertRejected("empty:service_explanation", service_explanation="\x00\u200b")


class NumberTests(ValidatorTestCase):
    def test_invented_number_rejected(self):
        self.assertRejected("unsupported_number:45", summary="Gusts may reach 45 mph.")
        self.assertRejected("unsupported_number:3.5",
                            service_explanation="Washing takes about 3.5 hours.")

    def test_wind_number_used_as_rain_percent_rejected(self):
        facts = make_facts(peak_rain_chance_pct=36, wind_max_mph=17)
        summary = "The highest hourly rain probability on this date is 36%. "
        self.assertRejected("unit_mismatch:17%", facts,
                            summary="The highest hourly rain probability on this date is 17%.")
        self.assertRejected("unit_mismatch:36mph", facts,
                            summary=summary + "Winds reach 36 mph.")
        self.assertRejected("unit_mismatch:17°F", facts, summary=summary + "The high is 17°F.")
        self.assertRejected("unit_mismatch:52inch", facts,
                            summary=summary + "Up to 52 inches of rain may fall.")

    def test_spelled_number_with_unit_rejected(self):
        for text in ("There is a sixty percent chance of rain at the peak hour.",
                     "Winds of twenty mph are possible.",
                     "It may reach fifty-two degrees.",
                     "Gusts reach twenty five miles per hour."):
            with self.subTest(text=text):
                self.assertRejected("spelled_number", summary=text)

    def test_date_and_lead_numbers_allowed(self):
        self.assertAccepted(
            summary="Your 10:00 AM appointment on Thursday, November 12, 2026 is 2 days away.",
        )
        self.assertAccepted(summary="Your appointment is on 11/12/2026 at 10:00.")

    def test_fact_values_with_units_allowed(self):
        self.assertAccepted(
            summary=("The high is 52°F and the low is 37 degrees. Winds reach 10 mph with "
                     "gusts of 17 mph. Up to 0.02 inches of precipitation is forecast."),
        )

    def test_raw_and_rounded_values_allowed(self):
        facts = make_facts(wind_max_mph=19.5)
        self.assertAccepted(facts, summary=VALID_SUMMARY + " Winds reach 19.5 mph, about 20 mph.")

    def test_negative_temperature_keeps_its_sign(self):
        cold = make_facts(temp_low_f=-3)
        self.assertEqual(cold.temp_low_f, -3)
        self.assertAccepted(cold, summary=VALID_SUMMARY + " The low is -3°F.")
        self.assertAccepted(cold, summary=VALID_SUMMARY + " The low is \N{MINUS SIGN}3°F.")
        reasons = self.assertRejected("unsupported_number:3", cold,
                                      summary=VALID_SUMMARY + " The low is 3°F.")
        self.assertIn("unit_mismatch:3°F", reasons)
        # A positive fact never accepts a negative number.
        self.assertRejected("unsupported_number:-37",
                            summary=VALID_SUMMARY + " The low is -37°F.")

    def test_negative_raw_and_rounded_values_allowed(self):
        cold = make_facts(temp_low_f=-12.5)
        self.assertEqual(cold.temp_low_f, -13)
        self.assertAccepted(cold, summary=VALID_SUMMARY + " The low is -12.5°F (about -13°F).")

    def test_hyphen_between_numbers_is_not_a_minus_sign(self):
        self.assertAccepted(summary=VALID_SUMMARY + " Temperatures range from 37-52°F.")
        # A hyphen after a word joins words; it is not a minus sign.
        self.assertAccepted(summary=VALID_SUMMARY + " Expect a mild, near-52°F high.")

    def test_comma_grouped_and_scientific_numbers_checked_whole(self):
        cases = {
            "The highest hourly rain probability is 1,060%.": "unsupported_number:1,060",
            "The highest hourly rain probability is 6,0%.": "unsupported_number:6,0",
            "Winds may reach 1e3 mph.": "unsupported_number:1e3",
            "The highest hourly rain probability is 6e1%.": "unsupported_number:6e1",
            "Temperatures of 52,37 are forecast.": "unsupported_number:52,37",
        }
        for text, reason in cases.items():
            with self.subTest(text=text):
                self.assertRejected(reason, summary=text)

    def test_ordinary_decimals_and_dates_still_allowed(self):
        self.assertAccepted(
            summary=("The highest hourly rain probability on November 12, 2026 is 60.0%. "
                     "At your 10:00 AM appointment on 11/12/2026 it is 20%. "
                     "Up to 0.02 inches of precipitation is forecast."),
        )

    def test_celsius_spellings_rejected(self):
        for text in ("The high is 52 degrees C.", "The high is 52 degrees Celsius.",
                     "The high is 52 deg C.", "The high is 52 C.", "The high is 52 celsius.",
                     "The high is 52\N{DEGREE CELSIUS}.", "The high is 52 centigrade."):
            with self.subTest(text=text):
                self.assertRejected("unit_mismatch:52°c", summary=VALID_SUMMARY + " " + text)
        for text in ("The high is 52 degrees F.", "The high is 52 degrees Fahrenheit.",
                     "The high is 52\N{DEGREE FAHRENHEIT}."):
            with self.subTest(text=text):
                self.assertAccepted(summary=VALID_SUMMARY + " " + text)

    def test_foreign_units_rejected(self):
        self.assertRejected("unit_mismatch:11°c", summary=VALID_SUMMARY + " The high is 11°C.")
        reasons = self.assertRejected("unit_mismatch:16km/h",
                                      summary=VALID_SUMMARY + " Winds reach 16 km/h.")
        self.assertIn("unsupported_number:16", reasons)
        self.assertRejected("unit_mismatch:12mm", summary=VALID_SUMMARY + " Up to 12 mm may fall.")


class RainScopeTests(ValidatorTestCase):
    def test_peak_described_as_all_day_rejected(self):
        for text in ("There is a 60% chance of rain all day.",
                     "Rain is expected throughout the day.",
                     "Expect steady rain.",
                     "The daily chance of rain is 60%."):
            with self.subTest(text=text):
                self.assertRejected("rain_scope", summary=text)

    def test_peak_percent_without_peak_qualifier_rejected(self):
        self.assertRejected("rain_scope", summary="The chance of rain on Thursday is 60%.")
        # The qualifier must be in the same sentence as the percentage.
        self.assertRejected("rain_scope",
                            summary="Rain peaks later on. The chance of rain on this date is 60%.")

    def test_all_day_wording_without_rain_allowed(self):
        self.assertAccepted(summary=VALID_SUMMARY + " Winds stay constant all day.")

    def test_equivalent_number_forms_allowed(self):
        self.assertAccepted(summary="The highest hourly rain probability is 60.0%. "
                                    "At your appointment hour it is 20%.")

    def test_peak_percent_applied_to_appointment_rejected(self):
        self.assertRejected("rain_scope",
                            summary="There is a 60% chance of rain at your appointment.")

    def test_appointment_percent_without_appointment_qualifier_rejected(self):
        self.assertRejected("rain_scope", summary="The chance of rain is 20%.")
        self.assertRejected("rain_scope", summary="The highest hourly chance of rain is 20%.")

    def test_peak_and_appointment_wording_accepted(self):
        self.assertAccepted(
            summary=("The highest hourly rain probability is 60%. "
                     "At your appointment hour it is 20%."),
        )
        self.assertAccepted(summary="For the hour starting at 10:00 AM, rain is 20% likely.")
        # "a.m." does not end the sentence.
        self.assertAccepted(
            summary="For the hour starting at 10 a.m. the rain probability is 20%.")
        self.assertAccepted(
            summary="The peak hourly rain chance is 60%, and at your appointment it is 20%.",
        )

    def test_appointment_percent_without_hour_data_rejected(self):
        no_time = make_facts(at=None)
        self.assertRejected("rain_scope", no_time,
                            summary="There is a 60% chance of rain at your appointment.")
        self.assertRejected("rain_scope", no_time,
                            summary="The highest hourly rain chance is 60%, at your appointment.")
        self.assertAccepted(no_time, summary="The highest hourly rain probability is 60%.")
        no_hour_value = make_facts(
            hourly={"precipitation_probability": {"2026-11-12T11:00": None}})
        self.assertRejected("rain_scope", no_hour_value,
                            summary="The highest chance of rain at your appointment is 60%.")

    def test_equal_peak_and_hour_values_accept_either_qualifier(self):
        facts = make_facts(peak_rain_chance_pct=40,
                           hourly={"precipitation_probability": {"2026-11-12T11:00": 40}})
        self.assertAccepted(facts, summary="Rain probability peaks at 40%.")
        self.assertAccepted(facts, summary="At your appointment hour the rain probability is 40%.")
        self.assertRejected("rain_scope", facts, summary="The rain probability is 40%.")


class ContradictionTests(ValidatorTestCase):
    def test_rain_contradictions_both_directions(self):
        low = make_facts(peak_rain_chance_pct=10)
        self.assertEqual(low.rain_level, "low")
        for text in ("Heavy rain is possible.", "Rain is likely later.", "Rain is expected."):
            with self.subTest(level="low", text=text):
                self.assertRejected("contradiction:rain", low, summary=text)
        for text in ("It looks like a dry day.", "No rain is in the forecast.",
                     "Rain is unlikely."):
            with self.subTest(level="likely", text=text):
                self.assertRejected("contradiction:rain", summary=text)
        for facts in (low, self.facts):
            with self.subTest(level=facts.rain_level, text="It will rain."):
                self.assertRejected("contradiction:rain", facts, summary="It will rain.")

    def test_unknown_rain_rejects_wet_and_dry_claims(self):
        unknown = make_facts(peak_rain_chance_pct=None)
        for text in ("It looks like a dry day.", "Rain is likely.", "Heavy rain is possible.",
                     "There will be heavy rain."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:rain", unknown, summary=text)

    def test_unknown_rain_rejects_positive_rain_claims(self):
        unknown = make_facts(peak_rain_chance_pct=None)
        self.assertEqual(unknown.rain_level, "unknown")
        for text in ("Rain may occur.", "Rain is possible.", "Showers are possible later.",
                     "It may rain in the afternoon.", "There is a chance of rain.",
                     "Some rain could fall.", "Expect some showers.", "Rain is not expected.",
                     "It could be a rainy day."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:rain", unknown, summary=text)

    def test_unknown_rain_allows_unavailability_statements(self):
        unknown = make_facts(peak_rain_chance_pct=None)
        for text in ("The rain probability for this date is not available.",
                     "Rain data is unavailable for this date.",
                     "No rain probability is available for this date.",
                     "The chance of rain is not available in this forecast.",
                     "The forecast does not include a rain probability for this date."):
            with self.subTest(text=text):
                self.assertAccepted(unknown, summary=text)

    def test_unknown_rain_rejects_qualitative_claim_beside_missing_data_statement(self):
        # Saying data is missing elsewhere in the sentence does not excuse a claim.
        unknown = make_facts(peak_rain_chance_pct=None)
        for text in ("There is a high chance of rain, but the probability is unavailable.",
                     "There is a low likelihood of precipitation, although the forecast "
                     "data is unavailable.",
                     "The risk of showers is high, but the rain probability is not available.",
                     "The chance of rain is high, and the forecast data is unknown.",
                     "The chance of rain is high, but the forecast for this date is "
                     "unavailable.",
                     "The chance of rain is not available, but the risk of showers is high.",
                     "The high chance of rain is unknown."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:rain", unknown, summary=text)

    def test_unknown_rain_allows_value_itself_described_as_unavailable(self):
        unknown = make_facts(peak_rain_chance_pct=None)
        for text in ("The chance of rain is not available.",
                     "The likelihood of precipitation is unavailable for this date.",
                     "The chance of rain for this date is not available.",
                     "The odds of showers are unknown.",
                     "The risk of rain is currently unavailable."):
            with self.subTest(text=text):
                self.assertAccepted(unknown, summary=text)

    def test_known_low_rain_keeps_planned_rules(self):
        # The extra positive-claim rules apply to unknown rain only.
        low = make_facts(peak_rain_chance_pct=10)
        self.assertAccepted(low, summary="Rain is possible but the highest hourly rain "
                                         "probability is only 10%.")

    def test_unlikely_about_other_subjects_is_not_a_rain_contradiction(self):
        self.assertEqual(self.facts.rain_level, "likely")
        for text in ("Strong winds are unlikely.", "Gusts above 17 mph are unlikely.",
                     "Strong winds are unlikely, but the highest hourly rain probability "
                     "is 60%."):
            with self.subTest(text=text):
                self.assertAccepted(summary=VALID_SUMMARY + " " + text)

    def test_unlikely_about_rain_is_a_rain_contradiction(self):
        for text in ("Rain is unlikely.", "It is unlikely to rain.", "Rain looks unlikely today.",
                     "Showers are unlikely.", "It is unlikely that it will rain."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:rain", summary=text)

    def test_wind_understatement_rejected(self):
        windy = make_facts(wind_max_mph=20)
        for text in ("Expect a gentle breeze of 20 mph.", "Winds will be calm.",
                     "Only a light breeze is forecast."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:wind", windy, summary=text)

    def test_wind_overstatement_rejected(self):
        light = make_facts(wind_max_mph=5)
        self.assertEqual(light.wind_level, "light")
        for text in ("It will be very windy.", "Strong winds are forecast.",
                     "Conditions will be gusty."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:wind", light, summary=text)

    def test_temperature_contradiction_rejected(self):
        self.assertEqual(self.facts.temperature_level, "mild")
        for text in ("It will be a warm day.", "Expect hot weather.", "Roads may be icy.",
                     "Freezing temperatures are possible."):
            with self.subTest(text=text):
                self.assertRejected("contradiction:temperature", summary=text)

    def test_matching_temperature_words_accepted(self):
        freezing = make_facts(temp_low_f=30)
        self.assertAccepted(freezing,
                            summary=VALID_SUMMARY + " Freezing temperatures are possible.")
        warm = make_facts(temp_high_f=85)
        self.assertAccepted(warm, summary=VALID_SUMMARY + " It will be warm.")


class CertaintyTests(ValidatorTestCase):
    def test_guarantee_rejected(self):
        self.assertRejected("certainty", summary="We guarantee your car will stay clean.")
        self.assertRejected("certainty", summary="It won\u2019t rain.")  # curly apostrophe
        for phrase in validation.CERTAINTY_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertRejected("certainty", summary=f"Weather note: {phrase}.")

    def test_missing_uncertainty_rejected_when_lead_ge_3(self):
        facts = make_facts(day=NOV_13)
        self.assertEqual(facts.lead_days, 3)
        for note in ("", "Check the forecast.", "Forecasts are useful.",
                     # The plan's D5 pattern is used exactly: "can still change" is not in it.
                     "The forecast can still change."):
            with self.subTest(note=note):
                self.assertRejected("missing_uncertainty", facts, uncertainty_note=note)
        for note in ("The forecast may change before your appointment.",
                     "Forecasts this far ahead are uncertain.",
                     "You can check again closer to your appointment.",
                     "Check again later.",
                     "This could change."):
            with self.subTest(note=note):
                self.assertAccepted(facts, uncertainty_note=note)

    def test_empty_uncertainty_allowed_when_lead_lt_3(self):
        self.assertEqual(self.facts.lead_days, 2)
        self.assertAccepted(uncertainty_note="")


class AdviceAndTopicTests(ValidatorTestCase):
    def test_probe_advice_outputs_rejected(self):
        # The two real outputs from the 2026-11-10 Ollama probe.
        for text in ("Cover sensitive exterior components before your appointment.",
                     "Use a water-repellent coating to protect the paint."):
            with self.subTest(text=text):
                self.assertRejected("advice", service_explanation=text)

    def test_advice_phrases_rejected(self):
        for phrase in validation.ADVICE_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertRejected("advice", service_explanation=f"Note: {phrase} it.")

    def test_interior_service_contradiction_rejected(self):
        interior = make_facts(sensitivity="interior")
        self.assertEqual(interior.outlook, "weather_minor")
        for text in ("Rain could affect your interior clean.",
                     "Strong wind may damage the interior work.",
                     "The weather will ruin the cleaning."):
            with self.subTest(text=text):
                self.assertRejected("service_contradiction", interior,
                                    service_explanation=text)
        self.assertAccepted(service_explanation="Rain could affect your exterior wash.")

    def test_off_topic_rejected(self):
        for text in ("See https://example.com for details.", "Visit www.example.com today.",
                     "Email help@example.com with questions.", "It costs $ more.",
                     "The price stays the same.", "Ask about a discount.",
                     "Refunds are available.", "This is not medical advice.",
                     "Check your insurance.", "As an AI, I cannot know."):
            with self.subTest(text=text):
                self.assertRejected("off_topic", service_explanation=text)

    def test_unsupported_weather_conditions_rejected(self):
        # The facts hold rain, wind, temperature and precipitation only.
        for text in ("Snow is possible.", "Thunderstorms may form.", "Expect sunny skies.",
                     "Fog may form in the morning.", "It will be cloudy."):
            with self.subTest(text=text):
                self.assertRejected("unsupported_condition", summary=text)
