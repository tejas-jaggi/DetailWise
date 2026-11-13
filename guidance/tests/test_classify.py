"""Tests for the deterministic classification rules and customer copy (plan D2, D3).

Python decides every class, the outlook and the recommendation. These tests pin
the thresholds, the outlook precedence with missing data, and the exact copy
that is flagged for team review.
"""

import itertools
import re
from decimal import ROUND_HALF_UP, Decimal

from django.test import SimpleTestCase

from bookings.models import Service
from guidance import classify

RAIN_PHRASE = "at least one hour of this date has a rain probability of 50% or higher"
WIND_PHRASE = "the forecast maximum wind speed is 20 mph or higher"
FREEZING_PHRASE = "the forecast low is at or below 32°F"
CLOSING = "Your booking is not changed by this guidance. The choice is yours."
MAY_CHANGE = "The forecast may change before your appointment."

# Plan Task 2: words the deterministic copy never uses.
BANNED_WORDS = (
    "should", "must", "need to", "make sure", "reschedule", "cancel",
    "different date", "another day", "guarantee",
)
# Plan D5: unsupported-advice blocklist (also applied to Python copy).
ADVICE_BLOCKLIST = (
    "wax", "coating", "sealant", "ceramic", "polish", "cover", "tarp", "garage",
    "indoors", "umbrella", "apply", "spray", "make sure", "ensure", "you should",
    "we recommend", "reschedule", "cancel", "another day", "another date",
)
# Plan D5: all-day or continuous rain wording.
ALL_DAY_PHRASES = (
    "all day", "all-day", "throughout the day", "the whole day", "the entire day",
    "all morning", "all afternoon", "all evening", "continuous", "constant",
    "steady rain", "nonstop", "non-stop", "the chance of rain for the day",
    "daily chance of rain",
)
# Plan D5: certainty phrases.
CERTAINTY_PHRASES = (
    "guarantee", "definitely", "certainly", "for sure", "will not rain", "won't rain",
    "will stay dry", "no chance",
)
# Plan D5 uncertainty pattern, plus an optional "still" so the reviewed wording
# "can still change" counts as admitting change.
UNCERTAINTY_PATTERN = re.compile(
    r"\b(may|can|could|might)(?: still)? change\b|\buncertain\b|\bcheck again\b"
    r"|closer to your appointment",
    re.IGNORECASE,
)
# Values that are not usable numbers: booleans, non-finite floats, text, containers.
NOT_NUMBERS = (True, False, float("nan"), float("inf"), float("-inf"), "50", [50])
# Values that are not a single label: wrong type, containers, unhashable values.
MALFORMED_LABELS = (
    None, 1, 2.5, True, b"rain", object(), [], ["rain"], {}, {"rain": 1}, set(), ("rain",),
)
# Values that are not a tuple of names: wrong type, other containers, bad elements.
MALFORMED_NAME_TUPLES = (
    None, 1, 2.5, True, object(), "rain", b"rain", [], ["rain"], {}, {"rain": 1},
    {"rain"}, frozenset(), (["rain"],), ({"rain": 1},), ({"rain"},), (None,), (1,),
)
# Plan D2 lead-day bands for confidence.
CONFIDENCE_BANDS = {
    0: "higher", 1: "higher", 2: "higher", 3: "moderate", 4: "moderate", 5: "moderate",
    6: "moderate", 7: "lower", 8: "lower", 15: "lower", 30: "lower",
}

SENSITIVITIES = ("exterior", "interior", "mixed")
EXTERIOR_LIKE = ("exterior", "mixed")
MISSING_VARIANTS = ((), ("peak_rain_chance_pct",), tuple(classify.MISSING_LABELS))


def phrase_hits(text, phrases):
    """Phrases found in text, matched case-insensitively at word starts."""
    return [p for p in phrases if re.search(r"\b" + re.escape(p), text, re.IGNORECASE)]


def concern_subsets():
    """Every non-empty ordered subset of the concern names."""
    names = ("rain", "wind", "freezing")
    for size in range(1, 4):
        yield from itertools.combinations(names, size)


def every_recommendation():
    """(arguments, text) for every outlook x concerns x missing x confidence combination."""
    for outlook in classify.OUTLOOKS:
        if outlook == "concerns":
            subsets = list(concern_subsets())
        elif outlook == "weather_minor":
            subsets = [()] + list(concern_subsets())
        else:
            subsets = [()]
        for concerns, missing, level in itertools.product(
            subsets, MISSING_VARIANTS, classify.CONFIDENCE_LEVELS
        ):
            args = (outlook, concerns, missing, level)
            yield args, classify.recommendation(*args)


