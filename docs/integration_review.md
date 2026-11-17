# Local integration review — November 16, 2026

The selected runtime is local Django + SQLite + optional local Ollama.
PostgreSQL support remains inactive and cloud deployment is postponed.
This review separates automated/HTTP evidence from the browser checks that
still need a person to complete the [local demo checklist](local_demo.md).

## Automated validation

Environment: Python 3.13.15, Django 5.2.19 and Node.js 26.13.1. Node's directory
was added to the test process's `PATH`. Tests used `DJANGO_READ_DOT_ENV=False`,
`DJANGO_DEBUG=True`, `DJANGO_DB_ENGINE=sqlite`, a temporary generated secret and
Django's temporary test databases.

| Check | Result |
|---|---|
| Focused booking management, staff dashboard, rate-limit, panel and configuration tests | 110 passed in 14.458 s; no skips. |
| `.venv/Scripts/python.exe manage.py test --noinput` | 559 passed in 73.076 s; no skips. |
| `node --test guidance/tests/js/guidance_state.test.mjs` | 32 passed; no skips. |

The JavaScript test subprocess in `guidance/tests/test_panel.py` now explicitly
decodes output with `encoding="utf-8"`. The full suite passed with
`PYTHONUTF8=0` and the Windows cp936/GBK default encoding, without `-X utf8`.
Initial sandbox Node `EPERM` and temporary-directory failures were resolved
by approved reruns; those failures were environment restrictions.

## Browser and live HTTP evidence

The native Edge browser loaded the disposable server's catalog. Accessibility
inspection confirmed service names, prices and navigation. Browser automation
was otherwise unavailable: coordinate geometry and then minimized-window/user-
input guards prevented further interaction. No visual responsive review,
chart rendering, customer workflow or CSV download was verified in a browser.

A separate HTTP smoke run against a disposable SQLite server at
`127.0.0.1:8765` passed registration/login, invalid-input handling, booking
creation/editing/cancellation, ownership, customer/staff permissions, staff
statistics, chart JSON, date filters, CSV content/download headers and logout.
These were HTTP checks, not browser interaction or visual checks.

The forecast endpoint returned `weather_unavailable`; a successful live weather
fetch was not established. Five explanation requests returned unavailable
results, then the sixth returned HTTP 429 with a positive `Retry-After`.
Forecast requests and booking saves remained available after the quota was
reached. The smoke harness deliberately used an unavailable loopback Ollama
URL; no model call or AI evaluation was performed.

## Remaining manual checks and limits

- Complete registration, login, create/edit/cancel and logout in a real browser,
  including narrow/mobile and desktop layouts.
- Verify the Vega charts load from their CDN, display the expected values and
  remain usable at different widths; also check their table fallbacks.
- Download and open the CSV through the browser after applying date filters.
- Verify a real Open-Meteo forecast and, optionally, a local Ollama explanation.
  Record a fallback separately from a successful model response.
- Apply the existing explanation-quota migration in the intended demo database
  before the demo; this review did not migrate the user's local database.

The user's local `db.sqlite3` SHA-256 was unchanged. No real PostgreSQL
connection/migration, HTTPS infrastructure or cloud deployment was verified.
Historical AI experiments remain in [the AI plan](ai_plan.md#13-live-experiment-evidence)
and are not results of this integration review.
