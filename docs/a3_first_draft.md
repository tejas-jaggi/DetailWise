# DetailWise: P2-A3 First Draft

*INFO 490 Project 2, Team 3: Yidan Huang, Bochen Zhang, Tianze Guo and Tejas
Jaggi. Prepared November 12, 2026, for the first-draft deadline of November 16,
2026.*

Repository: <https://github.com/tejas-jaggi/DetailWise>

Every result below was produced in this repository. Three kinds of evidence
are kept separate: **automated tests** (the AI model and the network are
replaced with fixed replies), **live checks** with the real forecast and model
(section 3), and a **browser check** with a simulated model. The first real AI
call through the app timed out and fell back to standard guidance; a later
**controlled application-level smoke test succeeded** (one run, section 3). A
live AI explanation in the browser has not yet been demonstrated.

---

## 1. Updated product scope (15 pts)

**Startup:** DetailWise, an online booking tool for a single car detailing shop
in Urbana, IL.

**Problem.** Small detailing shops take bookings by phone or text. Customers
cannot easily see what is offered or keep track of what they booked. Exterior
work depends on the weather, so customers often book a wash for a day when it
will rain, and nothing warns them.

**Target users.**
- **Customers:** local car owners who want to book online and keep track of it.
- **Shop staff:** the owner or employees who need a view of booking volume and value.

**Three core features.**
1. **Customer accounts and booking** (implemented): service catalog,
   registration and sign-in, booking with Central Time validation, a private
   My Bookings list and booking detail.
2. **Weather-informed AI guidance** (implemented and covered by automated tests;
   prompt v1 baseline evaluated on five fixed cases): on
   the booking page, the forecast for the chosen date and an explanation of what
   it means for the chosen service, written by an AI model (Llama 3, run by the
   Django server through Ollama) from facts that Python computes and checks.
3. **Staff analytics and export** (planned): a staff dashboard with charts by
   date and service, and a CSV export.

**Why a customer would prefer it:** generic booking tools do not tell you
whether the weather suits the service you are booking; weather apps do not know
which service you booked. DetailWise puts both on the booking page, and never
pressures the customer: the guidance is informational and the booking is always
their choice.

**Changes from P2-A2** (full list in [`product_scope.md`](product_scope.md)):
- The four proposed features are grouped into the three above.
- Django's built-in accounts are used; Google sign-in is postponed.
- Each booking stores the price at the time of booking.
- Each service records whether it is exterior, interior or mixed work, which
  the AI guidance uses.
- The AI model is chosen: Llama 3 8B, run locally with Ollama.
- The AI explains the forecast but does not write the recommendation, because
  a planning test showed the model inventing product advice.

Bochen Zhang's P2-A2 prototype is the team-approved design and is now applied
to every page: dark background, yellow primary actions, cyan for information
and the AI label, compact 3px corners, boxed header, illustrated service cards,
centred sign-in forms, and the "Weather for your date" panel beside the booking
form. Headings use installed condensed system fonts because the prototype's
embedded font has an unverified web licence.

## 2. Functional Django foundation (40 pts)

| Requirement | Evidence in the repository |
|---|---|
| Functional Django project | `config/` (settings from environment variables, URL routing) |
| At least one Django app | Three: `accounts`, `bookings`, `guidance` |
| At least two meaningful models | `accounts.User` (custom user), `bookings.Service`, `bookings.Booking` |
| Relationship between models | `Booking.customer` → `User` (FK, cascade); `Booking.service` → `Service` (FK, protect) |
| Migrations | `accounts/migrations/0001_initial.py`, `bookings/migrations/0001_initial.py`, `0002_seed_services.py` (reversible seed data) |
| Working views and templates | Function-based views (`register`, `catalog`, `booking_create`, `my_bookings`, `booking_detail`, guidance endpoints) and class-based views (`SignInView`, `SignOutView`); every page extends `templates/base.html`; reusable includes (`includes/form_field.html`, `bookings/_booking_card.html`, `guidance/_weather_panel.html`) |
| Functional form | `BookingForm` (service, date, time, validated in Central Time), registration form, sign-in form, `GuidanceRequestForm` |
| Database-backed workflow | Catalog → sign in → **Book a service** (form) → `booking_create` view saves a `Booking` for the signed-in user → redirect to **My Bookings**, which lists the saved booking with its reference (for example `DW-0001`) |
| Authentication and authorization | Sign-in/out (POST, CSRF), protected routes, customers see only their own bookings, staff get 403 on customer pages |
| JSON API and external API | Customer-only JSON endpoints `/guidance/forecast/` and `/guidance/explain/`; Open-Meteo forecast API |