def all_customer_copy():
    """Every string the module can show a customer."""
    texts = [text for _, text in every_recommendation()]
    texts += [classify.service_consideration(s) for s in SENSITIVITIES]
    texts += [classify.confidence_sentence(level, lead) for level, lead in LEAD_CASES]
    texts += list(classify.MISSING_LABELS.values())
    return texts


LEAD_CASES = (
    ("higher", 0), ("higher", 1), ("higher", 2),
    ("moderate", 3), ("moderate", 6),
    ("lower", 7), ("lower", 15),
)


class ThresholdTests(SimpleTestCase):
    def test_rain_thresholds(self):
        cases = {
            None: "unknown", 0: "low", 19: "low", 20: "possible", 49: "possible",
            50: "likely", 79: "likely", 80: "very likely", 100: "very likely",
        }
        for pct, expected in cases.items():
            with self.subTest(pct=pct):
                self.assertEqual(classify.rain_level(pct), expected)

    def test_wind_thresholds_use_rounded_mph(self):
        cases = {
            None: "unknown", 0: "light", 9: "light", 10: "breezy", 19: "breezy",
            classify.round_half_up(19.5): "windy", 29: "windy", 30: "very windy", 45: "very windy",
        }
        for mph, expected in cases.items():
            with self.subTest(mph=mph):
                self.assertEqual(classify.wind_level(mph), expected)

    def test_wind_level_rounds_raw_values_half_up(self):
        self.assertEqual(classify.wind_level(19.4), "breezy")
        self.assertEqual(classify.wind_level(19.5), "windy")
        self.assertEqual(classify.wind_level(9.5), "breezy")
        self.assertEqual(classify.wind_level(29.5), "very windy")

    def test_temperature_levels(self):
        cases = [
            ((32, 45), "freezing risk"),
            ((30, 85), "freezing risk"),
            ((33, 49), "cold"),
            ((40, 50), "mild"),
            ((55, 79), "mild"),
            ((60, 80), "warm"),
            ((None, 60), "unknown"),
            ((40, None), "unknown"),
            ((None, None), "unknown"),
        ]
        for (low, high), expected in cases:
            with self.subTest(low=low, high=high):
                self.assertEqual(classify.temperature_level(low, high), expected)

    def test_confidence_bands(self):
        cases = {0: "higher", 2: "higher", 3: "moderate", 6: "moderate", 7: "lower", 15: "lower"}
        for lead, expected in cases.items():
            with self.subTest(lead=lead):
                self.assertEqual(classify.confidence(lead), expected)

    def test_negative_lead_days_rejected(self):
        with self.assertRaises(ValueError):
            classify.confidence(-1)

    def test_round_half_up(self):
        cases = {19.5: 20, 20.4: 20, -0.5: -1, 0.5: 1, 2.5: 3, 19.49: 19, 20: 20}
        for value, expected in cases.items():
            with self.subTest(value=value):
                result = classify.round_half_up(value)
                self.assertEqual(result, expected)
                self.assertIsInstance(result, int)

    def test_enum_tuples(self):
        self.assertEqual(
            classify.RAIN_LEVELS, ("low", "possible", "likely", "very likely", "unknown")
        )
        self.assertEqual(
            classify.WIND_LEVELS, ("light", "breezy", "windy", "very windy", "unknown")
        )
        self.assertEqual(
            classify.TEMPERATURE_LEVELS, ("freezing risk", "cold", "mild", "warm", "unknown")
        )
        self.assertEqual(classify.CONFIDENCE_LEVELS, ("higher", "moderate", "lower"))
        self.assertEqual(
            classify.OUTLOOKS, ("favorable", "concerns", "incomplete", "weather_minor")
        )


