"""Task 10 fixed-facts evaluation runner (protocol: docs/task10_evaluation.md).

Five fixed cases (A–E) are built as real ``WeatherFacts`` with the production
``build_facts()``, from a synthetic forecast payload and with "today" pinned to
``REFERENCE_NOW``. The facts are therefore identical on every run date and for
every prompt version, so prompt v1 and v2 can be compared on the same inputs.

Each case is sent once to ``llm.request_explanation()`` and checked with
``validate_output()``. Nothing here fetches a forecast, so weather-fetch
failures cannot occur or be counted.

Nothing in this module calls the model or the network when it is imported or
when the cases are built. Model calls happen only in ``run_case()`` /
``run_cases()``, which the ``guidance_evaluate`` command runs only with
``--live``.

Validator acceptance is **not** semantic accuracy: accepted replies still need
human review (the ``human_review`` field in the results file).
"""

import ctypes
import datetime as dt
import hashlib
import json
import statistics
import sys
import time as clock
from dataclasses import asdict, dataclass, field
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings

from bookings.models import Service
from bookings.timeutils import CENTRAL
from guidance import facts as facts_module
from guidance import llm
from guidance.schema import OUTPUT_FIELDS
from guidance.validation import clean_text, validate_output

# "Today" for every case: Monday, November 16, 2026, 09:00 Central Time.
REFERENCE_NOW = dt.datetime(2026, 11, 16, 9, 0, tzinfo=CENTRAL)
SERVICE_NAMES = {"exterior": "Exterior Wash", "interior": "Interior Clean", "mixed": "Full Detail"}
MAX_STORED_CHARS = 600
RESULTS_SCHEMA = "detailwise-task10-results-v1"
VERSION_TIMEOUT = 3

ACCEPTED, REJECTED = "accepted", "rejected"
TIMEOUT, MODEL_UNAVAILABLE, PARSE_FAILURE, NOT_RUN = (
    "timeout", "model_unavailable", "parse_failure", "not_run")
STATUSES = (ACCEPTED, REJECTED, TIMEOUT, MODEL_UNAVAILABLE, PARSE_FAILURE, NOT_RUN)
FULL_BASELINE, SUBSET = "full_baseline", "subset"
COMPLETE, INCOMPLETE = "complete", "incomplete"
SUBSET_LABEL = "diagnostic subset, not the five-case Task 10 baseline"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
# LLMUnavailable.kind -> result status.
KIND_STATUS = {"timeout": TIMEOUT, "unreachable": MODEL_UNAVAILABLE, "http": MODEL_UNAVAILABLE,
               "malformed": PARSE_FAILURE}


@dataclass(frozen=True)
class Case:
    """One fixed case. ``daily`` and ``hourly`` use WeatherFacts field names;
    a ``None`` value is deliberately missing."""

    case_id: str
    label: str
    sensitivity: str
    lead_days: int
    time: dt.time | None
    daily: dict
    hourly: dict = field(default_factory=dict)


def _daily(high, low, peak, precip, wind, gust):
    return {"temp_high_f": high, "temp_low_f": low, "peak_rain_chance_pct": peak,
            "precipitation_in": precip, "wind_max_mph": wind, "gust_max_mph": gust}


# The documented cases. Precipitation, gusts and the A/B appointment-hour
# temperature and wind complete the protocol (team-approved Nov 12, 2026); they
# change no class, concern or missing value.
CASES = (
    Case("A", "favorable exterior", "exterior", 1, dt.time(10, 0),
         _daily(72, 52, 10, 0.0, 8, 14),
         {"appt_temp_f": 60, "appt_wind_mph": 6, "appt_rain_chance_pct": 10}),
    Case("B", "two different rain values", "exterior", 1, dt.time(10, 0),
         _daily(68, 50, 70, 0.12, 8, 15),
         {"appt_temp_f": 56, "appt_wind_mph": 6, "appt_rain_chance_pct": 10}),
    Case("C", "interior with severe weather", "interior", 1, None,
         _daily(85, 65, 90, 0.35, 32, 41)),
    Case("D", "mixed service, missing facts", "mixed", 7, None,
         _daily(72, None, None, 0.0, 8, 14)),
    Case("E", "exterior with two concerns", "exterior", 7, None,
         _daily(45, 30, 20, 0.01, 22, 31)),
)
ALL_CASE_IDS = tuple(case.case_id for case in CASES)


# ---------------------------------------------------------------------------
# Building the fixed facts (no model, no network, no database)
# ---------------------------------------------------------------------------

