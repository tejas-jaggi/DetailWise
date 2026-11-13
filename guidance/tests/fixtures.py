"""Test helpers: a valid Open-Meteo payload with known values, easy to modify.

Values are deterministic so tests can assert on them:

* daily, for the date at index ``i``: high ``50.0 + i``, low ``35.0 + i``,
  peak hourly rain probability ``10 + 5 * i``, precipitation ``0.01 * i``,
  wind ``8.0 + i``, gusts ``15.0 + i``;
* hourly, for clock hour ``h``: temperature ``40.0 + h``, rain probability ``h``,
  wind ``5.0 + h / 2``.

Every date has 24 hourly stamps, ``T00:00`` to ``T23:00``. That matches what
Open-Meteo returned for the 2026-11-01 fall-back day, with no duplicate stamp.
"""

import copy
from datetime import date, timedelta

DAILY_UNITS = {
    "time": "iso8601",
    "temperature_2m_max": "°F",
    "temperature_2m_min": "°F",
    "precipitation_probability_max": "%",
    "precipitation_sum": "inch",
    "wind_speed_10m_max": "mp/h",
    "wind_gusts_10m_max": "mp/h",
}

HOURLY_UNITS = {
    "time": "iso8601",
    "temperature_2m": "°F",
    "precipitation_probability": "%",
    "wind_speed_10m": "mp/h",
}


def forecast_payload(
    start=date(2026, 11, 10),
    days=16,
    *,
    daily=None,
    hourly=None,
    drop_dates=(),
    **top_level,
):
    """Return a valid forecast payload.

    * ``daily={"precipitation_probability_max": {"2026-11-12": None}}`` sets one daily value.
    * ``hourly={"precipitation_probability": {"2026-11-12T11:00": 20}}`` sets one hourly value.
    * ``drop_dates=("2026-11-18",)`` removes a date and its hourly stamps, leaving a gap.
    * Any other keyword replaces a top-level key, e.g. ``timezone="UTC"``.
    """
    dates = [start + timedelta(days=i) for i in range(days)]
    dropped = set(drop_dates)

    daily_block = {key: [] for key in DAILY_UNITS}
    hourly_block = {key: [] for key in HOURLY_UNITS}
    for i, day in enumerate(dates):
        iso = day.isoformat()
        if iso in dropped:
            continue
        daily_block["time"].append(iso)
        daily_block["temperature_2m_max"].append(50.0 + i)
        daily_block["temperature_2m_min"].append(35.0 + i)
        daily_block["precipitation_probability_max"].append(10 + 5 * i)
        daily_block["precipitation_sum"].append(round(0.01 * i, 2))
        daily_block["wind_speed_10m_max"].append(8.0 + i)
        daily_block["wind_gusts_10m_max"].append(15.0 + i)
        for hour in range(24):
            hourly_block["time"].append(f"{iso}T{hour:02d}:00")
            hourly_block["temperature_2m"].append(40.0 + hour)
            hourly_block["precipitation_probability"].append(hour)
            hourly_block["wind_speed_10m"].append(5.0 + hour / 2)

    _apply(daily_block, daily)
    _apply(hourly_block, hourly)

    payload = {
        "latitude": 40.11,
        "longitude": -88.21,
        "timezone": "America/Chicago",
        "timezone_abbreviation": "GMT-6",
        "daily_units": copy.deepcopy(DAILY_UNITS),
        "daily": daily_block,
        "hourly_units": copy.deepcopy(HOURLY_UNITS),
        "hourly": hourly_block,
    }
    payload.update(top_level)
    return payload


def _apply(block, changes):
    for key, by_stamp in (changes or {}).items():
        for stamp, value in by_stamp.items():
            block[key][block["time"].index(stamp)] = value
