"""``manage.py guidance_check``: a live check of the weather guidance pipeline (plan Task 9).

    python manage.py guidance_check --service exterior-wash --date 2026-11-14 [--time 10:00] [--runs 3]

It prints, in order:

* the forecast fetch time and whether the forecast cache was hit;
* the facts and classes for the service, date and time;
* whether the configured Ollama server is reachable and the configured model is
  installed (a read-only ``GET /api/tags``; nothing is ever downloaded);
* for each run, a real model call (the accepted-output cache is skipped), its
  latency and whether the validator accepted it, with reason codes if not;
* the customer sections from the last run (AI explanation or standard guidance).

It never prints the prompt, raw model output, URLs or exception text, and it makes
no database writes (it only reads the service).

Exit status: 0 every run accepted; 1 invalid input or no forecast; 2 the model was
unavailable or at least one run fell back to standard guidance.
"""

import json
import time as clock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from bookings.models import Service
from guidance import llm, service as guidance_service, weather
from guidance.fallback import ai_sections, fallback_sections, format_date, format_time
from guidance.forms import GuidanceRequestForm
from guidance.validation import validate_output

TAGS_TIMEOUT = 5
MAX_TAGS_BYTES = 1_000_000
MAX_RUNS = 10


def model_installed(model: str, names) -> bool:
    """True if ``model`` is in Ollama's list; a name without a tag means ``:latest``."""
    wanted = model if ":" in model else f"{model}:latest"
    return wanted in names


def ollama_models() -> list[str]:
    """Installed model names from ``GET /api/tags``, or ``LLMUnavailable``."""
    base_url = settings.GUIDANCE["OLLAMA_BASE_URL"].rstrip("/")
    try:
        request = Request(f"{base_url}/api/tags", headers={"Accept": "application/json"},
                          method="GET")
        with urlopen(request, timeout=TAGS_TIMEOUT) as response:
            body = response.read(MAX_TAGS_BYTES + 1)
    except HTTPError:
        raise llm.LLMUnavailable("http") from None
    except URLError as exc:
        kind = "timeout" if isinstance(exc.reason, TimeoutError) else "unreachable"
        raise llm.LLMUnavailable(kind) from None
    except TimeoutError:
        raise llm.LLMUnavailable("timeout") from None
    except (OSError, ValueError):
        raise llm.LLMUnavailable("unreachable") from None
    try:
        if len(body) > MAX_TAGS_BYTES:
            raise ValueError("model list too large")
        return [entry["name"] for entry in json.loads(body)["models"]]
    except (ValueError, KeyError, TypeError):
        raise llm.LLMUnavailable("malformed") from None


def _elapsed_ms(started: float) -> int:
    return round((clock.monotonic() - started) * 1000)


def _endpoint_kind() -> str:
    host = urlsplit(settings.GUIDANCE["OLLAMA_BASE_URL"]).hostname or ""
    return "this machine (loopback)" if host in ("127.0.0.1", "localhost", "::1") \
        else "another host"


