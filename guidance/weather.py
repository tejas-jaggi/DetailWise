"""Open-Meteo forecast client for the fixed shop location (Urbana, IL).

``fetch_forecast()`` returns the raw forecast only after checking its time zone,
units, keys and array lengths. Any failure raises ``WeatherUnavailable``.
Valid responses are cached for 30 minutes; failures are never cached.
"""

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "guidance:forecast:v1"
MAX_RESPONSE_BYTES = 1_000_000

DAILY_UNITS = {
    "temperature_2m_max": "°F",
    "temperature_2m_min": "°F",
    "precipitation_probability_max": "%",
    "precipitation_sum": "inch",
    "wind_speed_10m_max": "mp/h",
    "wind_gusts_10m_max": "mp/h",
}
HOURLY_UNITS = {
    "temperature_2m": "°F",
    "precipitation_probability": "%",
    "wind_speed_10m": "mp/h",
}
DAILY_KEYS = tuple(DAILY_UNITS)
HOURLY_KEYS = tuple(HOURLY_UNITS)

FETCH_ERRORS = (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError)


class WeatherUnavailable(Exception):
    """The forecast could not be fetched or failed validation."""


def forecast_url() -> str:
    config = settings.GUIDANCE
    query = urlencode(
        {
            "latitude": config["LATITUDE"],
            "longitude": config["LONGITUDE"],
            "timezone": config["TIMEZONE"],
            "forecast_days": config["FORECAST_DAYS"],
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "daily": ",".join(DAILY_KEYS),
            "hourly": ",".join(HOURLY_KEYS),
        },
        safe=",",
    )
    return f"{config['FORECAST_URL']}?{query}"


def fetch_forecast() -> dict:
    """Return the validated forecast, from the cache when possible."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    config = settings.GUIDANCE
    try:
        with urlopen(forecast_url(), timeout=config["WEATHER_TIMEOUT"]) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        data = json.loads(body)
        _check_forecast(data, config["TIMEZONE"])
    except FETCH_ERRORS as exc:
        # Log the class name only: exception text can contain hosts or response content.
        logger.warning("Open-Meteo forecast unavailable: %s", type(exc).__name__)
        raise WeatherUnavailable("Forecast unavailable.") from None

    cache.set(CACHE_KEY, data, config["CACHE_SECONDS"])
    return data


def _check_forecast(data, timezone: str) -> None:
    if not isinstance(data, dict):
        raise TypeError("forecast is not an object")
    if data.get("timezone") != timezone:
        raise ValueError("unexpected time zone")
    _check_block(data, "daily", DAILY_UNITS)
    _check_block(data, "hourly", HOURLY_UNITS)


def _check_block(data: dict, name: str, expected_units: dict) -> None:
    units = data[f"{name}_units"]
    block = data[name]
    if not isinstance(units, dict) or not isinstance(block, dict):
        raise TypeError(f"{name} is not an object")

    times = block["time"]
    if not isinstance(times, list) or not times:
        raise ValueError(f"{name}.time is empty")
    if not all(isinstance(stamp, str) for stamp in times):
        raise TypeError(f"{name}.time has a non-string stamp")

    for key, unit in expected_units.items():
        if units[key] != unit:
            raise ValueError(f"unexpected unit for {name}.{key}")
        values = block[key]
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError(f"{name}.{key} does not match {name}.time")