class ConcernAndOutlookTests(SimpleTestCase):
    def test_concerns_from_known_classes_only(self):
        self.assertEqual(classify.concerns("unknown", "unknown", "unknown"), ())
        self.assertEqual(classify.concerns("low", "light", "mild"), ())
        self.assertEqual(classify.concerns("possible", "breezy", "cold"), ())
        self.assertEqual(classify.concerns("likely", "unknown", "unknown"), ("rain",))
        self.assertEqual(classify.concerns("very likely", "light", "warm"), ("rain",))
        self.assertEqual(classify.concerns("unknown", "windy", "unknown"), ("wind",))
        self.assertEqual(classify.concerns("unknown", "very windy", "freezing risk"),
                         ("wind", "freezing"))
        self.assertEqual(classify.concerns("likely", "very windy", "freezing risk"),
                         ("rain", "wind", "freezing"))

    def test_unknown_class_never_adds_or_removes_a_concern(self):
        # Replacing any one known class with "unknown" removes exactly that class's
        # concern (if it had one) and leaves every other concern in place.
        dimension_concern = {0: "rain", 1: "wind", 2: "freezing"}
        known = (classify.RAIN_LEVELS[:-1], classify.WIND_LEVELS[:-1],
                 classify.TEMPERATURE_LEVELS[:-1])
        for combo in itertools.product(*known):
            full = classify.concerns(*combo)
            for index in range(3):
                partial = list(combo)
                partial[index] = "unknown"
                expected = tuple(c for c in full if c != dimension_concern[index])
                with self.subTest(combo=combo, unknown=index):
                    self.assertEqual(classify.concerns(*partial), expected)

    def test_outlook_precedence_matrix(self):
        rows = [
            # (rain, wind, temperature) -> exterior/mixed outlook, concerns
            (("unknown", "very windy", "freezing risk"), "concerns", ("wind", "freezing")),
            (("unknown", "windy", "unknown"), "concerns", ("wind",)),
            (("unknown", "unknown", "freezing risk"), "concerns", ("freezing",)),
            (("unknown", "light", "mild"), "incomplete", ()),
            (("unknown", "unknown", "unknown"), "incomplete", ()),
            (("likely", "very windy", "freezing risk"), "concerns", ("rain", "wind", "freezing")),
            (("very likely", "unknown", "unknown"), "concerns", ("rain",)),
            (("low", "unknown", "mild"), "favorable", ()),
            (("possible", "breezy", "cold"), "favorable", ()),
            (("low", "unknown", "unknown"), "favorable", ()),
            (("low", "light", "warm"), "favorable", ()),
        ]
        for classes, expected_outlook, expected_concerns in rows:
            self.assertEqual(classify.concerns(*classes), expected_concerns)
            for sensitivity in EXTERIOR_LIKE:
                with self.subTest(sensitivity=sensitivity, classes=classes):
                    self.assertEqual(classify.outlook(sensitivity, *classes), expected_outlook)
            with self.subTest(sensitivity="interior", classes=classes):
                self.assertEqual(classify.outlook("interior", *classes), "weather_minor")

    def test_outlook_precedence_over_every_combination(self):
        for rain, wind, temperature in itertools.product(
            classify.RAIN_LEVELS, classify.WIND_LEVELS, classify.TEMPERATURE_LEVELS
        ):
            known = classify.concerns(rain, wind, temperature)
            if known:
                expected = "concerns"
            elif rain == "unknown":
                expected = "incomplete"
            else:
                expected = "favorable"
            with self.subTest(rain=rain, wind=wind, temperature=temperature):
                self.assertEqual(classify.outlook("interior", rain, wind, temperature),
                                 "weather_minor")
                self.assertEqual(classify.outlook("exterior", rain, wind, temperature), expected)
                self.assertEqual(classify.outlook("mixed", rain, wind, temperature), expected)

    def test_no_default_substitution(self):
        # Missing rain is not treated as "low" (dry) or as "likely" (wet).
        unknown = classify.outlook("exterior", "unknown", "light", "mild")
        low = classify.outlook("exterior", "low", "light", "mild")
        likely = classify.outlook("exterior", "likely", "light", "mild")
        self.assertEqual((unknown, low, likely), ("incomplete", "favorable", "concerns"))
        self.assertNotEqual(classify.concerns("unknown", "light", "mild"),
                            classify.concerns("likely", "light", "mild"))
        # Missing wind or temperature is not treated as calm or mild either: a
        # favorable result still names what is missing (see the copy tests).
        self.assertEqual(classify.concerns("low", "unknown", "unknown"), ())

    def test_invalid_class_values_rejected(self):
        bad_calls = [
            lambda: classify.concerns("Likely", "light", "mild"),
            lambda: classify.concerns("low", "gale", "mild"),
            lambda: classify.concerns("low", "light", "hot"),
            lambda: classify.outlook("exterior", "", "light", "mild"),
            lambda: classify.outlook("outdoor", "low", "light", "mild"),
            lambda: classify.outlook(None, "low", "light", "mild"),
        ]
        for index, call in enumerate(bad_calls):
            with self.subTest(index=index), self.assertRaises(ValueError):
                call()

    def test_sensitivities_match_service_model(self):
        self.assertEqual(set(SENSITIVITIES), set(Service.WeatherSensitivity.values))