**Workflow:** User input (booking form) → Django view (`booking_create`,
server-side validation) → database operation (`Booking` saved with the
customer and a price snapshot) → visible result (confirmation message and the
booking in My Bookings).

**Test results (November 12, 2026):**

| Command | Result |
|---|---|
| `python manage.py test` | 464 tests, OK (accounts 24, bookings 78, guidance 362) |
| `node --test "guidance/tests/js/*.test.mjs"` | 29 tests, OK |
| `python manage.py check` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |

## 3. Initial AI implementation and technical plan (20 pts)

**Feature:** weather guidance for a booking (AI-assisted decision support).

**Model and technique:** Llama 3 8B (`llama3`, Q4_0) served by Ollama, called
by the Django server over HTTP with a JSON schema that constrains the reply.
Python does the reasoning (classification and recommendation); the model writes
plain-language explanations of those results.

**Input:** facts for one service, date and optional time: forecast values with
units, Python's classes (rain, wind, temperature, confidence, outlook), the
service's weather sensitivity and the fixed explanation of what the rain
percentage means. No customer identity is sent.

**Output:** one JSON object with the five classes (which must match Python's)
and three short texts: Conditions, For your service, and Forecast confidence.
The Recommendation always comes from Python.

**How it interacts with Django:**

```
Booking page (customer) → /guidance/explain/ (view, signed-in customers only)
  → Open-Meteo forecast → Python facts and classes
  → Ollama /api/chat (JSON schema) → validator checks every field
  → accepted: AI explanation  |  rejected or unavailable: standard guidance from Python
  → four labelled sections in the panel beside the booking form
```

**Implemented:** the forecast client, classification, facts, Ollama client,
validator, fallback, service layer with a 30-minute cache of accepted replies,
JSON endpoints, the booking-page panel, and a live-check command
(`python manage.py guidance_check`). Full documentation:
[`ai_plan.md`](ai_plan.md).

**Feasibility evidence:**

| Evidence | Type | Result |
|---|---|---|
| Planning probe, Nov 10 | Real Ollama calls (2) | Class fields matched the facts in 2 of 2 runs; 23 s cold, 13 s warm; both runs invented product advice, which led to the Python-only recommendation and the advice filter |
| `guidance_check`, Nov 12 | Real Open-Meteo + real Ollama (1 call) | Forecast in 454 ms; Ollama and `llama3` found; **the model call timed out at 45 s** under memory pressure (0.4 GB RAM free), and standard guidance was shown as designed |
| Direct Ollama call, Nov 12 (later) | Real Ollama (1 call, cold start) | With about 6.8 GB of RAM free: valid reply in 13.9 s (10.7 s to load the model); the model ran about 44% on the GPU and 56% on the CPU |
| `guidance_check`, Nov 12 (later) | Real Open-Meteo + real Ollama (1 run, disposable project copy) | Forecast in 1,571 ms; the reply was **accepted by the validator** in about 11.3 s with no fallback; 13.7 s in total, exit status 0. Conditions and For your service were written by the model; Forecast confidence and Recommendation came from Python |
| Task 10 prompt v1 baseline, Nov 12 (evening) | Real Ollama, five fixed cases, one run each (`guidance_evaluate --live`) | **5 of 5 replies accepted by the validator, 0 of 5 fallbacks**; 18.2 s for the first call (including model load), then 11.1–11.7 s; median 11.4 s. Independent human review pending; an AI-assisted preliminary review found possible content problems the validator does not catch |
| Automated tests | Mocked network and model | 362 guidance tests pass, covering every model failure type, the validator and the fallback |
| Browser check | Simulated model on a disposable copy | Forecast, accepted and fallback explanations, stale-result protection, mobile layout and booking save all worked |

**Where the model runs:** the customer's browser only talks to Django; Django
calls Ollama. Customers never need Ollama installed. The model must be
reachable from whichever machine runs Django, so a hosted version (for example
on Render) needs its own reachable model server or inference provider; Ollama
on a laptop does not serve a hosted app. Without a reachable model, customers
get standard guidance from Python.

**First successful controlled application-level AI smoke test completed on
November 12, 2026** (the last row above). It is one command-line run on a
disposable copy of the project, so it does not establish reliability,
acceptance or fallback rates, performance under concurrent use, or a live
browser demonstration. The earlier timeout had about 0.4 GB of RAM free and the
success about 6.8 GB, so insufficient memory is a plausible contributor to the
timeout; this is a hypothesis, not a proven cause.

**Task 10 prompt v1 baseline (completed November 12, 2026):** the five fixed
cases in [`task10_evaluation.md`](task10_evaluation.md) were run once each with
the same fixed facts (`python manage.py guidance_evaluate --live`). The
validator accepted 5 of 5 replies, with no fallback; median latency 11.4 s.
This is one five-case course-project baseline, not a population estimate, and
validator acceptance is not accuracy: an AI-assisted preliminary review (not
a human review) found possible content problems in cases B, C and D that the
validator does not catch. The independent human review is pending.

**Next step (Task 10, planned):** the human review of these five replies, two
failure analyses, one targeted prompt change (v2) and a rerun on the same
facts. **No prompt v1/v2 comparison exists yet.**

## 4. Development progress and roadmap (15 pts)

Responsible members and dates marked *Proposed* are **not yet confirmed by the
team**. The detailed, living version is [`roadmap.md`](roadmap.md).

| Task | Current status | Responsible member | Expected completion |
|---|---|---|---|
| Django core features | Accounts, catalog, booking, My Bookings and ownership done (91 original tests, plus 11 design-system tests). Edit/cancel booking planned | Tejas Jaggi | Core done; edit/cancel *Proposed* Nov 22 |
| Database and APIs | Models, migrations, Open-Meteo integration and customer JSON endpoints done. Staff summary JSON, CSV export and dashboard planned | Tejas Jaggi; *Proposed:* Yidan Huang (aggregation queries), Bochen Zhang (charts) | *Proposed* Nov 25–28 |
| AI integration | Implemented and tested with mocks; first real call timed out (45 s) and fell back correctly; first controlled smoke test accepted (Nov 12, one run); live browser demonstration planned | Tejas Jaggi; *Proposed:* Tianze Guo (hosted-model comparison) | Browser demonstration: team to confirm |
| Evaluation and testing | 464 Django + 29 JavaScript tests pass (mocked). Fixed-facts runner implemented; prompt v1 baseline run Nov 12 (validator acceptance 5 of 5, fallback 0 of 5; [`task10_evaluation.md`](task10_evaluation.md)); two failure analyses drafted and prompt v2 proposed (not implemented); human review and v1/v2 comparison planned | Tejas Jaggi; *Proposed:* Tianze Guo (run and record cases) | *Proposed* Dec 2 |
| Deployment | Planned; the hosted app needs a reachable model (see `ai_plan.md` §10) and the HTTPS production settings in section 5 | Team to confirm | *Proposed* Dec 4 |
| Documentation | README, AI documentation, scope, roadmap and this draft done. Mid-point presentation video (4 minutes) and the separate P2-A4 final demo video (at most 3 minutes) and final README planned | Tejas Jaggi; videos: team to confirm | *Proposed* Dec 7 |

## 5. GitHub organization and reproducibility (10 pts)

- **Repository:** <https://github.com/tejas-jaggi/DetailWise> (public, so the
  instructor can read it).
- **Contents:** Django code, migrations, the AI integration code,
  `requirements.txt`, `.gitignore` (excludes `.env`, the database, caches and
  model weights such as `*.bin`, `*.safetensors`, `*.pt`, `*.gguf`) and
  `README.md` with setup, environment variables, database setup, how to run the
  app and tests, and how to use the AI feature.
- **Reproducibility:** a new developer follows the README: create a virtual
  environment, install `requirements.txt`, copy `.env.example` to `.env`, add a
  secret key, run `migrate`, then `runserver`. The AI is optional: without
  Ollama the app runs and shows standard guidance.
- **Secrets:** no `.env`, keys or passwords are tracked; `.env` is excluded by
  `.gitignore`, and the README tells developers never to commit or share it.
- **Production settings:** `python manage.py check --deploy` lists four HTTPS
  settings for a public deployment (W004 HSTS, W008 SSL redirect, W012 secure
  session cookie, W016 secure CSRF cookie). These are hosting requirements to
  set once the HTTPS host is chosen, not faults in the local development app.
