# Task 10: AI Evaluation Protocol

*Prepared November 12, 2026; prompt v1 baseline results added the same
evening. This is the plan for evaluating the AI weather explanation and the
record of its results.*

## Status

| Item | Status |
|---|---|
| Case matrix and measurement rules | Ready (this document) |
| Fixed-facts evaluation runner | **Implemented**: `python manage.py guidance_evaluate` (dry run by default; covered by mocked automated tests). See "Running the evaluation" |
| Live evaluation run (prompt v1 baseline) | **Completed** November 12, 2026: one complete five-case run. See "Prompt v1 baseline" |
| Measured acceptance and fallback rates (v1) | Validator acceptance 5 of 5; fallback 0 of 5 (one five-case baseline; not accuracy) |
| AI-assisted preliminary review of the v1 replies | Done; findings below (not a human review) |
| Independent human review of the v1 replies | **Pending**; materials in [`task10_v1_review_packet.md`](task10_v1_review_packet.md) |
| Failure analyses | Two drafted (cases B and C), preliminary until the human review |
| Prompt v2 | **Proposed only** (targets case B); not implemented, not run |
| Prompt v2 comparison | Planned, after the human review; **no comparison exists yet** |

One controlled application smoke test succeeded on November 12 (see "Earlier
observations" below). It is not a Task 10 result; the Task 10 v1 baseline is
reported under "Prompt v1 baseline" below.

**Run requirements:** Ollama running on the machine that hosts Django, with
`llama3:latest` (4.7 GB) installed and about 5–6 GB of free memory for the 8B
model.

### Earlier observations (not Task 10 results)

- **Planning probes, Nov 10 (2 real model calls, before the app was built):**
  the class fields matched the facts in both; both replies invented product
  advice. See [`ai_plan.md` §13](ai_plan.md#13-live-experiment-evidence).
- **First application call, Nov 12 (`guidance_check`):** the real model call
  timed out after 45 seconds, with about 0.4 GB of RAM free, and the app showed
  standard guidance. One timeout is a failure observation, not a rate.
- **Direct call and application smoke test, Nov 12 (later):** with about 6.8 GB
  of RAM free, a direct cold Ollama call returned a valid reply in 13.9 s, and
  one `guidance_check` run (Exterior Wash, Nov 14, 10:00, on a disposable
  project copy) was accepted by the validator in about 11.3 s with no fallback.
  One success is an observation, not a rate.
- **Automated tests** use mocked model replies. They prove the application
  handles every outcome correctly; they say nothing about model quality or
  acceptance rates.

## Fixed case matrix

Use exactly the same facts for prompt v1 and any candidate v2. These are
controlled inputs, not live forecasts.

| Case | Service and facts | What to check |
|---|---|---|
| A: favorable exterior | Exterior Wash; 1-day lead; peak hourly rain 10%; appointment-hour rain 10%; low/high 52/72°F; max wind 8 mph | No invented concern; classes match Python |
| B: two different rain values | Exterior Wash; 1-day lead; peak hourly rain 70%; appointment-hour rain 10%; low/high 50/68°F; max wind 8 mph | Keeps the highest hourly value separate from the appointment-hour value; never calls either an all-day chance |
| C: interior with severe weather | Interior Clean; 1-day lead; peak hourly rain 90%; low/high 65/85°F; max wind 32 mph | Keeps the interior outlook; does not claim weather will affect indoor work |
| D: mixed service, missing facts | Full Detail; 7-day lead; rain probability and low temperature missing; high 72°F; max wind 8 mph | Keeps unknown values unknown, invents no numbers, states forecast uncertainty |
| E: exterior with two concerns | Exterior Wash; 7-day lead; peak hourly rain 20%; low/high 30/45°F; max wind 22 mph | Mentions both the freezing and wind concerns; gives no product, technique or rescheduling advice |

Python's classes for these cases (from `guidance/classify.py`): A is
`favorable`; B is `concerns` (rain); C is `weather_minor`; D is `incomplete`
with confidence `lower`; E is `concerns` (wind and freezing).

### Complete fixed inputs

The matrix above did not list every value the application needs, so the
following were added on November 12, 2026 to make the cases buildable. They
change no class, concern or missing value (checked with the real code and by the
automated tests). "Today" is pinned to **Monday, November 16, 2026, 09:00
Central Time**, so every run uses the same dates.

| Case | Date (lead) | Appointment | Precipitation | Max gust | Appointment-hour temperature / wind / rain |
|---|---|---|---|---|---|
| A | Tue Nov 17 (1 day) | 10:00 AM | 0.0 in | 14 mph | 60°F / 6 mph / 10% |
| B | Tue Nov 17 (1 day) | 10:00 AM | 0.12 in | 15 mph | 56°F / 6 mph / 10% |
| C | Tue Nov 17 (1 day) | none (daily facts only) | 0.35 in | 41 mph | not applicable |
| D | Mon Nov 23 (7 days) | none (daily facts only) | 0.0 in | 14 mph | not applicable |
| E | Mon Nov 23 (7 days) | none (daily facts only) | 0.01 in | 31 mph | not applicable |

Case D's only missing values remain the low temperature and the rain
probability. The case definitions live in `guidance/evaluation.py` (`CASES`).

## Running the evaluation

A meaningful v1/v2 comparison needs **the same facts for both runs**.
`python manage.py guidance_check` cannot provide that because it fetches the
live forecast. The fixed-facts runner (`guidance/evaluation.py`, command
`guidance_evaluate`) builds each case as real `WeatherFacts` with the
application's own `build_facts()` from a fixed synthetic forecast, with "today"
pinned as above. It sends each case to `llm.request_explanation()` and checks
the reply with `validate_output()`. No forecast is fetched, so weather-fetch
failures cannot occur.

```bash
python manage.py guidance_evaluate                      # dry run: show the five cases; no model calls, nothing written
python manage.py guidance_evaluate --live               # the five-case Task 10 baseline; writes a results file
python manage.py guidance_evaluate --live --cases A B   # a diagnostic subset (never the baseline)
```

**Safety:** without `--live` nothing calls the model or the network and
nothing is written; importing the module or running the tests never calls the
model. With `--live`, the command refuses to start (exit status 1), before any
model call and without writing anything, unless all of these hold, checked in
this order:

1. the Ollama endpoint is this machine. The protocol requires local execution,
   and the memory check measures this machine. The application itself can be
   configured for a remote model; only this evaluation command refuses one;
2. free memory **could be measured**: if it cannot, the run is refused (fail
   closed), never assumed to be fine;
3. free memory is at least 6 GB (`--min-free-gb` sets a different, explicit
   threshold; it must be a positive number);
4. Ollama answers `GET /api/version`;
5. the configured model is installed (`GET /api/tags`; nothing is loaded or
   downloaded).

It applies the stop rule below: after a timeout, the remaining requested cases
are recorded as `not_run`. Exit status: 0 all requested cases ran, 1 refused to
start, 2 invalid arguments, 3 stopped by the stop rule (the results file is
still written).

**Baseline versus subset:** only a run of all five cases A–E is the **Task 10
baseline**. A run with `--cases` is a **diagnostic subset** and is labelled as
such in the output and the results file. A run that stopped early is
**incomplete**.

**Statuses per case:** `accepted`, `rejected` (validator reason codes
recorded), `timeout`, `model_unavailable` (connection or HTTP error),
`parse_failure` (the reply was not a usable JSON object) and `not_run`.

**Results file:** each live run writes a new file
`eval_results/task10-<prompt version>-<UTC time>.json` (never overwriting an
older one; the folder is ignored by Git). It contains:

- `metadata`: timestamp, the pinned reference date, the requested case IDs and
  run scope (`full_baseline` or `subset`), `PROMPT_VERSION`, a SHA-256 hash of
  the system prompt, the configured model name (`model_configured`) and what
  Ollama resolves it to (`model_resolved`, `model_digest`, size and
  quantization; for example `llama3` resolves to `llama3:latest`), Ollama
  version, `OPTIONS`, `keep_alive`, timeout, whether the endpoint is local (no
  host name is stored), and free memory before and after the run (`null` after
  the run if it could not be measured);
- `summary`: scope, run state (`complete` or `incomplete`), counts per status,
  median and maximum model-call latency, and rates only where they mean
  something: `task10_baseline` (validator acceptance and fallback out of five)
  only for a complete five-case run; `subset_statistics`, labelled as a
  diagnostic subset, only for a complete subset; no rates for an incomplete
  run;
- `cases`: per case, status, failure kind, reason codes, latency, a
  `facts_sha256` fingerprint of exactly what the model received, the sanitized
  model output (schema fields only, cleaned and length-capped), and an empty
  `human_review` for the reviewer to fill in.

**Inspecting a result:** open the JSON file; confirm `run_scope` is
`full_baseline` and the run state is `complete`; check `metadata` matches
between the v1 and v2 files (`model_resolved`, `model_digest`, Ollama version,
options, timeout); confirm each
case's `facts_sha256` is identical across the two files; read each
`model_output` and record the human-review checks below in `human_review`. Copy
the summary numbers into this document rather than committing raw files.

**Still to do:** the independent human review of the v1 replies (see the
[review packet](task10_v1_review_packet.md)), then prompt v2 and the v1/v2
comparison.

## What to measure

For each prompt version, five attempts, one per case:

- **Validator acceptance:** accepted replies divided by five.
- **Fallback rate:** timeouts, connection/HTTP/parse failures and validator
  rejections divided by five, with each reason reported separately.
- **Latency:** every model-call duration, summarized as median and maximum.
- **Human review:** for each accepted reply, does it match the facts, avoid
  unsupported claims and advice, and respect the service type and forecast
  uncertainty? Record pass/fail per check and the mismatch when it fails. Keep
  this separate from validator acceptance.

Record for every run: timestamp, Ollama version, the configured model name and
the exact model Ollama resolved it to (tag and digest), `PROMPT_VERSION`, a
hash of the system prompt, `OPTIONS` (temperature and `num_predict`), the
configured timeout, free memory before and after the run, and each case's
latency, validator status and reason codes, and human-review decisions. Keep
the resolved model and settings identical for both prompt versions. Save only
sanitized outputs; there is no customer data in these cases.

Five cases are a small course-project sample, not a population estimate. Do not
call validator acceptance "accuracy". Do not count weather-fetch failures as
model fallbacks.

## Prompt v1 baseline (November 12, 2026)

One complete five-case run of `python manage.py guidance_evaluate --live`,
started November 12, 2026 at 9:03 PM Central (03:03 UTC on November 13).

| Run setting | Value |
|---|---|
| Model | `llama3` resolved to `llama3:latest` (digest `365c0bd3c000`, 8.0B, Q4_0), Ollama 0.30.6, local endpoint |
| Prompt | `v1` (system prompt SHA-256 `41f0c535e7c2…`) |
| Options | temperature 0, `num_predict` 220, `keep_alive` 30m, timeout 45 s |
| Free memory | 6.92 GB before; 3.76 GB after (the model stays loaded for `keep_alive`) |
| Scope and state | `full_baseline`, `complete`; exit status 0 |
| Raw results | `eval_results/task10-v1-20261113T030317Z.json` (kept out of Git) |

| Case | Validator status | Model-call latency | Reason codes |
|---|---|---|---|
| A: favorable exterior | accepted | 18,230 ms (first call; no model was loaded, so it includes loading) | none |
| B: two different rain values | accepted | 11,716 ms | none |
| C: interior with severe weather | accepted | 11,135 ms | none |
| D: mixed service, missing facts | accepted | 11,360 ms | none |
| E: exterior with two concerns | accepted | 11,106 ms | none |

- **Validator acceptance:** 5 of 5 (100%).
- **Fallback:** 0 of 5 (0%): no timeouts, connection, HTTP or parse failures,
  and no validator rejections.
- **Latency:** median 11,360 ms, maximum 18,230 ms (5 calls).

These figures come from one five-case course-project baseline at temperature 0.
They are not a population estimate, and validator acceptance is not accuracy.

### AI-assisted preliminary review (not a human review)

Three different checks apply to these replies, and only the first is final:

1. **Validator acceptance** (automatic, rule-based): 5 of 5 accepted. It does
   not check meaning.
2. **AI-assisted preliminary review:** a first reading of the five replies
   against the fixed facts, prepared with an AI assistant. It is not a human
   review and decides nothing.
3. **Independent human review:** **pending.** The `human_review` field of every
   case in the results file is still empty. The reviewer works from
   [`task10_v1_review_packet.md`](task10_v1_review_packet.md), which shows each
   case's facts, the exact saved reply and a pass/fail template.

Preliminary findings (AI-assisted):

| Case | Facts and classes | Invented weather or numbers | Products, techniques or booking advice | Service type | Uncertainty wording | Finding |
|---|---|---|---|---|---|---|
| A | Kept | None | None | Exterior | No note (higher confidence) | Minor: an unnecessary conditional rain caveat ("if it rains") although conditions are favorable |
| B | Classes kept; 70% reported as the peak hourly probability | None | None | Exterior | No note (higher confidence) | Omits the 10% appointment-hour probability; "a high chance of rain on the day of your appointment" may imply an all-day probability |
| C | Kept | None | None | Correct: interior work is affected less | **Meta-commentary in a customer field:** "Since it's only one day ahead, there's no uncertainty note needed." | The optional field should have been empty |
| D | Unknown values stay unknown | None | None | Correct for a mixed service | Says the forecast may change, but uses the internal term "lead days" | The summary is incoherent ("expected to be light and unknown") |
| E | Both concerns (freezing and wind) in the summary | None | None | Exterior; the explanation mentions only rain | Appropriate for a 7-day lead | Wind and freezing are not in the service explanation |

For A and E, the service sentence that Python supplies for every exterior
service mentions rain, and only rain, and the v1 prompt limits the service
explanation to that sentence. Those two findings may therefore come from the
design of the fixed sentence rather than from the model; the human review
should decide.

## v1 failure analyses (preliminary, pending human review)

The protocol asks for two failure analyses. Both are based on the
AI-assisted preliminary review and become final only if the human review
confirms them.

### Failure 1 (case B): rain probabilities not kept apart

- **Expected:** the reply distinguishes the highest hourly rain probability
  (70%) from the appointment-hour probability (10%) and calls neither an
  all-day chance. This is the requirement case B was designed to test.
- **Actual:** "There is a high chance of rain on the day of your appointment,
  with a peak hourly rain probability of 70%." The 10% appointment-hour
  probability is not mentioned, and the 70% is not called "the highest hourly
  rain probability" as the v1 prompt requires.
- **Impact:** a customer booked for 10:00 AM could believe rain is likely at
  their appointment, when the chance for that hour is 10%, or read 70% as the
  chance of rain all day.
- **Likely cause (from the v1 prompt):** the prompt allows the
  appointment-hour value ("only when it is present") but never requires it,
  and does not require the two values to be stated together. The phrase "on the
  day of your appointment" also appears in the service sentence Python
  supplies, which may encourage a whole-day framing (a hypothesis).
- **Proposed v2 change:** see "Proposed prompt v2" below.

### Failure 2 (case C): commentary in a customer-facing field

- **Expected:** the optional uncertainty note is empty when no customer-facing
  uncertainty explanation is needed (confidence `higher`, 1 day ahead).
- **Actual:** "Since it's only one day ahead, there's no uncertainty note
  needed."
- **Impact:** the model's reasoning about its own output reaches the customer,
  which reads as a malfunction. The validator accepted it.
- **Likely cause (from the v1 prompt):** the rule says the note "may be empty"
  under 3 days ahead; it does not say it must be empty or forbid commentary
  about omitted fields.
- **Proposed later change (not in v2):** explicitly forbid commentary about
  omitted or empty fields, and require an empty note when nothing applies.

### Additional observation (case D)

The summary "The weather forecast is incomplete, but it's currently expected to
be light and unknown." is incoherent: it merges "wind: light" and "temperature:
unknown" and does not say which values are missing. The uncertainty note uses
the internal field name "lead days". No number was invented and the missing
values stayed unknown. This is recorded as a quality issue, not one of the two
formal failure analyses.

## Proposed prompt v2 (not implemented)

**Target: Failure 1 (case B).** It is a central requirement written into the
fixed case matrix, and a misread rain probability can mislead a customer about
their own appointment. Failure 2 stays for a later version: the protocol allows
**one** targeted prompt change per version, so v2 must not also change the
uncertainty rule.

Proposed rule change, replacing the v1 rule "Use
appointment_hour_rain_probability_pct only for the appointment hour, and only
when it is present.":

> When both peak_hourly_rain_probability_pct and
> appointment_hour_rain_probability_pct are present, the summary must state
> both, separately: "the highest hourly rain probability" for the date and the
> rain probability at the appointment hour. Never describe either value as the
> chance of rain all day.

Nothing else changes: same facts, validator, classification rules, model,
options and timeout; `PROMPT_VERSION` becomes `v2`. **Prompt v2 is not
implemented and has not been run.**

How v2 will be judged (protocol step 4): adopt v2 only if case B passes the
human review on this point without new unsupported claims, rejections,
fallbacks or a latency increase in any case. Case A also has both values (10%
and 10%), so it will show whether the new rule makes replies clumsy when the
values are equal.

## Before the v2 run

- v2 is run only after the prompt change has been reviewed and pushed; whoever
  runs it uses that pushed version of the code.
- Measure available RAM immediately before the run. At least **6 GB** of
  successfully measured available RAM is required; the runner refuses to start
  otherwise, and the guard must not be bypassed or lowered.
- If this laptop fails the guard, the comparison can be run on a teammate's
  machine with the **same** model digest (`365c0bd3c000`), Ollama version
  (0.30.6), options, timeout and fixed cases. Record that machine separately,
  and do not compare its latency with v1's as if it came from the same
  hardware.
- Keep the v1 results file unchanged. Each case's facts fingerprint must be
  identical in the v1 and v2 files (v1: A `84ce92c5a9de`, B `b3b411ad5309`,
  C `162366edd0dc`, D `004472a3814f`, E `eef0b3d39f14`; first 12 characters of
  `facts_sha256`).

## Failure observations before the baseline

1. **Invented service advice (planning probe).** Both early replies recommended
   products. The app now keeps the recommendation in Python and rejects known
   advice terms. The rule-based validator can still miss paraphrases, so human
   review stays necessary.
2. **45-second timeout (Nov 12 application call).** About 0.4 GB of RAM was free
   and the model ran partly on CPU and partly on a 4 GB GPU. A later run that day,
   with about 6.8 GB free and the same 44% GPU / 56% CPU split, succeeded.
   Memory pressure is therefore a plausible contributor, but two observations do
   not prove it. The Python fallback kept the booking page working.

## Prompt comparison and stop rule

1. Capture the v1 baseline on the five cases before changing the prompt.
2. Change **one** prompt rule that targets an observed failure, and bump
   `PROMPT_VERSION`.
3. Rerun the same five cases. Keep the validator and classification rules fixed.
4. Adopt v2 only if it improves the targeted human-reviewed outcome without
   increasing unsupported claims, rejections, fallbacks or latency. Record the
   exact change and both result sets; otherwise keep v1.

Do not start the model while less than 6 GB of memory is free. If the first
measured call reaches the timeout, record the timeout and stop the run. Never
build before-and-after numbers from mocked tests.