class ServiceConsiderationTests(SimpleTestCase):
    def test_exact_service_consideration_copy(self):
        self.assertEqual(
            classify.service_consideration("exterior"),
            "An exterior wash is done outside, so rain on the day of your appointment "
            "can make the car dirty again sooner.",
        )
        self.assertEqual(
            classify.service_consideration("interior"),
            "Interior cleaning happens inside the car, so the forecast matters less for "
            "this service.",
        )
        self.assertEqual(
            classify.service_consideration("mixed"),
            "This service includes exterior work, so rain on the day of your appointment "
            "can make the exterior dirty again sooner. Weather matters less for the "
            "interior work.",
        )

    def test_unknown_sensitivity_rejected(self):
        with self.assertRaises(ValueError):
            classify.service_consideration("outdoor")


class MissingSentenceTests(SimpleTestCase):
    def test_missing_labels_cover_every_fact_value(self):
        self.assertEqual(
            set(classify.MISSING_LABELS),
            {
                "temp_high_f", "temp_low_f", "peak_rain_chance_pct", "precipitation_in",
                "wind_max_mph", "gust_max_mph", "appt_temp_f", "appt_wind_mph",
                "appt_rain_chance_pct",
            },
        )
        self.assertEqual(classify.MISSING_LABELS["peak_rain_chance_pct"],
                         "peak hourly rain probability")
        self.assertEqual(classify.MISSING_LABELS["wind_max_mph"], "wind speed")
        self.assertEqual(classify.MISSING_LABELS["temp_low_f"], "low temperature")

    def test_missing_sentence(self):
        self.assertEqual(classify.missing_sentence(()), "")
        self.assertEqual(
            classify.missing_sentence(("peak_rain_chance_pct",)),
            "Not available in this forecast: peak hourly rain probability.",
        )
        self.assertEqual(
            classify.missing_sentence(("wind_max_mph", "temp_low_f")),
            "Not available in this forecast: wind speed, low temperature.",
        )

    def test_missing_sentence_for_every_outlook(self):
        missing = ("wind_max_mph", "temp_low_f")
        sentence = "Not available in this forecast: wind speed, low temperature."
        cases = [
            ("favorable", ()),
            ("concerns", ("rain",)),
            ("incomplete", ()),
            ("weather_minor", ()),
            ("weather_minor", ("wind",)),
        ]
        for outlook, concerns in cases:
            for level in classify.CONFIDENCE_LEVELS:
                with self.subTest(outlook=outlook, confidence=level):
                    with_missing = classify.recommendation(outlook, concerns, missing, level)
                    without = classify.recommendation(outlook, concerns, (), level)
                    self.assertIn(sentence, with_missing)
                    self.assertNotIn("Not available", without)


