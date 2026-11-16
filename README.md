# DetailWise

DetailWise is a Django web application for a fictional car detailing shop in
Urbana, IL. Customers browse services, create an account and save bookings.
On the booking page, an optional **weather guidance panel** shows the forecast
for the chosen date and, on request, an AI-written explanation of what it means
for the chosen service. Python computes every number and recommendation, and
every AI reply is validated before a customer sees it.

INFO 490 Project 2, Team 3: Yidan Huang, Bochen Zhang, Tianze Guo and Tejas Jaggi.

**Current integration (November 16, 2026):** the team is using local Django,
SQLite and optional local Ollama. Customer booking edits/cancellation, staff
reporting/CSV and per-customer AI request limits are implemented. PostgreSQL
and production settings remain available but inactive; cloud deployment is
postponed. See the [local demo checklist](docs/local_demo.md) and
[November 16 integration review](docs/integration_review.md) for validation
results and remaining browser checks.

> **Historical snapshot (P2-A3 first draft, November 12, 2026):**
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
> - **Planned at that time:** the human review and prompt comparison, a live AI explanation
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
| Edit and cancel a booking | Implemented for the customer's own saved, future bookings; cancellation retains the record |
| Staff dashboard (Vega-Lite charts, CSV export) | Implemented; see staff reporting below |
| Per-customer AI explanation request limit | Implemented: 5 valid requests per rolling 10-minute window by default; forecasts and booking saves remain available |
| AI evaluation (accepted/fallback rates, failure analysis) | Prompt v1 baseline run Nov 12 on five fixed cases: validator acceptance 5 of 5, fallback 0 of 5, median latency 11.4 s. Human review pending ([review packet](docs/task10_v1_review_packet.md)); prompt v2 proposed, not implemented ([docs/task10_evaluation.md](docs/task10_evaluation.md)) |
| Runtime and deployment | Local Django + SQLite + optional local Ollama. Cloud deployment postponed; PostgreSQL and production configuration retained but inactive ([deployment guide](docs/deployment.md)) |

The workflow is: **Service Catalog → Sign In/Register → Create Booking (with
optional weather guidance) → Database Save → My Bookings**.

## Requirements

- Python **3.13**
- Dependencies, pinned in `requirements.txt`:

  | Package | Purpose |
  |---|---|
  | Django 5.2.19 (LTS) | Web framework |
  | python-dotenv 1.2.1 | Loads settings from a local `.env` file |
  | psycopg[binary] 3.3.9 | PostgreSQL driver, including its binary runtime |
  | WhiteNoise 6.12.0 | Serves collected production static files |
  | Waitress 3.0.2 | Production WSGI server on Windows and Unix |
  | asgiref, sqlparse | Django dependencies |
  | tzdata | Time zone data for `America/Chicago` (needed on Windows) |

  The weather and AI features use only the Python standard library. There is no
  AI SDK and no API key.
- The database defaults to SQLite during development; no database server is needed.
  Production PostgreSQL configuration is described in [the deployment guide](docs/deployment.md).
