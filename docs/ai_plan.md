# DetailWise AI: Weather Guidance

*INFO 490 Project 2, Team 3. This is the project's AI documentation (the
assignment's `README_AI.md` requirement). Last updated November 12, 2026.*

This document states what is **implemented and tested**, what was **measured
live**, and what is **planned next**. Mocked tests are never presented as real
model results.

## Contents

1. [Implemented](#1-implemented)
2. [Planned before the final submission](#2-planned-before-the-final-submission)
3. [Architecture and data flow](#3-architecture-and-data-flow)
4. [Model and configuration](#4-model-and-configuration)
5. [What the model sees, and what it does not](#5-what-the-model-sees-and-what-it-does-not)
6. [Classification rules](#6-classification-rules)
7. [Deterministic customer copy](#7-deterministic-customer-copy)
8. [Output schema and validation](#8-output-schema-and-validation)
9. [Fallback, caching and failure handling](#9-fallback-caching-and-failure-handling)
10. [Where the model must run (deployment)](#10-where-the-model-must-run-deployment)
11. [Limitations of rule-based validation](#11-limitations-of-rule-based-validation)
12. [Automated test evidence](#12-automated-test-evidence)
13. [Live experiment evidence](#13-live-experiment-evidence)
14. [Known limitations](#14-known-limitations)
15. [Future improvements](#15-future-improvements)

---

## 1. Implemented

On the booking page, a signed-in customer picks a service, date and optional
time. A **"Weather for your date"** panel beside the form:

1. shows the Open-Meteo forecast for that exact date (and hour, if a time is
   chosen) for the fixed shop in Urbana, IL;
2. on request (**Explain this forecast**), shows four sections:
   **Conditions**, **For your service**, **Forecast confidence** and
   **Recommendation**, labelled either **AI explanation** or **Standard guidance**.

The AI is part of the Django booking workflow, not a separate demo. It never
changes, blocks or saves a booking; the booking form works the same with or
without it.

| Stage | Module | What it does |
|---|---|---|
| Fetch | `guidance/weather.py` | Open-Meteo client: timeout 5 s, unit/time-zone checks, 30-min cache |
| Classify | `guidance/classify.py` | Threshold rules and all deterministic customer copy |
| Facts | `guidance/facts.py` | Exact-date and appointment-hour facts (Central Time, DST-aware) |
| Explain | `guidance/llm.py` | Ollama chat call with a JSON-schema-constrained reply |
| Validate | `guidance/validation.py` | Schema, number, unit and claim checks on the reply |
| Fallback | `guidance/fallback.py` | Deterministic sections; Python's recommendation always |
| Orchestrate | `guidance/service.py` | Ties the stages together; caches accepted replies |
| Serve | `guidance/views.py`, `forms.py` | Two customer-only JSON endpoints |
| Show | `templates/guidance/_weather_panel.html`, `static/js/guidance*.js` | Booking-page panel |
| Check | `guidance/management/commands/guidance_check.py` | Live check of the whole pipeline |
| Evaluate | `guidance/evaluation.py`, `guidance/management/commands/guidance_evaluate.py` | Task 10 fixed-facts runner (dry run by default; prompt v1 baseline run Nov 12) |

## 2. Planned before the final submission

- **Evaluation (Task 10):** five fixed cases, measurements and a stop rule are
  written in [`task10_evaluation.md`](task10_evaluation.md). The fixed-facts
  runner (`python manage.py guidance_evaluate`) is implemented and tested with
  mocked replies: it sends the same fixed facts to every prompt version
  (`guidance_check` cannot, because it uses the live forecast). The prompt v1
  baseline ran on November 12 (5 of 5 accepted by the validator; section 13).
  The independent human review is pending; two failure analyses are drafted
  and prompt v2 is proposed (not implemented); the v1/v2 comparison is
  planned.
- **Deployment** with a model reachable from the hosted app (section 10).
- **Rate limiting** of the explanation endpoint (section 14).

Further ideas beyond the final submission are listed in section 15.

## 3. Architecture and data flow

```
Customer's browser (booking page)
  │  GET  /guidance/forecast/?service=&date=&time=     (on every selection change)
  │  POST /guidance/explain/   service, date, time      (Explain button, CSRF)
  ▼
Django view: signed-in customer only; validates the three fields
  ▼
service.get_explanation()
  ├─ weather.fetch_forecast()      Open-Meteo, cached 30 min
  ├─ facts.build_facts()           Python computes every number and class
  ├─ cache check                   accepted replies only, re-validated before use
  ├─ llm.request_explanation()     server → Ollama /api/chat (JSON schema)
  ├─ validation.validate_output()  every field checked against the facts
  └─ fallback.ai_sections() or fallback.fallback_sections()
  ▼
JSON response → panel writes text with textContent (never as HTML)
```

Answers to the assignment's workflow questions (3.3):

| Question | Answer |
|---|---|
| What enters the AI system? | The prepared facts for one service, date and time (section 5). |
| How is it prepared? | Python fetches the forecast, picks the exact date and hour, rounds values, classifies them and builds the fact JSON. |
| Which model? | Llama 3 8B through Ollama (section 4). |
| How are results generated? | One `/api/chat` call with a fixed system prompt, the facts as the user message, `temperature 0` and a JSON schema in `format`. |
| How are results validated? | `validate_output()` (section 8). Valid JSON is never assumed correct. |
| How does the user receive it? | Four labelled sections in the booking-page panel. If the model fails or is rejected, the same four sections come from Python and are labelled "Standard guidance". |

**Why the model cannot fetch weather itself:** it has no tools, no browsing and
no network access through the app. Django calls Open-Meteo, computes the facts
and sends only those facts. The model is told they are its only source, and the
validator rejects any number not in the facts.

## 4. Model and configuration

| Item | Value |
|---|---|
| Runtime | Ollama (0.30.6 on the development laptop) |
| Model | `llama3` → `llama3:latest`, Llama 3 8B, Q4_0 quantization |
| Endpoint | `POST {OLLAMA_BASE_URL}/api/chat` |
| Options | `stream: false`, `temperature: 0`, `num_predict: 220`, `keep_alive: "30m"` |
| Structured output | `format` = the JSON schema in `guidance/schema.py` |
| Reply size cap | 64 KB |
| Prompt version | `v1` (`guidance/llm.py`, `PROMPT_VERSION`) |

Configuration (all optional; defaults shown), set in `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where **Django** reaches Ollama |
| `OLLAMA_MODEL` | `llama3` | Model name as Ollama knows it |
| `GUIDANCE_LLM_TIMEOUT` | `45` | Seconds Django waits for the model |

**Why this model and architecture:**

- **Cost and privacy:** a local open-weights model has no per-call fee and no
  API key, and no booking data leaves the machine that runs Django.
- **Task fit:** the model only rewrites known facts in plain language; an 8B
  model is enough for that, and Python keeps every decision.
- **Reliability:** Ollama's `format` option constrains the reply to the JSON
  schema, and the five class fields are restricted to fixed enums.
- **Trade-offs:** latency (13–23 s in the planning probe before the app was
  built; 11.1–18.2 s in the November 12 controlled runs; a 45 s timeout under
  memory pressure; section 13), one request at a time by default, and the model must
  run where Django can reach it (section 10). A hosted provider would be faster
  but adds cost, a key to protect and data sent to a third party; a comparison
  is planned (section 15).

## 5. What the model sees, and what it does not

The user message is exactly `WeatherFacts.as_prompt_dict()` as JSON:

- `service_name`, `weather_sensitivity` (exterior / interior / mixed),
  `service_consideration` (Python's sentence for that service);
- `date`, `lead_days`, and `appointment_time` when a time is chosen;
- the known forecast values, named with their units:
  `high_temperature_f`, `low_temperature_f`, `peak_hourly_rain_probability_pct`,
  `precipitation_in`, `max_wind_mph`, `max_gust_mph`,
  `appointment_hour_temperature_f`, `appointment_hour_wind_mph`,
  `appointment_hour_rain_probability_pct` (missing values are left out, never
  defaulted);
- `rain_probability_note`: "peak_hourly_rain_probability_pct is the highest
  chance of rain for any single hour of the date. It is not the chance of rain
  all day.";
- Python's classes: `rain_level`, `wind_level`, `temperature_level`,
  `confidence`, `outlook`, `concerns`, and `not_available`.

**Never sent:** the customer's name, username, email or ID, any booking ID or
price, cookies, IP address, or anything typed into a free-text field (the
booking form has none). The browser can only choose the service, date and time;
any other submitted field (a model name, URL, prompt or weather value) is ignored.

The system prompt (fixed, prompt v1) tells the model that the facts are its only
source of weather information; to copy the five class fields exactly; never to
write a number not in the facts; to write at most two short sentences per field
in plain customer language; to explain only the given `service_consideration`
with no products, techniques or instructions; to make no promises and never
suggest changing, moving or cancelling the booking; to say the forecast may
change when `lead_days` is 3 or more; and to call the peak value "the highest
hourly rain probability", never an all-day chance.

## 6. Classification rules

Python decides every class. The model copies them and never decides them.

| Class | Input | Rule |
|---|---|---|
| `rain_level` | **peak hourly** rain probability of the date (Open-Meteo `precipitation_probability_max`) | `low` <20 · `possible` 20–49 · `likely` 50–79 · `very likely` ≥80 · `unknown` if missing |
| `wind_level` | daily max sustained wind, rounded half-up | `light` <10 · `breezy` 10–19 · `windy` 20–29 · `very windy` ≥30 · `unknown` |
| `temperature_level` | daily low / high °F | `freezing risk` if low ≤32, else `cold` if high <50, else `mild` if high <80, else `warm` · `unknown` if either is missing |
| `confidence` | lead days (Central Time) | `higher` 0–2 · `moderate` 3–6 · `lower` 7+ |
| `concerns` | known classes only | `rain` if likely/very likely; `wind` if windy/very windy; `freezing` if freezing risk |

**Outlook precedence** (first match wins):

1. Interior service → `weather_minor`.
2. Exterior or mixed with at least one known concern → `concerns` (a missing
   value never hides a known concern).
3. Exterior or mixed, no concern, rain unknown → `incomplete`.
4. Exterior or mixed, no concern, rain known → `favorable`.

**Peak-hourly vs appointment-hour rain probability.** Open-Meteo's daily
`precipitation_probability_max` is the highest *single-hour* probability of the
date, not the chance of rain all day. The appointment-hour value is a separate
fact: Open-Meteo's hourly probability covers the *preceding* hour, so the hour
starting at H:MM uses the H+1:00 stamp. Temperature and wind are instantaneous
and use the H:00 stamp. The panel labels them "Highest hourly rain chance" and
"Rain chance, hour starting {time}"; it never shows a bare "Rain chance".

## 7. Deterministic customer copy

All customer copy that Python writes lives in one table in
`guidance/classify.py` (`COPY TABLE`). It is informational and non-directive,
never tells the customer to cancel or move a booking, and every recommendation
ends with "The choice is yours."

*Service considerations (the "For your service" section):*

| Sensitivity | Text |
|---|---|
| exterior | An exterior wash is done outside, so rain on the day of your appointment can make the car dirty again sooner. |
| interior | Interior cleaning happens inside the car, so the forecast matters less for this service. |
| mixed | This service includes exterior work, so rain on the day of your appointment can make the exterior dirty again sooner. Weather matters less for the interior work. |

*Recommendation building blocks, in the order they are joined:*

| Part | Text |
|---|---|
| Outlook `favorable` | No rain, wind or temperature concern stands out in the available forecast values for exterior work. |
| Outlook `incomplete` | The rain forecast for this date is not available, so this guidance is limited for exterior work. |
| Outlook `weather_minor` | This service happens inside the car, so the forecast is less important for it. |
| Outlook `concerns` | Worth noting for exterior work: *(concern phrases joined with "; ")*. |
| Concern `rain` | at least one hour of this date has a rain probability of 50% or higher |
| Concern `wind` | the forecast maximum wind speed is 20 mph or higher |
| Concern `freezing` | the forecast low is at or below 32°F |
| Missing values | Not available in this forecast: *(labels)*. |
| Lead ≥ 3 days | The forecast may change before your appointment. |
| Always last | Your booking is not changed by this guidance. The choice is yours. |

*Forecast confidence sentences* ("Your appointment date is N days away." plus):

| Confidence | Text |
|---|---|
| higher (0–2 days) | Forecasts this close to the date can still change. |
| moderate (3–6 days) | Forecasts several days ahead are less certain and may change. |
| lower (7+ days) | Forecasts farther ahead are less certain and may change. |

## 8. Output schema and validation

The model must return one JSON object with exactly these fields
(`additionalProperties: false`, all required):

| Field | Type | Rule |
|---|---|---|
| `rain_level`, `wind_level`, `temperature_level`, `confidence`, `outlook` | enum | must equal Python's facts |
| `summary` | string ≤280 | the Conditions section |
| `service_explanation` | string ≤280 | the For your service section |
| `uncertainty_note` | string ≤200 | required wording when lead ≥3; may be empty otherwise |

The Recommendation is **never** a model field. A reply containing an extra field
(for example `"recommendation"`) fails the schema check.

`validate_output()` returns the cleaned fields or a list of reason codes:

- **Schema:** exact keys, string types, enum membership, enums equal to the
  facts, length limits; control characters stripped, markup characters
  (`< > { }` and backtick) rejected.
- **Numbers:** every number in the prose must be one of the fact values (rounded
  or raw), the date's parts, lead days or the appointment's hour and minutes.
  Comma-grouped and scientific tokens are matched whole; negative signs are kept.
- **Units:** a number before `%` must be a rain value, before `mph` a wind
  value, before `°F` a temperature. Celsius in any spelling is rejected.
  Spelled-out numbers before a unit ("sixty percent") are rejected.
- **Rain scope:** all-day wording next to rain is rejected; a peak % must sit
  with a peak qualifier ("highest", "peak", …); an appointment-hour % must sit
  with an appointment qualifier; the peak value applied to the appointment hour
  is rejected.
- **Contradictions:** rain, wind and temperature words that contradict the
  classes; when rain is unknown, any claim that it will or will not rain, while
  neutral statements that the value is unavailable are allowed.
- **Certainty, advice and topic:** "guarantee", "definitely", "will stay dry";
  products and instructions (wax, coating, cover, reschedule, cancel, "you
  should", …); weather the facts do not contain (snow, storm, sunny, …); URLs,
  emails, prices.
- **Uncertainty:** when lead ≥3, `uncertainty_note` must say the forecast may
  change.

## 9. Fallback, caching and failure handling

| Situation | What the customer gets | Internal label |
|---|---|---|
| Reply accepted | Model text for 3 sections + Python recommendation, "AI explanation" | `source: ai` |
| Reply rejected by the validator | Python's 4 sections, "Standard guidance"; rejected text is never shown | `fallback_reason: ai_rejected` |
| Ollama unreachable, 404 model missing, timeout, malformed reply | Python's 4 sections, "Standard guidance" | `fallback_reason: ai_unavailable` |
| Open-Meteo down or unusable | "Forecast unavailable right now. You can still save your booking." | `status: weather_unavailable` |
| Date beyond the forecast | "No forecast for this date yet. Forecasts are available through {date}." | `status: out_of_range` |
| Browser waits more than 55 s | "The AI explanation took too long. You can still save your booking." | client timeout |

- **Caching:** only accepted replies are cached, for 30 minutes, under
  `guidance:ai:v1:<sha256 of model name + PROMPT_VERSION + every fact>`.
  Different services, dates, times or forecast values never share an entry.
  Cached fields are validated again before use, and the sections are rebuilt
  from the current facts, so the recommendation is always freshly computed.
- **Prompt changes:** bumping `PROMPT_VERSION` (or changing `OLLAMA_MODEL`)
  changes every key, so old replies are never reused; they expire within 30 min.
- **Logging:** INFO lines with the outcome, the failure kind, reason codes and
  latency. Logs never contain the facts, prompt, model text, exception text or
  customer details.
- **Customer safety:** responses never include prompts, stack traces,
  exception text, reason codes or rejected model text, and the panel writes all
  text with `textContent`.

## 10. Where the model must run (deployment)

The AI call is **server-side**. The browser talks only to Django; **Django**
calls Ollama at `OLLAMA_BASE_URL`. `127.0.0.1` therefore means the machine (or
container) running Django, never the customer's computer. Customers never need
Ollama.

| Setup | Does the AI work? |
|---|---|
| Django and Ollama on the same laptop | Yes |
| A teammate opens that laptop's app from another computer on the network | Yes; their computer needs nothing |
| Django on a host such as Render, Ollama only on someone's laptop | **No.** Render's `127.0.0.1` is the Render container. Customers get standard guidance. |
| Django on a server that also runs Ollama (or can reach a private Ollama) | Yes, for every customer |
| Ollama unavailable anywhere | Standard guidance from Python; bookings unaffected |

Hosting options for the final version (to be chosen before the final submission):

1. **One VM running Django and Ollama** (needs about 6 GB free RAM for the 8B
   model; a GPU makes it much faster). Simplest; the model port stays on
   `127.0.0.1`.
2. **Django on a PaaS + a private model server** reached over a private network
   or an authenticated reverse proxy. **Never expose Ollama's port to the
   internet without authentication.**
3. **A hosted inference provider** behind the same client interface. Faster and
   scalable, but adds per-call cost, an API key to protect, and sends the facts
   (no customer identity) to a third party.

Whichever option is chosen, the Django host needs HTTPS production settings.
`python manage.py check --deploy` (with `DJANGO_DEBUG=False`) currently reports
four: W004 (HSTS, `SECURE_HSTS_SECONDS`), W008 (`SECURE_SSL_REDIRECT`), W012
(`SESSION_COOKIE_SECURE`) and W016 (`CSRF_COOKIE_SECURE`). They are requirements
for a public HTTPS deployment, not faults in the local development app.

## 11. Limitations of rule-based validation

The validator catches **known classes** of error. It does **not** guarantee that
an accepted reply is semantically correct.

- **References across words or sentences:** "The chance of rain is unknown, but
  **it** is high." is accepted, because "it" refers back to the rain chance and
  the rules do not resolve pronouns.
- **Fluent but misleading text** that uses only allowed numbers and avoids every
  listed phrase can pass.
- **Phrase lists** give both false positives (harmless wording rejected, so the
  customer sees standard guidance) and false negatives. Task 10 will measure how
  often each happens; it will not eliminate them.
- Some neutral wording is rejected on purpose because it is close to a claim,
  for example "Today's chance of rain is not available." This fails safe.

## 12. Automated test evidence

All automated tests mock the network and the model; **none of them is a real
model result.**

| Suite | Result (Nov 12, 2026) |
|---|---|
| Full Django suite (`python manage.py test`) | 464 tests, OK |
| Weather guidance app (`python manage.py test guidance`) | 362 tests, OK |
| JavaScript state logic (`node --test "guidance/tests/js/*.test.mjs"`) | 29 tests, OK |
| `manage.py check`, `makemigrations --check`, `migrate --check` | clean |

Mutation checks (deliberately breaking the code and confirming a test fails)
were run on the validator, client, service, endpoints, panel logic and the live
check; every surviving mutant was either fixed with a new test or shown to be
redundant code and removed.

**Browser check (simulated model):** on a disposable copy with a local stand-in
for Open-Meteo and Ollama, the panel showed the forecast, an accepted
explanation, standard guidance for a rejected and for a failed model reply, the
out-of-range message, no stale result after a date change mid-request, a cached
repeat in 52 ms, a usable 390 px mobile layout, keyboard access, and a booking
saved with the panel active. On Nov 12 the same kind of check (again with a
simulated model) covered the approved visual design at 1280 px and 390 px:
AI-labelled and standard-guidance results, sign-in, booking save, My Bookings
and booking detail, with no horizontal overflow. This proves the plumbing and
the UI, **not** the real model's quality.

## 13. Live experiment evidence

| When | What | Result |
|---|---|---|
| Nov 10, planning probe (before implementation) | Ollama structured output, 2 runs | Enum fields matched the facts in 2 of 2 runs. 23.0 s cold (9.0 s load), 13.1 s warm. **Both runs invented service advice** ("cover sensitive exterior components", "use a water-repellent coating"), which is why the recommendation is Python-only and advice words are rejected. |
| Nov 10, earlier text-only probe | Free-text explanation | 16.1 s cold, 7.3 s warm; described 19.5 mph wind as a "gentle breeze" and did not mention uncertainty. |
| Nov 12, `guidance_check` (one controlled call) | Real Open-Meteo + local Ollama, Exterior Wash, Sat Nov 14, 10:00 | Forecast fetched in 454 ms. Ollama reachable in 11 ms; `llama3` installed. **The model call timed out after 45 s**, and standard guidance was shown (exit status 2). At the time only 0.4 GB of 15.8 GB RAM was free and the 5.3 GB model ran 56% on CPU / 44% on a 4 GB GPU. |
| Nov 12 (later), direct Ollama call | One short prompt sent straight to Ollama 0.30.6 (`llama3:latest`, 8B, Q4_0), cold start | About 6.79 GB of 15.77 GB RAM free before loading. Valid reply in 13.9 s (10.7 s model load, then 13.4 tokens/s). The loaded model (4.98 GB) ran about 44% on the GPU and 56% on the CPU. |
| Nov 12 (later), `guidance_check --runs 1` | Same inputs as the timeout (Exterior Wash, Sat Nov 14, 10:00), run on a disposable project copy (fresh migrations, default settings, throwaway secret key), model already loaded | Real forecast in 1,571 ms. **The reply was accepted by the validator in about 11.3 s; no fallback**; 13.7 s in total, exit status 0. Conditions and For your service were written by the model; Forecast confidence (Python's sentence, since the date was under 3 days away) and Recommendation came from Python. |

**First successful controlled application-level AI smoke test completed on
November 12, 2026.** What it does not show: a live AI explanation in the browser
on the booking page, reliability over many runs, or performance under
concurrent use. The timeout and the success differed in free memory (about
0.4 GB versus 6.8 GB) with the same GPU/CPU split, so insufficient memory is a
plausible contributor to the timeout; this is a hypothesis, not a proven cause.

**Task 10 prompt v1 baseline, November 12, 2026 (evening).** One complete run
of the five fixed cases (`guidance_evaluate --live`; `llama3:latest`, digest
`365c0bd3c000`, Ollama 0.30.6, prompt v1, 6.92 GB free before): **5 of 5
replies accepted by the validator, 0 of 5 fallbacks**; latencies 18.2 s (first
call, including loading the model), then 11.1–11.7 s; median 11.4 s. This is
one five-case course-project baseline, not a population estimate, and
validator acceptance is not accuracy. An AI-assisted preliminary review (not
a human review) found possible content problems the validator does not catch:
case B leaves out the appointment-hour rain probability, case C's uncertainty
note is commentary about itself, and case D's summary is incoherent. The
independent human review is pending
([review packet](task10_v1_review_packet.md)). The proposed prompt v2 targets
case B only and is not implemented. Details:
[`task10_evaluation.md`](task10_evaluation.md).

## 14. Known limitations

1. **Validation** is rule-based (section 11). The v1 baseline (section 13)
   includes accepted replies with possible content problems that the rules do
   not detect, so human review remains necessary.
2. **Latency and memory:** 13–23 s per explanation in the planning probe
   (before the app was built); a timeout at 45 s on Nov 12 under memory
   pressure; 11.3 s for one accepted app call
   later that day with the model already loaded (loading it took 10.7 s); in the
   v1 baseline, 18.2 s for the first call (including loading) and 11.1–11.7 s
   after it. The 8B model needs about 5–6 GB of
   memory, and a 4 GB GPU cannot hold it whole.
3. **Throughput:** Ollama answers one request at a time by default, so
   simultaneous customers queue. Each explanation holds a synchronous Django
   worker for up to 45 s.
4. **Rate limiting (planned):** a signed-in customer can currently trigger many model calls. Each
   new service, date or time is a new call, and so is any repeat whose earlier
   reply was rejected or failed (only accepted replies are cached). Recommended
   before public deployment:
   - a per-customer limit in Django using the existing cache (for example one
     explanation in progress and at most 10 per 10 minutes per user), with no
     new dependency;
   - a request limit at the reverse proxy (for example nginx `limit_req`);
   - at larger scale, a job queue so web workers are not held by the model.
5. **Cache scope:** the cache is per Django process (`LocMemCache`); separate
   processes do not share it.
6. **Deployment:** the AI works only where Django can reach a running model
   (section 10). Without it, every customer gets standard guidance.
7. **Reply length:** `num_predict: 220` could cut off a very long but valid reply
   (estimated worst case about 240–260 tokens). That fails safe as `malformed`,
   then standard guidance. Task 10 should record how often it happens.
8. **Forecast data:** forecasts 7–15 days out are low-confidence by design.
   Open-Meteo gives one "01:00" on the fall-back day, so that hour is ambiguous.
   A spring-forward time that does not exist gets daily values only.

## 15. Future improvements

- **Prompt v2, measured:** the v1 baseline had no validator rejections, so v2
  targets a human-reviewed content problem instead: stating the highest hourly
  and appointment-hour rain probabilities separately (case B). A later version
  could forbid commentary about empty fields (case C). One change per version,
  compared on the same five fixed cases ([`task10_evaluation.md`](task10_evaluation.md)).
- **Validation-failure retry** as a before/after experiment.
- **Streaming** so the customer sees progress sooner.
- **Hosted-provider comparison** (latency, cost, privacy) behind the same
  `request_explanation()` interface.