def _payload(case: Case, day: dt.date) -> dict:
    """A one-day forecast payload in Open-Meteo's shape, keyed by the production
    field-to-key maps so no mapping is duplicated here."""
    iso = day.isoformat()
    daily = {"time": [iso]}
    for fact_field, key in facts_module.DAILY_FIELDS.items():
        daily[key] = [case.daily.get(fact_field)]
    hourly = {"time": [f"{iso}T{hour:02d}:00" for hour in range(24)]}
    for key, _ in facts_module.HOURLY_FIELDS.values():
        hourly[key] = [None] * 24
    if case.time is not None:
        for fact_field, (key, hours_after) in facts_module.HOURLY_FIELDS.items():
            hourly[key][case.time.hour + hours_after] = case.hourly.get(fact_field)
    return {"daily": daily, "hourly": hourly}


def build_case_facts(case: Case):
    """The case as real ``WeatherFacts``, with "today" pinned to ``REFERENCE_NOW``."""
    day = REFERENCE_NOW.date() + dt.timedelta(days=case.lead_days)
    service = Service(name=SERVICE_NAMES[case.sensitivity], weather_sensitivity=case.sensitivity)
    with mock.patch.object(facts_module, "central_now", return_value=REFERENCE_NOW):
        return facts_module.build_facts(_payload(case, day), service, day, case.time)


def build_all_cases(case_ids=None) -> dict:
    """``{case_id: WeatherFacts}`` in case order, optionally only ``case_ids``."""
    return {case.case_id: build_case_facts(case) for case in CASES
            if case_ids is None or case.case_id in case_ids}


def facts_fingerprint(facts) -> str:
    """SHA-256 of exactly what the model receives (the prompt facts JSON)."""
    payload = json.dumps(facts.as_prompt_dict(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Running cases (calls the model; only used by `guidance_evaluate --live`)
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    status: str
    failure_kind: str | None = None
    reason_codes: list = field(default_factory=list)
    latency_ms: int | None = None
    facts_sha256: str = ""
    model_output: dict | None = None
    human_review: dict | None = None  # filled in later by a reviewer


def sanitize_output(data) -> dict | None:
    """Only the schema's text/enum fields, as cleaned strings, length-capped."""
    if not isinstance(data, dict):
        return None
    return {name: clean_text(data[name])[:MAX_STORED_CHARS]
            for name in OUTPUT_FIELDS if isinstance(data.get(name), str)}


def run_case(case_id: str, facts) -> CaseResult:
    """One model call for one case, then the validator. Never raises for model errors."""
    fingerprint = facts_fingerprint(facts)
    started = clock.monotonic()
    try:
        data = llm.request_explanation(facts)
    except llm.LLMUnavailable as exc:
        elapsed = round((clock.monotonic() - started) * 1000)
        return CaseResult(case_id, KIND_STATUS[exc.kind], failure_kind=exc.kind,
                          latency_ms=elapsed, facts_sha256=fingerprint)
    elapsed = round((clock.monotonic() - started) * 1000)
    clean, reasons = validate_output(data, facts)
    if clean is not None:
        return CaseResult(case_id, ACCEPTED, latency_ms=elapsed, facts_sha256=fingerprint,
                          model_output=sanitize_output(clean))
    return CaseResult(case_id, REJECTED, reason_codes=list(reasons), latency_ms=elapsed,
                      facts_sha256=fingerprint, model_output=sanitize_output(data))


def run_cases(case_ids=None) -> list:
    """Run the cases in order. Stop rule: after a timeout, the rest are ``not_run``."""
    results, stopped = [], False
    for case_id, facts in build_all_cases(case_ids).items():
        if stopped:
            results.append(CaseResult(case_id, NOT_RUN, facts_sha256=facts_fingerprint(facts)))
            continue
        result = run_case(case_id, facts)
        results.append(result)
        stopped = result.status == TIMEOUT
    return results


def run_scope(case_ids) -> str:
    """``full_baseline`` only when exactly the five cases A–E were requested."""
    return FULL_BASELINE if sorted(case_ids) == sorted(ALL_CASE_IDS) else SUBSET


def summarize(results) -> dict:
    """Counts, run scope and state, rates where they mean something, model-call latency.

    The Task 10 rates (denominator five) appear only for a complete five-case run.
    A completed subset gets clearly labelled diagnostic statistics instead. An
    interrupted run (any ``not_run``) gets no rates at all.
    """
    requested = [r.case_id for r in results]
    counts = {status: sum(r.status == status for r in results) for status in STATUSES}
    scope = run_scope(requested)
    state = INCOMPLETE if counts[NOT_RUN] or not results else COMPLETE
    total = len(results)

    def rates():
        # Validator acceptance, not semantic accuracy.
        return {"cases": total,
                "validator_acceptance": round(counts[ACCEPTED] / total, 3),
                "fallback": round((total - counts[ACCEPTED]) / total, 3)}

    latencies = sorted(r.latency_ms for r in results
                       if r.latency_ms is not None and r.status != MODEL_UNAVAILABLE)
    return {
        "scope": scope,
        "run_state": state,
        "requested_case_ids": requested,
        "counts": counts,
        "task10_baseline": rates() if scope == FULL_BASELINE and state == COMPLETE else None,
        "subset_statistics": ({"label": SUBSET_LABEL, **rates()}
                              if scope == SUBSET and state == COMPLETE else None),
        "latency_ms": {"median": round(statistics.median(latencies)) if latencies else None,
                       "max": latencies[-1] if latencies else None, "n": len(latencies)},
    }


# ---------------------------------------------------------------------------
# Run metadata and results file
# ---------------------------------------------------------------------------

def available_memory_gb() -> float | None:
    """Available physical memory in GB, or None where it cannot be measured."""
    try:
        if sys.platform == "win32":
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullAvailPhys / 2**30, 2)
            return None
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 2**20, 2)
    except (OSError, ValueError, AttributeError):
        return None
    return None