- **Optional, for AI explanations:** [Ollama](https://ollama.com) and the
  `llama3` model (about 4.7 GB to download; about 6 GB of free memory to run).
  Without it, the app works and shows standard guidance.
- **Optional, for the JavaScript tests:** Node.js 18 or newer (tested with v24).

## Setup

Run these commands from the repository root: the folder that contains
`manage.py` (named `DetailWise` when cloned from GitHub).
If you already have a `.env`, keep it; skip the copy command and add only any
missing settings from `.env.example`.

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
| `DJANGO_DB_ENGINE` | `sqlite` | Default. Use `postgresql` only with the production database variables. |
| `DJANGO_READ_DOT_ENV` | `True` | Default. Existing process variables take precedence; set `False` in production to skip `.env`. |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Optional. Where **the Django server** reaches Ollama. |
| `OLLAMA_MODEL` | `llama3` | Optional. Model name as Ollama knows it. |
| `GUIDANCE_LLM_TIMEOUT` | `45` | Optional. Seconds to wait for the model (whole number, 1 or more). |
| `GUIDANCE_EXPLAIN_LIMIT` | `5` | Maximum valid explanation requests per authenticated customer per rolling window (positive integer). |
| `GUIDANCE_EXPLAIN_WINDOW_SECONDS` | `600` | Rolling-window length in seconds (positive integer). |

`.env` is listed in `.gitignore`. **Never commit it or share it** (for example
in a ZIP of the project, a screenshot or a chat). If it is ever shared,
generate a new `DJANGO_SECRET_KEY`.

Keep `DJANGO_DEBUG=True` for local HTTP development and the existing tests.
With `DJANGO_DEBUG=False` (the default if omitted), the app requires explicit
allowed hosts, enables HTTPS redirects and secure cookies, and uses collected,
hashed static files. HSTS and forwarded-protocol trust remain disabled until
explicitly configured. See [production configuration](docs/deployment.md) for
all environment variables, PostgreSQL setup, proxy requirements and commands.

## Database and seed data

```bash
python manage.py migrate
```

With the local SQLite configuration, this creates `db.sqlite3` and seeds the
three services through a reversible data migration
(`bookings/migrations/0002_seed_services.py`). The service
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
- <http://127.0.0.1:8000/staff/> for reporting and CSV export (staff only)
- <http://127.0.0.1:8000/admin/> for the Django admin (staff only)

Use the [local demo checklist](docs/local_demo.md) to walk through customer,
weather, staff and request-limit behavior.

### Edit or cancel a booking

Open one of your upcoming bookings from **My Bookings**, then choose
**Edit booking** or **Cancel booking**. Only saved appointments that have not
started can be changed. Editing the date or time keeps the stored price;
changing the service uses that service's current listed price. The booking
reference stays the same. Cancellation is a CSRF-protected POST that changes
the status to Cancelled and keeps the record in history; it does not delete it.
Other customers' bookings remain inaccessible, and past or cancelled bookings
cannot be edited or cancelled again.

## Staff reporting

Staff can open **Dashboard** in the navigation, or visit `/staff/`. The existing
staff-only permission decorator protects both this page and `/staff/bookings.csv`.
Customer accounts receive 403; signed-out users are redirected to sign in.

- `start_date` and `end_date` filter **appointment dates in America/Chicago**,
  inclusively. Either bound may be omitted; both blank means all dates.
  Invalid or reversed ranges return 400 with field errors, including on export.
- Total bookings and both charts include cancellations. Upcoming means saved
  appointments strictly after now, following the booking workflow's DST rules.
- Estimated revenue sums saved price snapshots for non-cancelled bookings,
  both past and future. It is not collected payment or confirmed capacity.
- The daily trend omits dates without bookings. Service popularity includes
  inactive services with historical bookings. Dashboard reporting uses three
  aggregate queries, without loading customer records.
- CSV export contains individual booking references, service names, appointment
  dates/times, stored statuses and estimated prices in USD. It uses the same
  filters, includes cancelled records, and contains no customer information.
  Rows stream in appointment order. An empty result exports headers only.
  UTF-8 with a BOM supports Unicode in spreadsheets; CSV quoting handles commas,
  quotes and newlines. Formula-like cells are prefixed with an apostrophe,
  including formulas preceded by whitespace or control characters. That
  protective apostrophe is part of the exported value.
- Reports and exports send private, no-store cache headers.
- Charts use pinned Vega 6.4.0, Vega-Lite 6.5.0 and Vega-Embed 7.3.0 from
  jsDelivr, following the [official embedding documentation](https://vega.github.io/vega-lite/usage/embed.html).
  Chart data is safely embedded using Django's `json_script`; no customer data
  is included. Rendering charts needs access to the CDN. Server-rendered data
  tables remain available if scripts are unavailable or JavaScript is disabled.

Run the reporting tests with:

```bash
python manage.py test bookings.tests.test_staff_dashboard
```

The dashboard embeds its aggregate JSON in the page; it does not add the separate
JSON API previously proposed in the roadmap. CSV is a per-booking export, as
required for this implementation, rather than the older proposed daily summary.

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

### Explanation request limits

`POST /guidance/explain/` permits **5 valid requests per customer per rolling
10-minute window** by default. Configuration uses the two environment variables
above, exposed in Django as `GUIDANCE_RATE_LIMIT` (`REQUESTS`, `WINDOW_SECONDS`).
Authentication, customer permissions, CSRF and form validation run before quota
admission. Limits use the signed-in Django user ID, never an IP or submitted ID.
Invalid requests do not count. All admitted requests count, including cache hits,
unavailable forecasts, model failures and disconnected clients. Denied requests
do not extend the window. Forecast requests and booking saves are unaffected.

When the quota is full, the endpoint returns HTTP **429**, a `Retry-After` header
in whole seconds (rounded up), and JSON with `status: "rate_limited"`, a safe
`message` and numeric `retry_after`. The panel displays the wait and leaves
booking controls usable. It does not automatically retry or start another model
request; the customer can manually request an explanation later.

**Apply the new migration before using this branch:**

```bash
python manage.py migrate
```

The implementation adds `guidance.ExplanationQuota`, one row per requesting
customer, containing only admission timestamps. No booking or model output is
stored there. Expired timestamps are pruned on the next admitted request; the
small last-used history persists while idle and is removed when the user is
deleted. Existing quota history survives application restarts and cache clears.

**Concurrency and deployment:** admission runs inside a short transaction on
the `default` primary database. An UPDATE acquires a write lock before any
history is read: a database write lock on SQLite, a row lock on PostgreSQL.
The window uses database statement time after acquiring that lock, avoiding
clock differences between application instances. Unique user keys also protect
simultaneous first requests. Model/network work runs after the transaction commits,
including when `ATOMIC_REQUESTS` is enabled. Bounded jittered retries handle SQLite
lock contention; storage errors return safe HTTP **503** without calling the model.

No Redis or additional dependency is required. Multi-process and multi-instance
deployment requires **all instances to share the same transactional primary
database and policy settings**, preferably PostgreSQL with Django's default
READ COMMITTED isolation. Reads are explicitly pinned to `default`, not replicas.
Separate SQLite files per instance, read replicas for quota state, or per-process
caches cannot enforce a shared quota. SQLite is suitable for local development
but serializes writers and may return 503 under contention. Automated concurrency
tests use independent SQLite connections; PostgreSQL deployment/load testing is
still required before production. Do not clear quota rows during deployments.

This is a per-user admission limit, not a global model queue: five simultaneous
requests from one customer can still be admitted, and many different customers
can collectively load the model. Operator CLI evaluation/live-check commands
and direct service calls are outside this HTTP endpoint policy. Changing the
window length cannot recover timestamps already pruned under an older policy.

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
python manage.py guidance_check --service exterior-wash --date YYYY-MM-DD --time 10:00
python manage.py guidance_check --service interior-clean --date YYYY-MM-DD --runs 3
```

Replace `YYYY-MM-DD` with a future appointment date within the next 15 days
(Central Time); the forecast and past-time rules apply to this command too.

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

Use the local configuration (`DJANGO_DEBUG=True`, `DJANGO_DB_ENGINE=sqlite`).
This keeps HTTP requests and static URLs consistent with the existing tests.

```bash
python manage.py check
python manage.py test config
python manage.py test
node --test "guidance/tests/js/*.test.mjs"
```

The Django tests use a temporary test database built from the real migrations,
seed data included. **No test uses the network or a real AI model**: Open-Meteo
and Ollama are replaced with fixed replies. The JavaScript tests run in Node
with no packages to install, and also run inside the Django suite when Node is
installed. The tests cover:

- Models, constraints and seed migration reversibility
- Database selection, production security configuration and static-file delivery
- Central Time and daylight saving time (DST) validation
- Registration, sign-in and sign-out, and permissions
- The catalog, booking creation/editing/cancellation, My Bookings and ownership
- Staff statistics, chart data, date filters, permissions and CSV export
- Per-customer explanation quotas, expiry, storage failures and concurrent admission
- The forecast client, classification rules, exact-date facts and DST hours
- The AI client's request and every failure type, the validator, the fallback,
  the service layer and its cache, the JSON endpoints, the booking-page panel,
  the live-check command and the Task 10 evaluation runner

## Project structure

```
config/        settings (env-based), URL routing, configuration tests
accounts/      custom User model, registration, sign in/out, permission decorators
bookings/      Service and Booking models, Central Time helpers, booking form, views
guidance/      weather guidance: Open-Meteo client, classification, facts, Ollama
               client, validator, fallback, service, JSON endpoints, live check,
               Task 10 evaluation runner
templates/     base.html (shared layout) plus page templates and the weather panel
static/css/    tokens.css (theme), base.css (elements), components.css (UI parts)
static/js/     guidance-state.js (pure panel logic), guidance.js (panel DOM and fetch)
static/img/    service illustrations (from Bochen Zhang's prototype) and the favicon
docs/          deployment guide, product scope, roadmap, AI documentation, Task 10 protocol, A3 first
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

Weather forecasts and AI output are not stored in the database. Forecasts and
accepted AI replies are cached in memory for 30 minutes. Explanation admission
timestamps are stored separately in `ExplanationQuota` for per-user rate limiting.

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

- Booking edit/cancel, staff reporting and CSV export are implemented. The
  [local demo checklist](docs/local_demo.md) covers their integrated workflow;
  staff can also manage records in the Django admin.
- **AI:** the validator is rule-based, so it catches known kinds of error but
  cannot prove that an accepted reply is correct. Running the model needs
  about 6 GB of free memory. Measured so far, all on one laptop: the first live
  call through the app (with about 0.4 GB free) timed out after 45 seconds and
  fell back to standard guidance; a later controlled run was accepted in about
  11.3 s; in the five-case Task 10 evaluation, model calls took 11.1–11.7 s
  after an 18.2 s first call that included loading the model. (Two planning
  probes before the app was built took 13–23 s.) These few runs are not a
  reliability rate or a performance guarantee. Per-user rate limiting of the
  explanation endpoint is implemented; see deployment requirements above.
  The AI works wherever the Django server
  can reach a running model. Details:
  [docs/ai_plan.md](docs/ai_plan.md#14-known-limitations).
- The visual design follows Bochen Zhang's team-approved prototype, applied through
  the tokens in `static/css/tokens.css`. Headings use installed condensed system
  fonts (Arial Narrow where available) because the prototype's embedded font has
  an unverified web licence; they look slightly different on machines without it.
- There is no password reset. This matches wireframe S02.
- The selected runtime is local Django with SQLite and optional local Ollama.
  Cloud deployment is postponed. PostgreSQL selection, HTTPS settings,
  WhiteNoise and Waitress are retained for future deployment, but PostgreSQL
  is inactive and no live PostgreSQL/HTTPS deployment is established.
  HSTS stays off until HTTPS is verified; subdomain
  coverage and preload require separate deployment decisions. See the
  [deployment guide](docs/deployment.md) for expected security warnings and
  the remaining steps. This configuration does not transfer or modify the
  existing local SQLite database.