class RecommendationTests(SimpleTestCase):
    def test_exact_recommendation_per_outlook(self):
        self.assertEqual(
            classify.recommendation("favorable", (), (), "higher"),
            "No rain, wind or temperature concern stands out in the available forecast "
            "values for exterior work. " + CLOSING,
        )
        self.assertEqual(
            classify.recommendation("concerns", ("rain",), (), "higher"),
            f"Worth noting for exterior work: {RAIN_PHRASE}. " + CLOSING,
        )
        self.assertEqual(
            classify.recommendation("incomplete", (), ("peak_rain_chance_pct",), "higher"),
            "The rain forecast for this date is not available, so this guidance is limited "
            "for exterior work. Not available in this forecast: peak hourly rain "
            "probability. " + CLOSING,
        )
        self.assertEqual(
            classify.recommendation("weather_minor", (), (), "higher"),
            "This service happens inside the car, so the forecast is less important for "
            "it. " + CLOSING,
        )

    def test_concern_phrases_joined_in_order(self):
        self.assertEqual(
            classify.recommendation("concerns", ("rain", "wind", "freezing"), (), "higher"),
            f"Worth noting for exterior work: {RAIN_PHRASE}; {WIND_PHRASE}; "
            f"{FREEZING_PHRASE}. " + CLOSING,
        )

    def test_recommendation_lists_known_concerns_when_rain_missing(self):
        # Rain missing, wind 35 mph, low 25°F, 4 days ahead.
        rain = classify.rain_level(None)
        wind = classify.wind_level(35)
        temperature = classify.temperature_level(25, 40)
        found = classify.concerns(rain, wind, temperature)
        result = classify.outlook("exterior", rain, wind, temperature)
        text = classify.recommendation(result, found, ("peak_rain_chance_pct",),
                                       classify.confidence(4))
        self.assertEqual(result, "concerns")
        self.assertEqual(found, ("wind", "freezing"))
        self.assertEqual(
            text,
            f"Worth noting for exterior work: {WIND_PHRASE}; {FREEZING_PHRASE}. "
            "Not available in this forecast: peak hourly rain probability. "
            f"{MAY_CHANGE} {CLOSING}",
        )

    def test_interior_recommendation_does_not_list_concerns(self):
        text = classify.recommendation("weather_minor", ("rain", "wind"),
                                       ("temp_low_f",), "higher")
        self.assertEqual(
            text,
            "This service happens inside the car, so the forecast is less important for "
            "it. Not available in this forecast: low temperature. " + CLOSING,
        )

    def test_may_change_sentence_only_when_confidence_not_higher(self):
        for level in classify.CONFIDENCE_LEVELS:
            with self.subTest(confidence=level):
                text = classify.recommendation("favorable", (), (), level)
                if level == "higher":
                    self.assertNotIn(MAY_CHANGE, text)
                else:
                    self.assertIn(MAY_CHANGE, text)
                    self.assertTrue(text.endswith(f"{MAY_CHANGE} {CLOSING}"))

    def test_inconsistent_recommendation_arguments_rejected(self):
        bad_arguments = [
            # unknown outlook or confidence
            ("great", (), (), "higher"),
            ("favorable", (), (), "certain"),
            # "concerns" needs at least one valid concern, with no repeats
            ("concerns", (), (), "higher"),
            ("concerns", ("hail",), (), "higher"),
            ("concerns", ("rain", "hail"), (), "higher"),
            ("concerns", ("wind", "wind"), (), "higher"),
            ("concerns", "rain", (), "higher"),
            # "favorable" and "incomplete" carry no concerns
            ("favorable", ("rain",), (), "higher"),
            ("favorable", ("wind", "freezing"), (), "higher"),
            ("incomplete", ("wind",), ("peak_rain_chance_pct",), "higher"),
            # "weather_minor" may keep concerns, but only valid, distinct ones
            ("weather_minor", ("hail",), (), "higher"),
            ("weather_minor", ("rain", "rain"), (), "higher"),
            # missing keys must be known field names, with no repeats
            ("favorable", (), ("cloud_cover",), "higher"),
            ("favorable", (), ("temp_low_f", "temp_low_f"), "higher"),
            ("favorable", (), "temp_low_f", "higher"),
        ]
        for args in bad_arguments:
            with self.subTest(args=args), self.assertRaises(ValueError):
                classify.recommendation(*args)

    def test_weather_minor_keeps_concerns_without_showing_them(self):
        text = classify.recommendation("weather_minor", ("rain", "wind", "freezing"), (),
                                       "higher")
        self.assertNotIn("Worth noting for exterior work", text)
        for phrase in (RAIN_PHRASE, WIND_PHRASE, FREEZING_PHRASE):
            self.assertNotIn(phrase, text)

    def test_missing_sentence_rejects_unknown_or_duplicate_keys(self):
        for missing in (("cloud_cover",), ("wind_max_mph", "wind_max_mph"), "temp_low_f"):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                classify.missing_sentence(missing)

    def test_recommendation_copy_is_non_directive(self):
        count = 0
        for args, text in every_recommendation():
            count += 1
            with self.subTest(args=args):
                self.assertTrue(text.endswith("The choice is yours."))
                self.assertIn("Your booking is not changed by this guidance.", text)
                self.assertEqual(phrase_hits(text, BANNED_WORDS), [])
                self.assertEqual(phrase_hits(text, ADVICE_BLOCKLIST), [])
                self.assertEqual(phrase_hits(text, CERTAINTY_PHRASES), [])
        # 1 favorable + 7 concerns + 1 incomplete + 8 weather_minor subsets,
        # x 3 missing variants x 3 confidence levels.
        self.assertEqual(count, (1 + 7 + 1 + 8) * 3 * 3)

    def test_all_customer_copy_is_non_directive(self):
        for text in all_customer_copy():
            with self.subTest(text=text):
                self.assertEqual(phrase_hits(text, BANNED_WORDS), [])
                self.assertEqual(phrase_hits(text, ADVICE_BLOCKLIST), [])
                self.assertEqual(phrase_hits(text, CERTAINTY_PHRASES), [])

    def test_rain_copy_never_implies_all_day(self):
        for text in all_customer_copy():
            with self.subTest(text=text):
                self.assertEqual(phrase_hits(text, ALL_DAY_PHRASES), [])
        rain_text = classify.recommendation("concerns", ("rain",), (), "higher")
        self.assertIn("at least one hour", rain_text)
        self.assertIn("peak hourly", classify.MISSING_LABELS["peak_rain_chance_pct"])