def ollama_version() -> str | None:
    """The Ollama server version via ``GET /api/version`` (no model involved), or None."""
    base = settings.GUIDANCE["OLLAMA_BASE_URL"].rstrip("/")
    try:
        request = Request(f"{base}/api/version", headers={"Accept": "application/json"})
        with urlopen(request, timeout=VERSION_TIMEOUT) as response:
            version = json.loads(response.read(4096))["version"]
        return version if isinstance(version, str) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def endpoint_is_loopback() -> bool:
    """True when the configured Ollama endpoint is this machine."""
    host = urlsplit(settings.GUIDANCE["OLLAMA_BASE_URL"]).hostname or ""
    return host in LOOPBACK_HOSTS


def ollama_model_info(configured: str) -> dict | None:
    """The installed model a configured name resolves to, via ``GET /api/tags``.

    Read-only: lists installed models and loads nothing. A name without a tag
    resolves to ``:latest``, as Ollama does. None if not installed or unreachable.
    """
    wanted = configured if ":" in configured else f"{configured}:latest"
    base = settings.GUIDANCE["OLLAMA_BASE_URL"].rstrip("/")
    try:
        request = Request(f"{base}/api/tags", headers={"Accept": "application/json"})
        with urlopen(request, timeout=VERSION_TIMEOUT) as response:
            models = json.loads(response.read(1_000_000))["models"]
        entry = next((m for m in models if m.get("name") == wanted), None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if entry is None:
        return None
    details = entry.get("details") or {}
    return {"resolved_name": entry["name"], "digest": str(entry.get("digest", ""))[:12],
            "details": {key: details.get(key) for key in ("parameter_size", "quantization_level")}}


def run_metadata(version=None, *, free_before=None, model_info=None,
                 requested_case_ids=ALL_CASE_IDS) -> dict:
    """Everything needed to reproduce and compare a run. No secrets, hosts or paths.

    ``model_configured`` is the name in settings; ``model_resolved`` and
    ``model_digest`` are what Ollama reports it resolves to (they may differ,
    e.g. ``llama3`` -> ``llama3:latest``). ``free_memory_gb_after`` is filled in
    after the run (None if it could not be measured).
    """
    config = settings.GUIDANCE
    info = model_info or {}
    return {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "reference_today": REFERENCE_NOW.isoformat(),
        "requested_case_ids": list(requested_case_ids),
        "run_scope": run_scope(requested_case_ids),
        "prompt_version": llm.PROMPT_VERSION,
        "system_prompt_sha256": hashlib.sha256(llm.SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "model_configured": config["OLLAMA_MODEL"],
        "model_resolved": info.get("resolved_name"),
        "model_digest": info.get("digest"),
        "model_details": info.get("details"),
        "ollama_version": version if version is not None else ollama_version(),
        "options": dict(llm.OPTIONS),
        "keep_alive": llm.KEEP_ALIVE,
        "timeout_s": config["LLM_TIMEOUT"],
        "endpoint_is_loopback": endpoint_is_loopback(),
        "free_memory_gb_before": free_before,
        "free_memory_gb_after": None,
    }


def result_dict(result: CaseResult) -> dict:
    return asdict(result)


def write_results(results, metadata: dict, output_dir: Path) -> Path:
    """Write a new JSON results file; never overwrites an existing one."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromisoformat(metadata["timestamp_utc"]).strftime("%Y%m%dT%H%M%SZ")
    base = f"task10-{metadata['prompt_version']}-{stamp}"
    document = {
        "schema": RESULTS_SCHEMA,
        "note": ("Validator acceptance is not semantic accuracy. Fill in each case's "
                 "human_review after reading the model output."),
        "metadata": metadata,
        "summary": summarize(results),
        "cases": [result_dict(result) for result in results],
    }
    text = json.dumps(document, indent=2, ensure_ascii=False)
    for attempt in range(1, 100):
        path = output_dir / (f"{base}.json" if attempt == 1 else f"{base}-{attempt}.json")
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(text + "\n")
            return path
        except FileExistsError:
            continue
    raise FileExistsError(f"Too many result files named {base}")
