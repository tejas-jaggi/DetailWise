"""Deterministic weather classification and customer copy (plan D2, D3).

Python decides every class, the outlook and the recommendation. The local AI
model may only explain these results; it never decides them.

Rules:
- ``rain_level`` classifies the PEAK HOURLY rain probability of the date (the
  single most likely hour), never an all-day probability.
- Missing values are never replaced with defaults. An ``unknown`` class never
  adds or removes a concern, and every missing value is named in the copy.
- All customer copy is informational and non-directive. It is collected in the
  COPY TABLE section below and is flagged for team review in docs/ai_plan.md.
- Invalid inputs (booleans, non-finite or out-of-range numbers, unknown names,
  inconsistent combinations) raise ValueError; they are never classified. The
  facts builder (Task 3) turns invalid weather values into missing values first.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

RAIN_LEVELS = ("low", "possible", "likely", "very likely", "unknown")
WIND_LEVELS = ("light", "breezy", "windy", "very windy", "unknown")
TEMPERATURE_LEVELS = ("freezing risk", "cold", "mild", "warm", "unknown")
CONFIDENCE_LEVELS = ("higher", "moderate", "lower")
OUTLOOKS = ("favorable", "concerns", "incomplete", "weather_minor")
SENSITIVITIES = ("exterior", "interior", "mixed")  # bookings.Service.WeatherSensitivity

# ---------------------------------------------------------------------------
# COPY TABLE (for team review). Change wording here only.
# ---------------------------------------------------------------------------

SERVICE_CONSIDERATIONS = {
    "exterior": (
        "An exterior wash is done outside, so rain on the day of your appointment "
        "can make the car dirty again sooner."
    ),
    "interior": (
        "Interior cleaning happens inside the car, so the forecast matters less for "
        "this service."
    ),
    "mixed": (
        "This service includes exterior work, so rain on the day of your appointment "
        "can make the exterior dirty again sooner. Weather matters less for the "
        "interior work."
    ),
}

OUTLOOK_SENTENCES = {
    "favorable": (
        "No rain, wind or temperature concern stands out in the available forecast "
        "values for exterior work."
    ),
    "incomplete": (
        "The rain forecast for this date is not available, so this guidance is limited "
        "for exterior work."
    ),
    "weather_minor": (
        "This service happens inside the car, so the forecast is less important for it."
    ),
}
CONCERNS_LEAD = "Worth noting for exterior work: "
CONCERN_PHRASES = {
    "rain": "at least one hour of this date has a rain probability of 50% or higher",
    "wind": "the forecast maximum wind speed is 20 mph or higher",
    "freezing": "the forecast low is at or below 32°F",
}
MISSING_LEAD = "Not available in this forecast: "
MAY_CHANGE_SENTENCE = "The forecast may change before your appointment."
CLOSING_SENTENCE = "Your booking is not changed by this guidance. The choice is yours."

# Customer label for each fact value that can be missing (field names from WeatherFacts).
MISSING_LABELS = {
    "temp_high_f": "high temperature",
    "temp_low_f": "low temperature",
    "peak_rain_chance_pct": "peak hourly rain probability",
    "precipitation_in": "precipitation amount",
    "wind_max_mph": "wind speed",
    "gust_max_mph": "wind gust speed",
    "appt_temp_f": "temperature at your appointment time",
    "appt_wind_mph": "wind speed at your appointment time",
    "appt_rain_chance_pct": "rain probability for the hour starting at your appointment",
}

# Proposed wording from the Task 2 review, awaiting team editorial review.
CONFIDENCE_SENTENCES = {
    "higher": "Forecasts this close to the date can still change.",
    "moderate": "Forecasts several days ahead are less certain and may change.",
    "lower": "Forecasts farther ahead are less certain and may change.",
}

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _number(value, name: str):
    """Return value if it is a finite int or float (booleans are not numbers).

    Integers are always finite. Only floats go through math.isfinite(), which
    raises OverflowError for an integer too large to convert to a float.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return value


def _lead_days(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"lead_days must be a whole number of days, got {value!r}")
    if value < 0:
        raise ValueError("lead_days cannot be negative")
    return value


def _names(names, allowed, what: str) -> tuple[str, ...]:
    """Validate a tuple of names: each one known text, none repeated."""
    if not isinstance(names, tuple):
        raise ValueError(f"{what} names must be given as a tuple, got {names!r}")
    for name in names:
        if not isinstance(name, str) or name not in allowed:
            raise ValueError(f"unknown {what}: {name!r}")
    if len(set(names)) != len(names):
        raise ValueError(f"repeated {what} in {names!r}")
    return names


def round_half_up(value: float) -> int:
    """Round to a whole number, halves away from zero (19.5 -> 20, -0.5 -> -1).

    An integer is returned as it is. A float is rounded from its shortest repr;
    to_integral_value() does not depend on the 28-digit decimal precision, so
    huge floats such as 1e300 round without decimal.InvalidOperation.
    """
    value = _number(value, "value")
    if isinstance(value, int):
        return value
    return int(Decimal(repr(value)).to_integral_value(rounding=ROUND_HALF_UP))