class ConfidenceSentenceTests(SimpleTestCase):
    def test_confidence_sentence_states_lead_days(self):
        self.assertIn("today", classify.confidence_sentence("higher", 0))
        self.assertIn("1 day away", classify.confidence_sentence("higher", 1))
        self.assertIn("2 days away", classify.confidence_sentence("higher", 2))
        self.assertIn("15 days away", classify.confidence_sentence("lower", 15))

    def test_confidence_sentence_always_admits_change(self):
        for level, lead in LEAD_CASES:
            with self.subTest(confidence=level, lead=lead):
                text = classify.confidence_sentence(level, lead)
                # Every lead time admits the forecast can change; none claims certainty.
                self.assertRegex(text, UNCERTAINTY_PATTERN)
                self.assertEqual(phrase_hits(text, CERTAINTY_PHRASES), [])

    def test_confidence_sentence_differs_by_level(self):
        # Each label with a lead day from its own band; compare only the level
        # sentence that follows the lead phrase.
        level_sentences = {
            classify.confidence_sentence(level, lead).split(". ", 1)[1]
            for level, lead in (("higher", 2), ("moderate", 3), ("lower", 7))
        }
        self.assertEqual(len(level_sentences), 3)

    def test_confidence_sentence_requires_matching_band(self):
        for lead, band in CONFIDENCE_BANDS.items():
            self.assertEqual(classify.confidence(lead), band)
            for level in classify.CONFIDENCE_LEVELS:
                with self.subTest(confidence=level, lead=lead):
                    if level == band:
                        self.assertIn(classify.CONFIDENCE_SENTENCES[level],
                                      classify.confidence_sentence(level, lead))
                    else:
                        with self.assertRaisesRegex(ValueError, "lead"):
                            classify.confidence_sentence(level, lead)

    def test_unknown_confidence_rejected(self):
        with self.assertRaises(ValueError):
            classify.confidence_sentence("certain", 1)

    def test_exact_confidence_copy(self):
        self.assertEqual(
            classify.confidence_sentence("higher", 0),
            "Your appointment date is today. Forecasts this close to the date can still "
            "change.",
        )
        self.assertEqual(
            classify.confidence_sentence("moderate", 4),
            "Your appointment date is 4 days away. Forecasts several days ahead are less "
            "certain and may change.",
        )
        self.assertEqual(
            classify.confidence_sentence("lower", 10),
            "Your appointment date is 10 days away. Forecasts farther ahead are less "
            "certain and may change.",
        )

    def test_confidence_sentence_rejects_invalid_lead_days(self):
        for lead in (-1, -10, True, False, 2.0, 2.5, None, "3"):
            with self.subTest(lead=lead), self.assertRaises(ValueError):
                classify.confidence_sentence("higher", lead)


