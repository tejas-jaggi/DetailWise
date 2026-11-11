# DetailWise

DetailWise is a Django web application for a fictional car detailing shop in
Urbana, IL. Customers browse services, create an account and save bookings.
Later milestones add weather-informed AI booking guidance and a staff analytics
dashboard.

INFO 490 Project 2, Team 3: Sky (Tianze) Guo, Yidan Huang, Tejas Jaggi, Bochen Zhang.

> **Status (first-draft milestone, November 8, 2026):** the customer booking
> workflow runs on the server and saves to the database. The AI guidance and
> staff dashboard are **planned and not implemented yet**. See
> [Current limitations](#current-limitations).

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
| Edit and cancel a booking | Planned (next milestone) |
| Weather forecast (Open-Meteo) and AI explanation | Planned |
| Staff dashboard (Vega-Lite charts, CSV export) | Planned |
| Deployment | Planned |

The workflow is: **Service Catalog → Sign In/Register → Create Booking → Database Save → My Bookings**.

## Requirements

- Python **3.13**
- Dependencies, pinned in `requirements.txt`:

  | Package | Purpose |
  |---|---|
  | Django 5.2.19 (LTS) | Web framework |
  | python-dotenv 1.2.1 | Loads settings from a local `.env` file |
  | asgiref, sqlparse | Django dependencies |
  | tzdata | Time zone data for `America/Chicago` (needed on Windows) |

- The database is SQLite during development. Nothing needs installing.

## Setup

Run these commands from the `detailwise/` folder.

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

`.env` is listed in `.gitignore`. **Never commit it.**

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
- <http://127.0.0.1:8000/bookings/> for My Bookings (sign-in required)
- <http://127.0.0.1:8000/admin/> for the Django admin (staff only)

## Run the tests

```bash
python manage.py test
```

The tests use a temporary test database built from the real migrations, seed
data included. They cover:

- Models and constraints
- Seed migration reversibility
- Central Time and daylight saving time (DST) validation
- Registration, sign-in and sign-out
- Permissions
- The catalog, booking creation, My Bookings and booking ownership

## Project structure

```
config/        settings (env-based), URL routing
accounts/      custom User model, registration, sign in/out, permission decorators
bookings/      Service and Booking models, Central Time helpers, booking form, views
templates/     base.html (shared layout) plus page templates
static/css/    tokens.css (theme), base.css (elements), components.css (UI parts)
docs/          product scope, roadmap, implementation plan
```

### Data model

```
User (accounts.User) 1 ──< Booking >── 1 Service
```

- **Service:**
  - `name` and `slug` are unique.
  - `price` must be zero or more, enforced by a database constraint.
  - `weather_sensitivity` is exterior, interior or mixed.
  - Other fields: `description`, `is_active`, `display_order`.
- **Booking:**
  - `customer` is a foreign key to User. Deleting a customer also deletes their bookings.
  - `service` is a foreign key to Service. A service that has bookings cannot be deleted.
  - Other fields: `date`, `time`, `status` (Saved or Cancelled), `created_at`, `updated_at`.
  - `price_at_booking` is a copy of the service price taken when the booking is created. If the service price changes later, the booking's estimated value stays correct.
  - References such as `DW-0001` are generated from the primary key and not stored.

### Booking rules enforced on the server

- Bookings are compared with the current time in **Central Time
  (America/Chicago)**, using the full date and time. A time earlier today is
  rejected even if the date is today.
- Times that don't exist on a daylight-saving change day are rejected. For
  example, 2:30 AM on the second Sunday of March. The repeated 1:00–1:59 AM
  hour in November is accepted and treated as the first occurrence.
- Only active services can be booked.
- The customer is always the signed-in user. The browser can't choose the
  customer or the price.
- Staff accounts cannot create or list customer bookings. They get a 403 error.
- "Saved" means the request is recorded. **It does not confirm shop capacity.**
  Time-slot availability is outside the project scope.

## Current limitations

- Customers can't edit or cancel bookings yet. Staff can change bookings in the Django admin.
- No weather data and no AI guidance yet. Nothing in the app calls an AI model.
- No staff dashboard or CSV export yet. After signing in, staff are sent to the catalog.
- The visual theme in `static/css/tokens.css` is **provisional**. The team has not chosen a final design.
- There is no password reset. This matches wireframe S02.
- The app runs locally only. Deployment and Postgres come later.

## Planned AI functionality (not implemented)

A future `guidance` app will add weather-informed booking guidance to the
booking form:

```
Booking context (service, date, time)
  → Open-Meteo forecast (server side, no API key)
  → structured weather facts computed in code (rain probability, temperature, lead time)
  → LLM writes a short explanation from those facts only
  → output validation (no invented numbers, no certainty claims, no booking changes)
  → shown next to the booking form, with a template-text fallback on any failure
```

The AI will never change a booking and will never block a valid save. The AI
provider and model have **not** been chosen yet. See `docs/roadmap.md`.
