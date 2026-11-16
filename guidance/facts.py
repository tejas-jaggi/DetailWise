"""Exact-date weather facts for one service, date and optional time (plan D1, D2, D9).

``build_facts()`` is the only place raw forecast values enter the guidance code.

- The date must appear exactly in ``daily.time``; a neighbouring date is never used.
- Lead days use the Central date (``central_now``), never UTC.
- A value that is null, boolean, non-numeric, non-finite or out of range becomes
  ``None`` and its field name is listed in ``missing``. Invalid values never reach
  ``classify``, which raises ``ValueError`` on them.
- A daily low above the daily high makes both temperatures missing.
- Displayed values are rounded half-up to whole numbers (precipitation keeps its
  inches), and the classes are computed from those displayed values.
- Appointment temperature and wind use the H:00 stamp as hourly estimates;
  appointment rain probability uses the H+1:00 stamp, which covers H:00 to H+1:00,
  the hour containing an H:MM appointment. The appointment minutes are preserved.
"""

import math
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timedelta
from datetime import time as Time
from decimal import Decimal

from bookings.timeutils import central_now, is_nonexistent_central
from guidance import classify
from guidance.weather import WeatherUnavailable

# Fact field -> Open-Meteo daily key.
DAILY_FIELDS = {
    "temp_high_f": "temperature_2m_max",
    "temp_low_f": "temperature_2m_min",
    "peak_rain_chance_pct": "precipitation_probability_max",
    "precipitation_in": "precipitation_sum",
    "wind_max_mph": "wind_speed_10m_max",
    "gust_max_mph": "wind_gusts_10m_max",
}
# Fact field -> (Open-Meteo hourly key, hours after the appointment hour H).
HOURLY_FIELDS = {
    "appt_temp_f": ("temperature_2m", 0),
    "appt_wind_mph": ("wind_speed_10m", 0),
    "appt_rain_chance_pct": ("precipitation_probability", 1),
}
VALUE_FIELDS = tuple(DAILY_FIELDS) + tuple(HOURLY_FIELDS)
CORE_FIELDS = ("temp_high_f", "temp_low_f", "peak_rain_chance_pct", "wind_max_mph")
# Usable range per field: (lowest, highest); None means no limit beyond being finite.
RANGES = {
    "temp_high_f": (None, None),
    "temp_low_f": (None, None),
    "peak_rain_chance_pct": (0, 100),
    "precipitation_in": (0, None),
    "wind_max_mph": (0, None),
    "gust_max_mph": (0, None),
    "appt_temp_f": (None, None),
    "appt_wind_mph": (0, None),
    "appt_rain_chance_pct": (0, 100),
}
UNROUNDED_FIELDS = ("precipitation_in",)

# allowed_numbers() categories (plan D5).
NUMBER_CATEGORIES = {
    "rain_peak": ("peak_rain_chance_pct",),
    "rain_appointment": ("appt_rain_chance_pct",),
    "wind": ("wind_max_mph", "gust_max_mph", "appt_wind_mph"),
    "temperature": ("temp_high_f", "temp_low_f", "appt_temp_f"),
    "precipitation": ("precipitation_in",),
}

# as_prompt_dict() key for each value field: names carry the unit, and the two
# rain probabilities are named unambiguously (plan D4).
PROMPT_KEYS = {
    "temp_high_f": "high_temperature_f",
    "temp_low_f": "low_temperature_f",
    "peak_rain_chance_pct": "peak_hourly_rain_probability_pct",
    "precipitation_in": "precipitation_in",
    "wind_max_mph": "max_wind_mph",
    "gust_max_mph": "max_gust_mph",
    "appt_temp_f": "appointment_hour_temperature_f",
    "appt_wind_mph": "appointment_hour_wind_mph",
    "appt_rain_chance_pct": "appointment_hour_rain_probability_pct",
}
RAIN_PROBABILITY_NOTE = (
    "peak_hourly_rain_probability_pct is the highest chance of rain for any single hour "
    "of the date. It is not the chance of rain all day."
)