class InputSafeguardTests(SimpleTestCase):
    """Invalid inputs raise ValueError instead of being classified (no silent guesses)."""

    def test_confidence_rejects_booleans_and_non_integers(self):
        for lead in (True, False, 2.0, 3.5, float("nan"), None, "3"):
            with self.subTest(lead=lead), self.assertRaises(ValueError):
                classify.confidence(lead)

    def test_rain_level_rejects_out_of_range_and_non_numbers(self):
        for pct in (-1, -0.5, 100.5, 101, 250) + NOT_NUMBERS:
            with self.subTest(pct=pct), self.assertRaises(ValueError):
                classify.rain_level(pct)

    def test_rain_level_accepts_whole_range(self):
        self.assertEqual(classify.rain_level(0), "low")
        self.assertEqual(classify.rain_level(0.0), "low")
        self.assertEqual(classify.rain_level(100), "very likely")
        self.assertEqual(classify.rain_level(100.0), "very likely")

    def test_wind_level_rejects_negative_and_non_numbers(self):
        for mph in (-1, -0.6, -30) + NOT_NUMBERS:
            with self.subTest(mph=mph), self.assertRaises(ValueError):
                classify.wind_level(mph)

    def test_wind_level_accepts_zero(self):
        self.assertEqual(classify.wind_level(0), "light")
        self.assertEqual(classify.wind_level(0.0), "light")

    def test_temperature_level_rejects_non_numbers(self):
        for bad in NOT_NUMBERS:
            for low, high in ((bad, 60), (40, bad), (bad, None), (None, bad)):
                with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                    classify.temperature_level(low, high)

    def test_temperature_level_accepts_finite_values(self):
        self.assertEqual(classify.temperature_level(-10, 5), "freezing risk")
        self.assertEqual(classify.temperature_level(32.0, 45.5), "freezing risk")
        self.assertEqual(classify.temperature_level(60.5, 80.0), "warm")

    def test_round_half_up_rejects_non_numbers(self):
        for value in NOT_NUMBERS + (None,):
            with self.subTest(value=value), self.assertRaises(ValueError):
                classify.round_half_up(value)


