"""Tests for the deterministic fallback and the customer sections (plan Task 4, D3, D4).

Facts are built as in test_validation: today is 2026-11-10 (Central); by default
the date is Thu, Nov 12 at 10:00, peak hourly rain 60% and 20% for the hour
starting at 10:00.
"""

import re
from datetime import date, time

from django.test import SimpleTestCase

from guidance import classify, fallback, validation
from guidance.tests.test_validation import make_facts, valid_output

LABELS = ["Conditions", "For your service", "Forecast confidence", "Recommendation"]
PEAK_SENTENCE = "The highest hourly rain probability on Thu, Nov 12 is 60%."
HOUR_SENTENCE = "For the hour containing your 10:00 AM appointment, the rain probability is 20%."


def by_label(sections):
    return {section["label"]: section["text"] for section in sections}


def python_recommendation(facts):
    return classify.recommendation(facts.outlook, facts.concerns, facts.missing,
                                   facts.confidence)


class FallbackSectionTests(SimpleTestCase):
    def test_exact_fallback_sections(self):
        facts = make_facts()
        sections = fallback.fallback_sections(facts)
        self.assertEqual([section["label"] for section in sections], LABELS)
        self.assertEqual(
            by_label(sections),
            {
                "Conditions": (
                    f"{PEAK_SENTENCE} {HOUR_SENTENCE} "
                    "The forecast high is 52°F and the low is 37°F. "
                    "The forecast maximum wind speed is 10 mph, with gusts up to 17 mph. "
                    "The forecast precipitation total is 0.02 inches. "
                    "For your 10:00 AM appointment, the hourly temperature estimate is 50°F and "
                    "the hourly wind speed estimate is 10 mph."
                ),
                "For your service": classify.service_consideration("exterior"),
                "Forecast confidence": classify.confidence_sentence("higher", 2),
                "Recommendation": python_recommendation(facts),
            },
        )

    def test_fallback_sections_pass_validator_rules(self):
        days = {0: date(2026, 11, 10), 3: date(2026, 11, 13), 15: date(2026, 11, 25)}
        rains = {"low": 10, "likely": 60, "unknown": None}
        for sensitivity in ("exterior", "interior", "mixed"):
            for lead, day in days.items():
                for rain, peak in rains.items():
                    for at in (time(10, 0), time(14, 30), None):
                        facts = make_facts(day=day, at=at, sensitivity=sensitivity,
                                           peak_rain_chance_pct=peak)
                        texts = by_label(fallback.fallback_sections(facts))
                        with self.subTest(sensitivity=sensitivity, lead=lead, rain=rain, at=at):
                            self.assertEqual((facts.lead_days, facts.rain_level), (lead, rain))
                            for label in LABELS[:3]:
                                self.assertEqual(
                                    validation.text_reasons(texts[label], facts), [], label)
                            # The recommendation quotes Task 2's thresholds (50%, 20 mph,
                            # 32°F), so only the phrase rules apply to it.
                            self.assertEqual(
                                validation.phrase_reasons(texts["Recommendation"], facts), [])
                            if lead >= 3:
                                self.assertRegex(texts["Forecast confidence"],
                                                 validation.UNCERTAINTY_PATTERN)

    def test_fallback_omits_missing_values(self):
        facts = make_facts(
            temp_high_f=None, gust_max_mph=None, precipitation_in=None,
            hourly={"temperature_2m": {"2026-11-12T10:00": None}},
        )
        conditions = by_label(fallback.fallback_sections(facts))["Conditions"]
        self.assertNotIn("None", conditions)
        self.assertNotRegex(conditions, r"(?<!\d)(°F|%)")
        self.assertNotRegex(conditions, r"(?<!\d) (mph|inch)")
        self.assertIn("The forecast low is 37°F.", conditions)
        self.assertIn("The forecast maximum wind speed is 10 mph.", conditions)
        self.assertIn("For your 10:00 AM appointment, the hourly wind speed estimate is 10 mph.",
                      conditions)
        self.assertNotIn("high is", conditions)
        self.assertNotIn("gust", conditions)
        self.assertNotIn("precipitation", conditions)

    def test_fallback_partial_values(self):
        cases = [
            (dict(wind_max_mph=None), "The forecast maximum wind gust is 17 mph."),
            (dict(temp_low_f=None), "The forecast high is 52°F."),
            (dict(temp_low_f=-3), "The forecast high is 52°F and the low is -3°F."),
            (dict(hourly={"wind_speed_10m": {"2026-11-12T10:00": None}}),
             "For your 10:00 AM appointment, the hourly temperature estimate is 50°F."),
            (dict(precipitation_in=1.0), "The forecast precipitation total is 1 inch."),
            (dict(precipitation_in=0.0), "The forecast precipitation total is 0 inches."),
        ]
        for changes, sentence in cases:
            facts = make_facts(**changes)
            conditions = by_label(fallback.fallback_sections(facts))["Conditions"]
            with self.subTest(changes=changes):
                self.assertIn(sentence, conditions)
                self.assertEqual(validation.text_reasons(conditions, facts), [])

    def test_format_time_and_date(self):
        cases = {time(0, 15): "12:15 AM", time(9, 5): "9:05 AM", time(12, 0): "12:00 PM",
                 time(14, 30): "2:30 PM", time(23, 0): "11:00 PM"}
        for moment, text in cases.items():
            with self.subTest(moment=moment):
                self.assertEqual(fallback.format_time(moment), text)
        self.assertEqual(fallback.format_date(date(2026, 11, 25)), "Wed, Nov 25")
        self.assertEqual(fallback.format_date(date(2027, 3, 14)), "Sun, Mar 14")

    def test_fallback_rain_wording_distinguishes_peak_and_hour(self):
        conditions = by_label(fallback.fallback_sections(make_facts()))["Conditions"]
        self.assertIn(PEAK_SENTENCE, conditions)
        self.assertIn(HOUR_SENTENCE, conditions)
        sentences = re.split(r"(?<=[.!?])\s+", conditions)
        self.assertIn(PEAK_SENTENCE, sentences)
        self.assertIn(HOUR_SENTENCE, sentences)
        for facts in (make_facts(at=None),
                      make_facts(hourly={"precipitation_probability":
                                         {"2026-11-12T11:00": None}})):
            with self.subTest(time=facts.time, hour_value=facts.appt_rain_chance_pct):
                conditions = by_label(fallback.fallback_sections(facts))["Conditions"]
                self.assertIn(PEAK_SENTENCE, conditions)
                self.assertNotIn("the rain probability is", conditions)

    def test_fallback_afternoon_time_format(self):
        facts = make_facts(at=time(14, 30),
                           hourly={"precipitation_probability": {"2026-11-12T15:00": 35}})
        conditions = by_label(fallback.fallback_sections(facts))["Conditions"]
        self.assertIn("For the hour containing your 2:30 PM appointment, the rain "
                      "probability is 35%.", conditions)

    def test_hourly_estimates_keep_exact_and_half_hour_appointment_times(self):
        for at, label in ((time(10, 0), "10:00 AM"), (time(10, 30), "10:30 AM")):
            with self.subTest(time=at):
                facts = make_facts(at=at)
                conditions = by_label(fallback.fallback_sections(facts))["Conditions"]
                self.assertIn(f"For the hour containing your {label} appointment, "
                              "the rain probability is 20%.", conditions)
                self.assertIn(f"For your {label} appointment, the hourly temperature "
                              "estimate is 50°F and the hourly wind speed estimate is 10 mph.",
                              conditions)
                self.assertNotIn("hour starting", conditions)
                self.assertEqual(facts.time, at)

    def test_fallback_shows_known_concerns_when_rain_missing(self):
        facts = make_facts(peak_rain_chance_pct=None, wind_max_mph=35, temp_low_f=25)
        texts = by_label(fallback.fallback_sections(facts))
        self.assertNotIn("highest hourly rain", texts["Conditions"])
        self.assertIn("35 mph", texts["Conditions"])
        self.assertIn("25°F", texts["Conditions"])
        recommendation = texts["Recommendation"]
        self.assertIn(classify.CONCERN_PHRASES["wind"], recommendation)
        self.assertIn(classify.CONCERN_PHRASES["freezing"], recommendation)
        self.assertIn("peak hourly rain probability", recommendation)
        self.assertEqual(recommendation, python_recommendation(facts))

    def test_missing_hourly_values_use_estimate_and_containing_hour_wording(self):
        facts = make_facts(at=time(10, 30), hourly={
            "temperature_2m": {"2026-11-12T10:00": None},
            "wind_speed_10m": {"2026-11-12T10:00": None},
            "precipitation_probability": {"2026-11-12T11:00": None},
        })
        recommendation = by_label(fallback.fallback_sections(facts))["Recommendation"]
        self.assertIn("hourly temperature estimate for your appointment", recommendation)
        self.assertIn("hourly wind speed estimate for your appointment", recommendation)
        self.assertIn("rain probability for the hour containing your appointment", recommendation)
        self.assertNotIn("hour starting", recommendation)