class OutOfRange(Exception):
    """The date is not in the forecast.

    ``within_range`` is True for a gap inside the forecast's dates and False for a
    date after (or before) them.
    """

    def __init__(self, last_forecast_date: Date, within_range: bool):
        super().__init__("No forecast for this date.")
        self.last_forecast_date = last_forecast_date
        self.within_range = within_range


@dataclass(frozen=True)
class WeatherFacts:
    service_name: str
    weather_sensitivity: str
    date: Date
    time: Time | None
    lead_days: int
    confidence: str
    temp_high_f: int | None
    temp_low_f: int | None
    peak_rain_chance_pct: int | None
    precipitation_in: float | None
    wind_max_mph: int | None
    gust_max_mph: int | None
    appt_temp_f: int | None
    appt_wind_mph: int | None
    appt_rain_chance_pct: int | None
    rain_level: str
    wind_level: str
    temperature_level: str
    concerns: tuple[str, ...]
    outlook: str
    service_consideration: str
    last_forecast_date: Date
    missing: tuple[str, ...]
    # The usable values before rounding, for allowed_numbers() only.
    raw_values: tuple[tuple[str, int | float], ...] = ()

    def allowed_numbers(self) -> dict[str, set[str]]:
        """Number tokens the explanation may use, per category (plan D5)."""
        raw = dict(self.raw_values)
        allowed = {}
        for category, fields in NUMBER_CATEGORIES.items():
            numbers = set()
            for field in fields:
                for value in (getattr(self, field), raw.get(field)):
                    if value is not None:
                        numbers |= _number_texts(value)
            allowed[category] = numbers
        allowed["calendar"] = self._calendar_numbers()
        allowed["all"] = set().union(*allowed.values())
        return allowed

    def _calendar_numbers(self) -> set[str]:
        day = self.date
        numbers = {
            str(day.year), str(day.month), f"{day.month:02d}", str(day.day), f"{day.day:02d}",
            str(self.lead_days),
        }
        if self.time is not None:
            hour, minute = self.time.hour, self.time.minute
            numbers |= {str(hour), f"{hour:02d}", str(hour % 12 or 12), str(minute),
                        f"{minute:02d}"}
        return numbers

    def as_prompt_dict(self) -> dict:
        """Facts for the model: JSON-ready, missing values left out (plan D4)."""
        facts = {
            "service_name": self.service_name,
            "weather_sensitivity": self.weather_sensitivity,
            "service_consideration": self.service_consideration,
            "date": self.date.isoformat(),
            "lead_days": self.lead_days,
        }
        if self.time is not None:
            facts["appointment_time"] = self.time.strftime("%H:%M")
        for field, key in PROMPT_KEYS.items():
            value = getattr(self, field)
            if value is not None:
                facts[key] = value
        facts["rain_probability_note"] = RAIN_PROBABILITY_NOTE
        facts.update(
            rain_level=self.rain_level,
            wind_level=self.wind_level,
            temperature_level=self.temperature_level,
            confidence=self.confidence,
            outlook=self.outlook,
            concerns=list(self.concerns),
            not_available=[classify.MISSING_LABELS[field] for field in self.missing],
        )
        return facts

    def as_public_dict(self) -> dict:
        """Facts for the customer JSON response: JSON-ready, no raw values."""
        public = {
            "service_name": self.service_name,
            "weather_sensitivity": self.weather_sensitivity,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M") if self.time is not None else None,
            "lead_days": self.lead_days,
            "confidence": self.confidence,
        }
        public.update({field: getattr(self, field) for field in VALUE_FIELDS})
        public.update(
            rain_level=self.rain_level,
            wind_level=self.wind_level,
            temperature_level=self.temperature_level,
            concerns=list(self.concerns),
            outlook=self.outlook,
            service_consideration=self.service_consideration,
            last_forecast_date=self.last_forecast_date.isoformat(),
            missing=list(self.missing),
        )
        return public