class Command(BaseCommand):
    help = "Live check of the forecast, facts, Ollama model and validator for one booking."

    def add_arguments(self, parser):
        parser.add_argument("--service", required=True, help="Service slug, e.g. exterior-wash")
        parser.add_argument("--date", required=True, help="Appointment date, YYYY-MM-DD")
        parser.add_argument("--time", default="", help="Appointment time, HH:MM (optional)")
        parser.add_argument("--runs", type=int, default=1,
                            help=f"Model calls to make, 1 to {MAX_RUNS} (default 1)")

    def handle(self, *args, **options):
        runs = options["runs"]
        if not 1 <= runs <= MAX_RUNS:
            raise CommandError(f"--runs must be between 1 and {MAX_RUNS}.")
        selected = Service.objects.filter(slug=options["service"], is_active=True).first()
        if selected is None:
            raise CommandError(f"No active service with the slug {options['service']!r}.")
        form = GuidanceRequestForm({"service": selected.pk, "date": options["date"],
                                    "time": options["time"]})
        if not form.is_valid():
            messages = [m for errors in form.error_dict().values() for m in errors]
            raise CommandError(" ".join(messages))
        data = form.cleaned_data

        facts = self.check_forecast(data)
        sections, source = fallback_sections(facts), "Standard guidance"
        accepted = 0
        if self.check_ollama():
            config = settings.GUIDANCE
            self.stdout.write(f"Runs: {runs}, timeout {config['LLM_TIMEOUT']} s each, "
                              f"prompt {llm.PROMPT_VERSION} (accepted-output cache skipped)")
            for number in range(1, runs + 1):
                clean = self.run_once(number, facts)
                if clean is not None:
                    accepted += 1
                    sections, source = ai_sections(clean, facts), "AI explanation"
                else:
                    sections, source = fallback_sections(facts), "Standard guidance"
            self.stdout.write(f"Summary: {accepted} of {runs} runs accepted")

        self.stdout.write(f"\nCustomer sections ({source}), from the last run:")
        for section in sections:
            self.stdout.write(f"  {section['label']}: {section['text']}")
        if accepted < runs:
            raise CommandError("Customers would see standard guidance for at least one run.",
                               returncode=2)

    def check_forecast(self, data):
        hit = cache.get(weather.CACHE_KEY) is not None
        started = clock.monotonic()
        result = guidance_service.get_forecast(data["service"], data["date"], data["time"])
        elapsed = _elapsed_ms(started)
        config = settings.GUIDANCE
        self.stdout.write(f"Location: {config['LATITUDE']}, {config['LONGITUDE']} "
                          f"({config['TIMEZONE']})")
        if result.status == "weather_unavailable":
            self.stdout.write(f"Forecast: unavailable after {elapsed} ms")
            raise CommandError(result.message)
        self.stdout.write(f"Forecast: fetched in {elapsed} ms "
                          f"({'cache hit' if hit else 'cache miss'})")
        if result.status != "available":
            raise CommandError(result.message)

        facts = result.facts
        when = format_date(facts.date)
        if facts.time is not None:
            when += f" at {format_time(facts.time)}"
        self.stdout.write(f"\nService: {facts.service_name} ({facts.weather_sensitivity})")
        self.stdout.write(f"Date: {when}")
        self.stdout.write(f"Lead days: {facts.lead_days}")
        self.stdout.write(f"Confidence: {facts.confidence}")
        values = facts.as_prompt_dict()
        for key in ("high_temperature_f", "low_temperature_f",
                    "peak_hourly_rain_probability_pct",
                    "appointment_hour_rain_probability_pct", "max_wind_mph", "max_gust_mph",
                    "precipitation_in"):
            if key in values:
                self.stdout.write(f"  {key}: {values[key]}")
        self.stdout.write(f"Rain: {facts.rain_level}")
        self.stdout.write(f"Wind: {facts.wind_level}")
        self.stdout.write(f"Temperature: {facts.temperature_level}")
        self.stdout.write(f"Outlook: {facts.outlook}")
        self.stdout.write(f"Concerns: {', '.join(facts.concerns) or 'none'}")
        self.stdout.write(f"Missing: {', '.join(facts.missing) or 'none'}\n")
        return facts

    def check_ollama(self) -> bool:
        model = settings.GUIDANCE["OLLAMA_MODEL"]
        self.stdout.write(f"Ollama endpoint: {_endpoint_kind()}")
        started = clock.monotonic()
        try:
            names = ollama_models()
        except llm.LLMUnavailable as exc:
            self.stdout.write(f"Ollama: not reachable ({exc.kind}) after "
                              f"{_elapsed_ms(started)} ms. No model calls made.")
            return False
        self.stdout.write(f"Ollama: reachable in {_elapsed_ms(started)} ms")
        if not model_installed(model, names):
            self.stdout.write(f"Model {model}: not installed. Install it with "
                              f"`ollama pull {model}` (not run by this command). "
                              "No model calls made.")
            return False
        self.stdout.write(f"Model {model}: installed")
        return True

    def run_once(self, number: int, facts):
        """One real model call; the cleaned fields if accepted, else None."""
        started = clock.monotonic()
        try:
            data = llm.request_explanation(facts)
        except llm.LLMUnavailable as exc:
            self.stdout.write(f"Run {number}: unavailable ({exc.kind}) after "
                              f"{_elapsed_ms(started)} ms")
            return None
        elapsed = _elapsed_ms(started)
        clean, reasons = validate_output(data, facts)
        if clean is None:
            self.stdout.write(f"Run {number}: rejected in {elapsed} ms "
                              f"(reasons: {', '.join(reasons)})")
            return None
        self.stdout.write(f"Run {number}: accepted in {elapsed} ms")
        return clean