class AiSectionTests(SimpleTestCase):
    def test_ai_sections_use_python_recommendation(self):
        facts = make_facts()
        clean, reasons = validation.validate_output(valid_output(facts), facts)
        self.assertEqual(reasons, [])
        sections = fallback.ai_sections(clean, facts)
        self.assertEqual([section["label"] for section in sections], LABELS)
        texts = by_label(sections)
        self.assertEqual(texts["Conditions"], clean["summary"])
        self.assertEqual(texts["For your service"], clean["service_explanation"])
        self.assertEqual(texts["Recommendation"], python_recommendation(facts))

    def test_empty_note_uses_python_confidence_sentence(self):
        facts = make_facts()
        clean, _ = validation.validate_output(valid_output(facts, uncertainty_note=""), facts)
        texts = by_label(fallback.ai_sections(clean, facts))
        self.assertEqual(texts["Forecast confidence"],
                         classify.confidence_sentence(facts.confidence, facts.lead_days))
        note = "The forecast could change before Thursday."
        clean, _ = validation.validate_output(valid_output(facts, uncertainty_note=note), facts)
        self.assertEqual(by_label(fallback.ai_sections(clean, facts))["Forecast confidence"],
                         note)


class ChooseSectionsTests(SimpleTestCase):
    def test_accepted_output_gives_ai_sections(self):
        facts = make_facts()
        sections, source, reasons = fallback.choose_sections(valid_output(facts), facts)
        self.assertEqual((source, reasons), ("ai", []))
        self.assertEqual(by_label(sections)["Conditions"], valid_output(facts)["summary"])

    def test_rejected_output_gives_fallback_and_hides_text(self):
        facts = make_facts()
        rejected = "Use a ceramic coating and cover the car; it will rain all day."
        for data in (valid_output(facts, service_explanation=rejected), None, "not json",
                     valid_output(facts, wind_level="very windy")):
            with self.subTest(data=data if not isinstance(data, dict) else "dict"):
                sections, source, reasons = fallback.choose_sections(data, facts)
                self.assertEqual(source, "fallback")
                self.assertTrue(reasons)
                self.assertEqual(sections, fallback.fallback_sections(facts))
                for section in sections:
                    self.assertNotIn("ceramic", section["text"])
                    self.assertNotIn(rejected, section["text"])