def rain_level(pct: int | None) -> str:
    """Classify the peak hourly rain probability (%) of the date."""
    if pct is None:
        return "unknown"
    pct = _number(pct, "rain probability")
    if not 0 <= pct <= 100:
        # The value is not shown: Python cannot print an int over 4300 digits.
        raise ValueError("rain probability must be between 0 and 100")
    if pct < 20:
        return "low"
    if pct < 50:
        return "possible"
    if pct < 80:
        return "likely"
    return "very likely"


def wind_level(mph: int | None) -> str:
    """Classify the daily maximum sustained wind, rounded half-up to whole mph."""
    if mph is None:
        return "unknown"
    if _number(mph, "wind speed") < 0:
        # The value is not shown: Python cannot print an int over 4300 digits.
        raise ValueError("wind speed cannot be negative")
    mph = round_half_up(mph)
    if mph < 10:
        return "light"
    if mph < 20:
        return "breezy"
    if mph < 30:
        return "windy"
    return "very windy"


def temperature_level(low_f: int | None, high_f: int | None) -> str:
    for value, name in ((low_f, "low temperature"), (high_f, "high temperature")):
        if value is not None:
            _number(value, name)
    if low_f is None or high_f is None:
        return "unknown"
    if low_f <= 32:
        return "freezing risk"
    if high_f < 50:
        return "cold"
    if high_f < 80:
        return "mild"
    return "warm"


def confidence(lead_days: int) -> str:
    return _band(_lead_days(lead_days))


def _band(lead_days: int) -> str:
    """D2 confidence band for a validated lead in days."""
    if lead_days <= 2:
        return "higher"
    if lead_days <= 6:
        return "moderate"
    return "lower"


def _require(value, allowed, name):
    if value not in allowed:
        raise ValueError(f"unexpected {name}: {value!r}")


def concerns(rain: str, wind: str, temperature: str) -> tuple[str, ...]:
    """Known adverse conditions, ordered rain, wind, freezing. Unknown adds nothing."""
    _require(rain, RAIN_LEVELS, "rain level")
    _require(wind, WIND_LEVELS, "wind level")
    _require(temperature, TEMPERATURE_LEVELS, "temperature level")
    found = []
    if rain in ("likely", "very likely"):
        found.append("rain")
    if wind in ("windy", "very windy"):
        found.append("wind")
    if temperature == "freezing risk":
        found.append("freezing")
    return tuple(found)


def outlook(sensitivity: str, rain: str, wind: str, temperature: str) -> str:
    """Apply the D2 precedence; the first matching rule wins."""
    _require(sensitivity, SENSITIVITIES, "weather sensitivity")
    known = concerns(rain, wind, temperature)
    if sensitivity == "interior":
        return "weather_minor"
    if known:
        return "concerns"
    if rain == "unknown":
        return "incomplete"
    return "favorable"


# ---------------------------------------------------------------------------
# Copy assembly
# ---------------------------------------------------------------------------


def service_consideration(sensitivity: str) -> str:
    _require(sensitivity, SENSITIVITIES, "weather sensitivity")
    return SERVICE_CONSIDERATIONS[sensitivity]


def missing_sentence(missing: tuple[str, ...]) -> str:
    names = _names(missing, MISSING_LABELS, "missing field")
    if not names:
        return ""
    return MISSING_LEAD + ", ".join(MISSING_LABELS[name] for name in names) + "."


def confidence_sentence(confidence: str, lead_days: int) -> str:
    _require(confidence, CONFIDENCE_LEVELS, "confidence")
    lead_days = _lead_days(lead_days)
    expected = _band(lead_days)
    if confidence != expected:
        raise ValueError(
            f"confidence {confidence!r} does not match a lead of {lead_days} days "
            f"(expected {expected!r})"
        )
    if lead_days == 0:
        when = "Your appointment date is today."
    elif lead_days == 1:
        when = "Your appointment date is 1 day away."
    else:
        when = f"Your appointment date is {lead_days} days away."
    return f"{when} {CONFIDENCE_SENTENCES[confidence]}"


def recommendation(
    outlook: str, concerns: tuple[str, ...], missing: tuple[str, ...], confidence: str
) -> str:
    """Assemble the deterministic recommendation (plan Task 2 copy, in order).

    ``weather_minor`` (interior) may carry known concerns; they are validated but
    never shown as exterior-work notes.
    """
    _require(outlook, OUTLOOKS, "outlook")
    _require(confidence, CONFIDENCE_LEVELS, "confidence")
    concerns = _names(concerns, CONCERN_PHRASES, "concern")
    missing_text = missing_sentence(missing)
    if outlook == "concerns":
        if not concerns:
            raise ValueError("the concerns outlook needs at least one concern")
        parts = [CONCERNS_LEAD + "; ".join(CONCERN_PHRASES[c] for c in concerns) + "."]
    else:
        if outlook in ("favorable", "incomplete") and concerns:
            raise ValueError(f"the {outlook} outlook cannot have concerns")
        parts = [OUTLOOK_SENTENCES[outlook]]
    if missing_text:
        parts.append(missing_text)
    if confidence != "higher":
        parts.append(MAY_CHANGE_SENTENCE)
    parts.append(CLOSING_SENTENCE)
    return " ".join(parts)
