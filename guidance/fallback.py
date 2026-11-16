"""Customer sections: deterministic fallback text and accepted model text (plan D3, D4).

Every response has four sections in this order. The Recommendation always comes
from Python (``classify.recommendation``), whatever the model returned.
"""

from decimal import Decimal

from guidance import classify
from guidance.validation import validate_output

LABELS = ("Conditions", "For your service", "Forecast confidence", "Recommendation")
# Fixed English names, independent of the server locale.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fallback_sections(facts) -> list[dict]:
    """The deterministic sections, used whenever model output is unavailable or rejected."""
    return _sections(
        conditions_text(facts),
        facts.service_consideration,
        classify.confidence_sentence(facts.confidence, facts.lead_days),
        facts,
    )


def ai_sections(clean: dict, facts) -> list[dict]:
    """Sections from validated model fields; the Recommendation is still Python's."""
    confidence = clean["uncertainty_note"] or classify.confidence_sentence(
        facts.confidence, facts.lead_days
    )
    return _sections(clean["summary"], clean["service_explanation"], confidence, facts)


def choose_sections(data: object, facts) -> tuple[list[dict], str, list[str]]:
    """Validate model output; return ``(sections, "ai", [])`` or the fallback with reasons."""
    clean, reasons = validate_output(data, facts)
    if clean is None:
        return fallback_sections(facts), "fallback", reasons
    return ai_sections(clean, facts), "ai", []


def conditions_text(facts) -> str:
    """Every known value, in plain sentences; missing values are left out."""
    sentences = []
    if facts.peak_rain_chance_pct is not None:
        sentences.append(
            f"The highest hourly rain probability on {format_date(facts.date)} is "
            f"{facts.peak_rain_chance_pct}%."
        )
    if facts.appt_rain_chance_pct is not None:
        sentences.append(
            f"For the hour containing your {format_time(facts.time)} appointment, the rain "
            f"probability is {facts.appt_rain_chance_pct}%."
        )

    high, low = facts.temp_high_f, facts.temp_low_f
    if high is not None and low is not None:
        sentences.append(f"The forecast high is {high}°F and the low is {low}°F.")
    elif high is not None:
        sentences.append(f"The forecast high is {high}°F.")
    elif low is not None:
        sentences.append(f"The forecast low is {low}°F.")

    wind, gust = facts.wind_max_mph, facts.gust_max_mph
    if wind is not None and gust is not None:
        sentences.append(
            f"The forecast maximum wind speed is {wind} mph, with gusts up to {gust} mph."
        )
    elif wind is not None:
        sentences.append(f"The forecast maximum wind speed is {wind} mph.")
    elif gust is not None:
        sentences.append(f"The forecast maximum wind gust is {gust} mph.")

    if facts.precipitation_in is not None:
        unit = "inch" if facts.precipitation_in == 1 else "inches"
        sentences.append(
            f"The forecast precipitation total is {_decimal_text(facts.precipitation_in)} "
            f"{unit}."
        )

    if facts.time is not None:
        temperature, hour_wind = facts.appt_temp_f, facts.appt_wind_mph
        lead = f"For your {format_time(facts.time)} appointment, the hourly"
        if temperature is not None and hour_wind is not None:
            sentences.append(
                f"{lead} temperature estimate is {temperature}°F and the hourly wind speed "
                f"estimate is {hour_wind} mph."
            )
        elif temperature is not None:
            sentences.append(f"{lead} temperature estimate is {temperature}°F.")
        elif hour_wind is not None:
            sentences.append(f"{lead} wind speed estimate is {hour_wind} mph.")
    return " ".join(sentences)


def format_date(day) -> str:
    """Thu, Nov 12."""
    return f"{WEEKDAYS[day.weekday()]}, {MONTHS[day.month - 1]} {day.day}"


def format_time(moment) -> str:
    """10:00 AM, 2:30 PM."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _sections(conditions: str, service: str, confidence: str, facts) -> list[dict]:
    recommendation = classify.recommendation(
        facts.outlook, facts.concerns, facts.missing, facts.confidence
    )
    texts = (conditions, service, confidence, recommendation)
    return [{"label": label, "text": text} for label, text in zip(LABELS, texts)]


def _decimal_text(value) -> str:
    """The same plain text as WeatherFacts.allowed_numbers(): 0.0 -> "0", 0.02 -> "0.02"."""
    if isinstance(value, int):
        return str(value)
    return format(Decimal(repr(value)).normalize(), "f")
