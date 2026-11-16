# Local demo checklist

The selected setup is local Django, SQLite and optional local Ollama.
PostgreSQL support stays inactive and cloud deployment is postponed. This is
a checklist of expected behavior, not a claim that a live demonstration has
passed. Record actual observations separately, including any unavailable
network/model/chart dependency.

The [November 16 integration review](integration_review.md) records completed
automated and HTTP checks, the limited browser observation and remaining
manual checks. It does not mark the unchecked items below as completed.

## Prepare

- [ ] Follow the README's local setup with `DJANGO_DEBUG=True`,
  `DJANGO_DB_ENGINE=sqlite`, a generated secret and local allowed hosts. Keep
  the existing `.env`; do not display or commit secrets.
- [ ] Use designated demo customer/staff accounts and demo bookings. The
  customer steps create and change records. Do not delete a shared SQLite
  database or reset quota rows to prepare the demo.
- [ ] Apply required migrations in the intended demo database with
  `python manage.py migrate`; the explanation quota requires its migration.
  Use an existing authorized staff account, or create a demo administrator
  with `python manage.py createsuperuser` in that demo database.
- [ ] Run `python manage.py check`, then `python manage.py test --noinput`
  under the local configuration. Tests use temporary databases; record the
  result and any skips instead of reusing historical counts.
- [ ] Start `python manage.py runserver` and open
  `http://127.0.0.1:8000/`. Select a future appointment in Central Time within
  the next 15 days for the weather demonstration.
- [ ] If demonstrating live AI, confirm local Ollama and `llama3` are already
  available and enough memory is free. Otherwise demonstrate the fallback.
  Live weather needs Open-Meteo access; chart rendering needs jsDelivr access.

## Customer workflow

- [ ] **Catalog:** confirm the three active service cards and listed prices
  (Exterior Wash $35, Interior Clean $60, Full Detail $95, unless demo data has
  deliberately changed). Select a service and confirm it survives sign-in.
- [ ] **Register/sign in:** create a customer account, confirm registration
  sends you to sign-in rather than signing in automatically, then sign in.
  Staff-only dashboard navigation should not appear for this customer.
- [ ] **Create:** choose an active service and a future Central Time date/time.
  Save the booking; confirm the success message, reference, saved price and
  entry under Upcoming in My Bookings. "Saved" does not confirm shop capacity.
- [ ] **Edit:** open the detail page and choose **Edit booking**. Confirm the
  fields are prefilled. Change date/time and save; the reference and saved
  price stay the same. Change the service and confirm its current listed
  price is used. An invalid/past appointment must not replace the saved data.
- [ ] **Cancel:** use **Cancel booking** on a designated demo booking. Confirm
  its status becomes Cancelled and it moves to history without being deleted.
  Past/cancelled records should have no edit/cancel controls.
- [ ] **Access:** with a second customer account, opening the first customer's
  booking should show "Booking not found". Sign-out should return to the catalog.

## Weather and optional AI

- [ ] On the create or edit form, choose a service/date/time. Confirm weather
  corresponds to that selection, or that an unavailable forecast is shown
  without preventing booking changes.
- [ ] Choose **Explain this forecast** once. Record whether the panel reports
  **AI explanation**, **Standard guidance**, or an unavailable result. A
  fallback is not evidence of a successful live model explanation.
- [ ] Confirm the four guidance sections when a forecast is available, and
  confirm the booking controls remain usable while guidance is unavailable.
  Change a selection and confirm old guidance is not shown as current.

## Staff reporting and CSV

- [ ] Sign in as staff and open **Dashboard** at `/staff/`. Confirm total,
  upcoming, cancelled and estimated-revenue figures against demo bookings.
  Revenue excludes cancellations and uses saved prices; it is not payment.
- [ ] Check **Booking trends** and **Service popularity**, then expand their
  data tables. Charts include cancelled bookings; dates without bookings are
  omitted. If CDN scripts fail, record that and use the available tables.
- [ ] Apply a range containing a known appointment, then a single-day range,
  an open-ended range and an empty range. Dates are inclusive and refer to
  appointments in Central Time. A reversed range should show validation errors.
- [ ] Use **Export bookings CSV** after applying a range. Check the same
  records are included, with reference, service, date, time, status and price;
  there should be no customer details. Empty results should export headers only.
- [ ] As a customer, direct access to `/staff/` and `/staff/bookings.csv` should
  return 403. When signed out, these URLs should redirect to sign-in.

## AI request limit

- [ ] Use a designated customer with a known quota history. The default is
  **5 valid explanation requests in a rolling 600-second window**; earlier
  explanations in this checklist count. Do not change the configured policy
  or clear quota rows to manufacture a result.
- [ ] For a manual check, submit valid explanation requests sequentially,
  changing a future appointment time between requests if needed to make a new
  UI request. Cache hits and fallbacks count too. After the quota is used, the
  next request should show a wait message; the response is HTTP 429 with
  `Retry-After`. Do not repeatedly retry while the wait is active.
- [ ] Confirm forecast selection and booking saves still work while limited.
  After the indicated wait, a manual explanation request can be admitted again.
- [ ] For a repeatable check without real model/network calls, run
  `python manage.py test guidance.tests.test_rate_limit --noinput`. These tests
  verify quota behavior but are not a live AI demonstration.

Keep observations separate from the preserved November 12 AI experiments.
Note the date, runtime, scenarios checked, actual outcomes and any skips;
never include passwords, secret keys or customer data in shared evidence.