def build_facts(forecast: dict, service, date: Date, time: Time | None = None) -> WeatherFacts:
    """Build the facts for exactly ``date`` from a validated forecast payload.

    Raises ``OutOfRange`` if the date is not in ``daily.time`` and
    ``WeatherUnavailable`` if none of the four core values is usable.
    """
    lead_days = (date - central_now().date()).days
    if lead_days < 0:
        raise ValueError("the date is before today in Central Time")

    daily = forecast["daily"]
    dates = daily["time"]
    try:
        first, last = Date.fromisoformat(dates[0]), Date.fromisoformat(dates[-1])
    except (TypeError, ValueError):
        raise WeatherUnavailable("Forecast dates are not readable.") from None
    try:
        index = dates.index(date.isoformat())
    except ValueError:
        raise OutOfRange(last, within_range=first <= date <= last) from None

    raw = {field: _usable(daily[key][index], field) for field, key in DAILY_FIELDS.items()}
    low, high = raw["temp_low_f"], raw["temp_high_f"]
    if low is not None and high is not None and low > high:
        raw["temp_low_f"] = raw["temp_high_f"] = None
    if time is not None:
        raw.update(_hour_values(forecast["hourly"], date, time))
    if all(raw[field] is None for field in CORE_FIELDS):
        raise WeatherUnavailable("No usable forecast values for this date.")

    values = {field: _display(field, raw.get(field)) for field in VALUE_FIELDS}
    rain = classify.rain_level(values["peak_rain_chance_pct"])
    wind = classify.wind_level(values["wind_max_mph"])
    temperature = classify.temperature_level(values["temp_low_f"], values["temp_high_f"])
    sensitivity = service.weather_sensitivity
    return WeatherFacts(
        service_name=service.name,
        weather_sensitivity=sensitivity,
        date=date,
        time=time,
        lead_days=lead_days,
        confidence=classify.confidence(lead_days),
        **values,
        rain_level=rain,
        wind_level=wind,
        temperature_level=temperature,
        concerns=classify.concerns(rain, wind, temperature),
        outlook=classify.outlook(sensitivity, rain, wind, temperature),
        service_consideration=classify.service_consideration(sensitivity),
        last_forecast_date=last,
        # Fields that were looked up but are unusable. Without a time, the
        # appointment-hour fields are not looked up, so they are not missing.
        missing=tuple(f for f in VALUE_FIELDS if f in raw and raw[f] is None),
        raw_values=tuple((f, v) for f, v in raw.items() if v is not None),
    )


def _hour_values(hourly: dict, date: Date, time: Time) -> dict:
    """Appointment-hour values; a nonexistent time or a missing stamp gives None."""
    values = dict.fromkeys(HOURLY_FIELDS)
    if is_nonexistent_central(date, time):
        return values
    start = datetime.combine(date, Time(time.hour))  # naive wall-clock time
    stamps = hourly["time"]
    for field, (key, hours_after) in HOURLY_FIELDS.items():
        stamp = (start + timedelta(hours=hours_after)).strftime("%Y-%m-%dT%H:00")
        try:
            position = stamps.index(stamp)
        except ValueError:
            continue
        values[field] = _usable(hourly[key][position], field)
    return values


def _usable(value, field: str):
    """The value if it is a finite, in-range number; otherwise None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Integers are always finite; math.isfinite() raises OverflowError on huge ones.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    lowest, highest = RANGES[field]
    if (lowest is not None and value < lowest) or (highest is not None and value > highest):
        return None
    return value


def _display(field: str, value):
    if value is None or field in UNROUNDED_FIELDS:
        return value
    return classify.round_half_up(value)


def _number_texts(value) -> set[str]:
    """Plain decimal text for a number: 50.0 -> "50", 0.12 -> "0.12", -3 -> "-3".

    The sign is kept: the validator reads "-3" as one token, so "3" never stands
    for -3. Integers are converted exactly (normalize() would round them to 28 digits).
    """
    if isinstance(value, int):
        text = format(Decimal(value), "f")
    else:
        text = format(Decimal(repr(value)).normalize(), "f")
    return {text}
