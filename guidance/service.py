"""Weather guidance service: ties the stages together (plan Task 6, D6).

* ``get_forecast()`` fetches the forecast and builds the facts. It never calls the model.
* ``get_explanation()`` also asks the local model to explain the facts. The reply
  is shown only if ``validate_output`` accepts it. Otherwise the customer gets
  Python's fallback sections. The Recommendation section is always Python's.

Outcomes, with ``(status, source, fallback_reason)``:

* accepted model text:  ``available, ai, None``
* model unavailable:    ``available, fallback, ai_unavailable`` (no reply, timeout,
  HTTP error or unusable reply: any ``LLMUnavailable``)
* model text rejected:  ``available, fallback, ai_rejected``
* no forecast:          ``weather_unavailable`` or ``out_of_range`` with a fixed
  message and no sections, since there are no facts to explain.

Only accepted model fields are cached, for ``CACHE_SECONDS`` (30 min), under a key
hashed from the model name, ``llm.PROMPT_VERSION`` and every fact. Changing any of
them gives a new key, so older entries are never read again and simply expire.
Cached fields are validated again before use and the sections are rebuilt from the
current facts, so the Recommendation is recomputed by Python on every request.

Logs are INFO only: the outcome, the ``LLMUnavailable.kind``, the reason codes
and the latency. They never contain the facts, the prompt, model text or
exception text.
"""

import dataclasses
import hashlib
import json
import logging
import time as clock
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

from guidance import llm, weather
from guidance.facts import OutOfRange, WeatherFacts, build_facts
from guidance.fallback import ai_sections, fallback_sections, format_date
from guidance.validation import validate_output

logger = logging.getLogger(__name__)

CACHE_PREFIX = "guidance:ai:v1"
WEATHER_UNAVAILABLE_MESSAGE = "Forecast unavailable right now. You can still save your booking."
OUT_OF_RANGE_MESSAGE = "No forecast for this date yet. Forecasts are available through {}."


@dataclass
class GuidanceResult:
    status: str  # "available", "out_of_range" or "weather_unavailable"
    facts: WeatherFacts | None = None
    sections: list[dict] = field(default_factory=list)
    source: str | None = None  # "ai", "fallback", or None for a forecast only
    fallback_reason: str | None = None  # "ai_unavailable", "ai_rejected" or None
    message: str | None = None

    def to_json(self) -> dict:
        """The customer response. No reason codes, exception details or raw values."""
        return {
            "status": self.status,
            "facts": self.facts.as_public_dict() if self.facts is not None else None,
            "sections": self.sections,
            "source": self.source,
            "fallback_reason": self.fallback_reason,
            "message": self.message,
        }


def get_forecast(service, date, time=None) -> GuidanceResult:
    """The facts for the date (and time), without calling the model."""
    try:
        facts = build_facts(weather.fetch_forecast(), service, date, time)
    except weather.WeatherUnavailable:
        return GuidanceResult("weather_unavailable", message=WEATHER_UNAVAILABLE_MESSAGE)
    except OutOfRange as exc:
        message = OUT_OF_RANGE_MESSAGE.format(format_date(exc.last_forecast_date))
        return GuidanceResult("out_of_range", message=message)
    return GuidanceResult("available", facts)


def get_explanation(service, date, time=None) -> GuidanceResult:
    """The four customer sections: accepted model text, or Python's fallback."""
    result = get_forecast(service, date, time)
    if result.status != "available":
        return result
    facts = result.facts

    key = cache_key(facts)
    cached = cache.get(key)
    if cached is not None:
        clean, _ = validate_output(cached, facts)
        if clean is not None:
            logger.info("Guidance explanation: source=ai cache_hit")
            return _explained(facts, ai_sections(clean, facts), "ai")

    started = clock.monotonic()
    try:
        data = llm.request_explanation(facts)
    except llm.LLMUnavailable as exc:
        logger.info(
            "Guidance explanation: source=fallback fallback_reason=ai_unavailable "
            "kind=%s latency_ms=%d", exc.kind, _elapsed_ms(started),
        )
        return _explained(facts, fallback_sections(facts), "fallback", "ai_unavailable")
    latency_ms = _elapsed_ms(started)

    clean, reasons = validate_output(data, facts)
    if clean is None:
        logger.info(
            "Guidance explanation: source=fallback fallback_reason=ai_rejected "
            "reasons=%s latency_ms=%d", ",".join(reasons), latency_ms,
        )
        return _explained(facts, fallback_sections(facts), "fallback", "ai_rejected")

    cache.set(key, clean, settings.GUIDANCE["CACHE_SECONDS"])
    logger.info("Guidance explanation: source=ai latency_ms=%d", latency_ms)
    return _explained(facts, ai_sections(clean, facts), "ai")


def cache_key(facts) -> str:
    """``guidance:ai:v1:<sha256 of the model, PROMPT_VERSION and every fact>``.

    The facts hold no customer details, and the key holds only a digest of them.
    """
    identity = json.dumps(
        [settings.GUIDANCE["OLLAMA_MODEL"], llm.PROMPT_VERSION, dataclasses.asdict(facts)],
        sort_keys=True,
        default=str,
    )
    return f"{CACHE_PREFIX}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _explained(facts, sections, source, fallback_reason=None) -> GuidanceResult:
    return GuidanceResult("available", facts, sections, source, fallback_reason)


def _elapsed_ms(started: float) -> int:
    return round((clock.monotonic() - started) * 1000)
