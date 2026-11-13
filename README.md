# DetailWise

DetailWise is a Django web application for a fictional car detailing shop in
Urbana, IL. Customers browse services, create an account and save bookings.
On the booking page, an optional **weather guidance panel** shows the forecast
for the chosen date and, on request, an AI-written explanation of what it means
for the chosen service. Python computes every number and recommendation, and
every AI reply is validated before a customer sees it.

INFO 490 Project 2, Team 3: Yidan Huang, Bochen Zhang, Tianze Guo and Tejas Jaggi.

> **Status (P2-A3 first draft, November 12, 2026):**
> - **Completed:** the customer booking workflow and the weather guidance
>   feature, covered by 464 Django tests and 29 JavaScript tests (passing).
>   These automated tests replace the AI model and the network with fixed replies.
> - **Live checks (Nov 12, 2026):** the real Open-Meteo fetch succeeded. The
>   first real AI call through the app timed out after 45 seconds and returned
>   standard Python guidance as designed. Later that day the **first successful
>   controlled application-level AI smoke test** passed: one `guidance_check` run
>   (on a disposable copy) was accepted by the validator with no fallback, in
>   about 13.7 s in total. This one command-line run does not yet establish a
>   live browser demonstration, reliability or acceptance rates.
> - **AI evaluation (Task 10):** the prompt v1 baseline is complete: five fixed
>   cases, one run each; the validator accepted 5 of 5 replies and 0 of 5 fell
>   back. Validator acceptance is not accuracy; the independent human review
>   and the prompt v1/v2 comparison are pending
>   ([results](docs/task10_evaluation.md)).
> - **Planned:** the human review and prompt comparison, a live AI explanation
>   in the browser, the staff dashboard and deployment, before the
>   December 8 final submission. See
>   [Scope notes and next steps](#scope-notes-and-next-steps).

## What works today

| Feature | Status |
|---|---|
| Service catalog (Exterior Wash $35, Interior Clean $60, Full Detail $95) | Working |
| Customer registration (does not sign you in, never creates staff) | Working |
| Sign in and sign out (POST only, CSRF protected) | Working |
| Selected service kept through sign-in and registration | Working |
| Create booking: service, date and time validated in Central Time | Working |
| My Bookings: only your own bookings, with Upcoming and Past/cancelled lists | Working |
| Booking detail page (other customers' bookings show "Booking not found") | Working |
| Django admin for users, services and bookings | Working |
| Weather forecast for the chosen date (Open-Meteo, no API key) | Working |
| AI explanation of the forecast (Llama 3 via Ollama, called by the Django server), validated, with standard-guidance fallback | Working in code and automated tests; one controlled live smoke test accepted (Nov 12); Task 10 prompt v1 baseline: 5 of 5 replies accepted by the validator (Nov 12); browser demonstration planned (see [live evidence](docs/ai_plan.md#13-live-experiment-evidence)) |
| Customer-only JSON endpoints for the forecast and the explanation | Working |
| Live-check command (`guidance_check`) | Working |
| Edit and cancel a booking | Planned |
| Staff dashboard (Vega-Lite charts, CSV export) | Planned |
| AI evaluation (accepted/fallback rates, failure analysis) | Prompt v1 baseline run Nov 12 on five fixed cases: validator acceptance 5 of 5, fallback 0 of 5, median latency 11.4 s. Human review pending ([review packet](docs/task10_v1_review_packet.md)); prompt v2 proposed, not implemented ([docs/task10_evaluation.md](docs/task10_evaluation.md)) |
| Deployment | Planned |

The workflow is: **Service Catalog → Sign In/Register → Create Booking (with
optional weather guidance) → Database Save → My Bookings**.

## Requirements

- Python **3.13**
- Dependencies, pinned in `requirements.txt`:

  | Package | Purpose |
  |---|---|
  | Django 5.2.19 (LTS) | Web framework |
  | python-dotenv 1.2.1 | Loads settings from a local `.env` file |
  | asgiref, sqlparse | Django dependencies |
  | tzdata | Time zone data for `America/Chicago` (needed on Windows) |

  The weather and AI features use only the Python standard library. There is no
  AI SDK and no API key.
- The database is SQLite during development. Nothing needs installing.
- **Optional, for AI explanations:** [Ollama](https://ollama.com) and the
  `llama3` model (about 4.7 GB to download; about 6 GB of free memory to run).
  Without it, the app works and shows standard guidance.
- **Optional, for the JavaScript tests:** Node.js 18 or newer (tested with v24).

## Setup

Run these commands from the repository root: the folder that contains
`manage.py` (named `DetailWise` when cloned from GitHub).

**Windows (PowerShell):**

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Next, generate a secret key and paste it into `.env` as `DJANGO_SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Environment variables

| Variable | Example | Meaning |
|---|---|---|
| `DJANGO_SECRET_KEY` | (generated) | Required. The app refuses to start without it. |
| `DJANGO_DEBUG` | `True` | Use `True` only for local development. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Optional. Where **the Django server** reaches Ollama. |
| `OLLAMA_MODEL` | `llama3` | Optional. Model name as Ollama knows it. |
| `GUIDANCE_LLM_TIMEOUT` | `45` | Optional. Seconds to wait for the model (whole number, 1 or more). |

`.env` is listed in `.gitignore`. **Never commit it or share it** (for example
in a ZIP of the project, a screenshot or a chat). If it is ever shared,
generate a new `DJANGO_SECRET_KEY`.

## Database and seed data

```bash
python manage.py migrate
```

This creates `db.sqlite3` and seeds the three services through a reversible
data migration (`bookings/migrations/0002_seed_services.py`). The service
descriptions come from wireframe S01.

To create an administrator account, which is also a staff account:

```bash
python manage.py createsuperuser
```

Staff accounts are only created this way or in the Django admin. Public
registration always creates customer accounts.

## Run the server

```bash
python manage.py runserver
```

Then open these pages:

- <http://127.0.0.1:8000/> for the service catalog
- <http://127.0.0.1:8000/accounts/register/> to register
- <http://127.0.0.1:8000/bookings/new/> to book (sign-in required)
- <http://127.0.0.1:8000/bookings/> for My Bookings (sign-in required)
- <http://127.0.0.1:8000/admin/> for the Django admin (staff only)

## AI weather guidance

### How to use it

1. Sign in as a customer and open **Book a service**.
2. Choose a service and a date (and optionally a time). The **Weather for your
   date** panel shows the forecast for that exact date. Forecasts cover today
   and the next 15 days.
3. Press **Explain this forecast**. In the controlled runs on November 12 on
   the development laptop, a new explanation took about 11–18 seconds; it can
   take up to the 45-second timeout, after which standard guidance is shown.
   Repeated identical explanations with a previously accepted AI response are
   served from the 30-minute cache. Rejected, failed and
   standard-guidance results are never cached, so those requests ask the model
   again.
4. The panel shows **Conditions**, **For your service**, **Forecast confidence**
   and **Recommendation**, labelled **AI explanation** or **Standard guidance**.
5. **Save booking** works the same whether or not you use the panel.

### Turning on AI explanations (optional)

The model is called **by the Django server**, not by the customer's browser.
Customers never need Ollama; the machine running Django must be able to reach
it. If the app is later hosted (for example on Render), Ollama running on a
teammate's laptop will **not** serve it: the hosted server needs its own
reachable model server or inference provider. See
[docs/ai_plan.md §10](docs/ai_plan.md#10-where-the-model-must-run-deployment).

1. Install Ollama from <https://ollama.com/download> and start it (the desktop
   app starts the server; otherwise run `ollama serve`).
2. Download the model once: `ollama pull llama3`
3. Check it is listed: `ollama list` should show `llama3:latest`.
4. Keep the defaults in `.env`, or set `OLLAMA_BASE_URL` / `OLLAMA_MODEL`.

**Without Ollama** (or if the model is slow, fails or writes something the
validator rejects), the panel shows **Standard guidance**: the same four
sections written by Python from the forecast, for example:

> **Recommendation:** Worth noting for exterior work: the forecast low is at or
> below 32°F. Your booking is not changed by this guidance. The choice is yours.

How the AI works, what it is sent, how replies are validated, and its
limitations are documented in **[docs/ai_plan.md](docs/ai_plan.md)**.

### Live check

`guidance_check` runs the real pipeline for one booking and reports each step.
It calls Open-Meteo and, if it is already running, the configured Ollama model.
It never downloads a model and never writes to the database.

```bash
python manage.py guidance_check --service exterior-wash --date 2026-11-14 --time 10:00
python manage.py guidance_check --service interior-clean --date 2026-11-20 --runs 3
```

It prints the forecast fetch time and cache hit or miss, the facts and classes,
whether Ollama is reachable and the model installed, and for each run the
latency and whether the reply was accepted (with reason codes if not), then the
customer sections. It never prints the prompt or the raw model reply.

| Exit status | Meaning |
|---|---|
| 0 | Every run was accepted |
| 1 | Invalid input, or no forecast for that date |
| 2 | Ollama or the model was unavailable, or at least one run fell back to standard guidance |

On Windows, run it in PowerShell or Windows Terminal; some consoles show `°` incorrectly.

### Task 10 evaluation runner

`guidance_evaluate` builds the five fixed evaluation cases from
[docs/task10_evaluation.md](docs/task10_evaluation.md) with the same facts on
every run, so prompt versions can be compared fairly.

```bash
python manage.py guidance_evaluate                     # dry run: shows the cases; no model calls, nothing written
python manage.py guidance_evaluate --live              # five-case Task 10 baseline; saves eval_results/task10-*.json
python manage.py guidance_evaluate --live --cases A B  # diagnostic subset only, never reported as the baseline
```

`--live` refuses to start, without calling the model or writing a file, unless
Ollama runs on this machine, free memory can be measured and is at least 6 GB
(an unmeasurable amount is refused), Ollama answers, and the configured model
is installed. Only a complete run of all five cases yields the baseline rates.
Exit status: 0 all requested cases ran, 1 refused to start, 2 invalid
arguments, 3 stopped after a timeout (results still saved). Results files go to
`eval_results/`, which Git ignores and the command never overwrites. The prompt
v1 baseline was run on November 12; its results are in
[docs/task10_evaluation.md](docs/task10_evaluation.md).

## Run the tests

```bash
python manage.py test
node --test "guidance/tests/js/*.test.mjs"
```

The Django tests use a temporary test database built from the real migrations,
seed data included. **No test uses the network or a real AI model**: Open-Meteo
and Ollama are replaced with fixed replies. The JavaScript tests run in Node
with no packages to install, and also run inside the Django suite when Node is
installed. The tests cover:

- Models, constraints and seed migration reversibility
- Central Time and daylight saving time (DST) validation
- Registration, sign-in and sign-out, and permissions
- The catalog, booking creation, My Bookings and booking ownership
- The forecast client, classification rules, exact-date facts and DST hours
- The AI client's request and every failure type, the validator, the fallback,
  the service layer and its cache, the JSON endpoints, the booking-page panel,
  the live-check command and the Task 10 evaluation runner

## Project structure

```
config/        settings (env-based), URL routing
accounts/      custom User model, registration, sign in/out, permission decorators
bookings/      Service and Booking models, Central Time helpers, booking form, views
guidance/      weather guidance: Open-Meteo client, classification, facts, Ollama
               client, validator, fallback, service, JSON endpoints, live check,
               Task 10 evaluation runner
templates/     base.html (shared layout) plus page templates and the weather panel
static/css/    tokens.css (theme), base.css (elements), components.css (UI parts)
static/js/     guidance-state.js (pure panel logic), guidance.js (panel DOM and fetch)
static/img/    service illustrations (from Bochen Zhang's prototype) and the favicon
docs/          product scope, roadmap, AI documentation, Task 10 protocol, A3 first
               draft, team update and handoff, implementation plans
```

### Data model

```
User (accounts.User) 1 ──< Booking >── 1 Service
```

- **Service:**
  - `name` and `slug` are unique.
  - `price` must be zero or more, enforced by a database constraint.
  - `weather_sensitivity` is exterior, interior or mixed. The weather guidance uses it.
  - Other fields: `description`, `is_active`, `display_order`.
- **Booking:**
  - `customer` is a foreign key to User. Deleting a customer also deletes their bookings.
  - `service` is a foreign key to Service. A service that has bookings cannot be deleted.
  - Other fields: `date`, `time`, `status` (Saved or Cancelled), `created_at`, `updated_at`.
  - `price_at_booking` is a copy of the service price taken when the booking is created. If the service price changes later, the booking's estimated value stays correct.
  - References such as `DW-0001` are generated from the primary key and not stored.

The weather guidance stores nothing in the database. Forecasts and accepted AI
replies are cached in memory for 30 minutes.

### Booking rules enforced on the server

- Bookings are compared with the current time in **Central Time
  (America/Chicago)**, using the full date and time. A time earlier today is
  rejected even if the date is today. The weather endpoints apply the same rule.
- Times that don't exist on a daylight-saving change day are rejected. For
  example, 2:30 AM on the second Sunday of March. The repeated 1:00–1:59 AM
  hour in November is accepted and treated as the first occurrence.
- Only active services can be booked.
- The customer is always the signed-in user. The browser can't choose the
  customer or the price.
- Staff accounts cannot create or list customer bookings. They get a 403 error.
- "Saved" means the request is recorded. **It does not confirm shop capacity.**
  Time-slot availability is outside the project scope.

## Scope notes and next steps

- Booking edit/cancel and the staff dashboard with CSV export are the next
  features (see [the roadmap](docs/roadmap.md)). Until then, staff manage
  bookings in the Django admin.
- **AI:** the validator is rule-based, so it catches known kinds of error but
  cannot prove that an accepted reply is correct. Running the model needs
  about 6 GB of free memory. Measured so far, all on one laptop: the first live
  call through the app (with about 0.4 GB free) timed out after 45 seconds and
  fell back to standard guidance; a later controlled run was accepted in about
  11.3 s; in the five-case Task 10 evaluation, model calls took 11.1–11.7 s
  after an 18.2 s first call that included loading the model. (Two planning
  probes before the app was built took 13–23 s.) These few runs are not a
  reliability rate or a performance guarantee. Per-user rate limiting of the
  explanation endpoint
  is planned before public deployment. The AI works wherever the Django server
  can reach a running model. Details:
  [docs/ai_plan.md](docs/ai_plan.md#14-known-limitations).
- The visual design follows Bochen Zhang's team-approved prototype, applied through
  the tokens in `static/css/tokens.css`. Headings use installed condensed system
  fonts (Arial Narrow where available) because the prototype's embedded font has
  an unverified web licence; they look slightly different on machines without it.
- There is no password reset. This matches wireframe S02.
- The app currently runs locally; hosting and Postgres are planned for the
  final submission. `python manage.py check --deploy` (run with `DJANGO_DEBUG=False`) reports four
  production settings to configure before going live: W004 (HSTS,
  `SECURE_HSTS_SECONDS`), W008 (`SECURE_SSL_REDIRECT`), W012
  (`SESSION_COOKIE_SECURE`) and W016 (`CSRF_COOKIE_SECURE`). These are HTTPS
  hosting requirements, not faults in the local development app, which runs
  over plain HTTP. Set them once the HTTPS host is chosen; do not enable HSTS
  before HTTPS works.