class LargeNumberTests(SimpleTestCase):
    """Huge finite numbers are classified like any other number (no new upper limits)."""

    HUGE = 10 ** 400  # too large to convert to a float
    MAX_FLOAT = 1.7976931348623157e308

    # Labels, not values, in subTest: Python refuses to print an int over 4300 digits.
    HUGE_INTEGERS = {"10**400": HUGE, "-10**400": -HUGE, "10**400 + 1": HUGE + 1,
                     "10**5000": 10 ** 5000}

    def test_number_accepts_huge_integers(self):
        for label, value in self.HUGE_INTEGERS.items():
            with self.subTest(value=label):
                self.assertTrue(classify._number(value, "value") == value)

    def test_number_accepts_huge_finite_floats(self):
        for value in (1e300, -1e300, self.MAX_FLOAT, -self.MAX_FLOAT):
            with self.subTest(value=value):
                self.assertEqual(classify._number(value, "value"), value)

    def test_number_still_rejects_booleans_and_non_finite_floats(self):
        for value in (True, False, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite number"):
                classify._number(value, "value")

    def test_round_half_up_huge_integers_unchanged(self):
        for label, value in self.HUGE_INTEGERS.items():
            with self.subTest(value=label):
                result = classify.round_half_up(value)
                self.assertIs(type(result), int)
                self.assertTrue(result == value)  # assertEqual would print the 5001 digits

    def test_round_half_up_huge_floats(self):
        # Floats are rounded from their shortest repr, as before: 1e300 -> 10**300.
        cases = {
            1e28: 10 ** 28,
            -1e28: -(10 ** 28),
            1e300: 10 ** 300,
            -1e300: -(10 ** 300),
            self.MAX_FLOAT: 17976931348623157 * 10 ** 292,
            -self.MAX_FLOAT: -17976931348623157 * 10 ** 292,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                result = classify.round_half_up(value)
                self.assertEqual(result, expected)
                self.assertIsInstance(result, int)

    def test_round_half_up_halfway_values(self):
        cases = {
            0.5: 1, -0.5: -1, 1.5: 2, -1.5: -2, 2.5: 3, -2.5: -3, 19.5: 20, -19.5: -20,
            0.4: 0, -0.4: 0, 19.49: 19, -19.49: -19, 1000000000000000.5: 1000000000000001,
            -1000000000000000.5: -1000000000000001, 4503599627370495.5: 4503599627370496,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(classify.round_half_up(value), expected)

    def test_round_half_up_matches_previous_rule_for_ordinary_values(self):
        # The rule before this change: quantize the repr to whole units, halves up.
        def previous(value):
            return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        values = [i / 10 for i in range(-2000, 2001)] + [i / 100 for i in range(-500, 501)]
        values += list(range(-200, 201)) + [1e20, -1e20, 123456789.5, -123456789.5]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(classify.round_half_up(value), previous(value))

    def test_classes_for_huge_values(self):
        self.assertEqual(classify.wind_level(self.HUGE), "very windy")
        self.assertEqual(classify.wind_level(1e300), "very windy")
        self.assertEqual(classify.wind_level(self.MAX_FLOAT), "very windy")
        self.assertEqual(classify.temperature_level(self.HUGE, self.HUGE), "warm")
        self.assertEqual(classify.temperature_level(-self.HUGE, self.HUGE), "freezing risk")
        self.assertEqual(classify.temperature_level(1e300, 1e300), "warm")
        self.assertEqual(classify.temperature_level(-1e300, 50), "freezing risk")
        self.assertEqual(classify.temperature_level(40, -self.HUGE), "cold")

    def test_out_of_range_messages_do_not_print_the_value(self):
        # str() of an int over 4300 digits raises its own ValueError ("Exceeds the
        # limit ..."), which would replace the intended message.
        too_long = 10 ** 5000
        rain = r"^rain probability must be between 0 and 100$"
        wind = r"^wind speed cannot be negative$"
        cases = [
            ("rain 10**5000", rain, lambda: classify.rain_level(too_long)),
            ("rain -10**5000", rain, lambda: classify.rain_level(-too_long)),
            ("rain 150", rain, lambda: classify.rain_level(150)),
            ("rain -0.5", rain, lambda: classify.rain_level(-0.5)),
            ("wind -10**5000", wind, lambda: classify.wind_level(-too_long)),
            ("wind -3", wind, lambda: classify.wind_level(-3)),
        ]
        for label, message, call in cases:
            with self.subTest(case=label), self.assertRaisesRegex(ValueError, message):
                call()
        # Valid huge values are still accepted.
        self.assertEqual(classify.wind_level(too_long), "very windy")

    def test_huge_values_outside_existing_ranges_raise_value_error(self):
        calls = [
            lambda: classify.rain_level(self.HUGE),
            lambda: classify.rain_level(-self.HUGE),
            lambda: classify.rain_level(1e300),
            lambda: classify.wind_level(-self.HUGE),
            lambda: classify.wind_level(-1e300),
        ]
        for index, call in enumerate(calls):
            with self.subTest(index=index), self.assertRaises(ValueError):
                call()


class MalformedNameTests(SimpleTestCase):
    """Malformed labels and name tuples raise a clear ValueError, never TypeError."""

    def test_label_arguments_reject_malformed_values(self):
        calls = [
            ("rain level", lambda v: classify.concerns(v, "light", "mild")),
            ("wind level", lambda v: classify.concerns("low", v, "mild")),
            ("temperature level", lambda v: classify.concerns("low", "light", v)),
            ("weather sensitivity", lambda v: classify.outlook(v, "low", "light", "mild")),
            ("rain level", lambda v: classify.outlook("exterior", v, "light", "mild")),
            ("wind level", lambda v: classify.outlook("exterior", "low", v, "mild")),
            ("temperature level", lambda v: classify.outlook("exterior", "low", "light", v)),
            ("weather sensitivity", lambda v: classify.service_consideration(v)),
            ("confidence", lambda v: classify.confidence_sentence(v, 1)),
            ("outlook", lambda v: classify.recommendation(v, (), (), "higher")),
            ("confidence", lambda v: classify.recommendation("favorable", (), (), v)),
        ]
        for index, (name, call) in enumerate(calls):
            for value in MALFORMED_LABELS:
                with self.subTest(call=index, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        call(value)

    def test_name_tuples_reject_malformed_values(self):
        calls = [
            ("concern", lambda v: classify.recommendation("concerns", v, (), "higher")),
            ("concern", lambda v: classify.recommendation("weather_minor", v, (), "higher")),
            ("concern", lambda v: classify.recommendation("favorable", v, (), "higher")),
            ("missing field", lambda v: classify.missing_sentence(v)),
            ("missing field", lambda v: classify.recommendation("favorable", (), v, "higher")),
        ]
        for index, (name, call) in enumerate(calls):
            for value in MALFORMED_NAME_TUPLES:
                with self.subTest(call=index, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        call(value)

    def test_valid_name_tuples_still_accepted(self):
        self.assertEqual(classify.missing_sentence(()), "")
        self.assertIn(WIND_PHRASE,
                      classify.recommendation("concerns", ("wind",), ("temp_low_f",), "lower"))
