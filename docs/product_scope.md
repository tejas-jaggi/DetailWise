# DetailWise: Updated Product Scope (P2-A3 first draft)

*INFO 490 Project 2, Team 3. Draft prepared November 8, 2026.*

## Product idea

DetailWise is a booking web application for a single car detailing shop in
Urbana, IL. Customers browse three services, create an account and save a
booking for a date and time. Before saving, they will see weather-informed
guidance about whether the forecast suits the service. Shop staff will see
booking trends and export booking data.

## Problem

Small detailing shops often take bookings by phone or text. Customers can't
easily see what is offered or keep track of what they booked. Exterior work is
weather-dependent, so customers often book a wash on a day it rains. The shop
also has no simple view of which services and dates are in demand.

## Target users

- **Customers:** local car owners who want to book a detailing service online and keep track of it.
- **Shop staff:** the owner or employees who want a quick view of booking volume and estimated value.

## Core features

The four features proposed in P2-A2 are grouped into three:

1. **Customer access and service booking.**
   - Implemented:
     - Service catalog.
     - Customer registration, sign-in and sign-out.
     - Booking creation, validated on the server in Central Time.
     - A private My Bookings list and booking detail page.
     - Ownership checks, so customers only ever see their own bookings.
   - Next: edit and cancel a booking (as a status change, not a deletion).
2. **Weather-informed AI guidance.** *(Planned.)*
   - The booking form will fetch an Open-Meteo forecast for the chosen date.
   - Code will turn the forecast into structured facts.
   - A language model will explain those facts in plain English for the chosen service. For example, rain matters for exterior work but not for interior cleaning.
   - The output will be validated, with a template fallback.
   - The guidance never changes or blocks a booking.
3. **Staff analytics and export.** *(Planned.)*
   - A staff-only dashboard with a date-range filter.
   - Totals and Vega-Lite charts by date and by service, fed by internal JSON endpoints.
   - CSV export (`date, service, saved_booking_count, estimated_value`).

## Changes from P2-A2

- The four proposed features are grouped into the three above. Accounts and
  booking form one feature because booking requires an account.
- Accounts use Django's built-in authentication. Google sign-in is postponed and optional.
- The listed price is stored on each booking (`price_at_booking`), so estimated
  values stay correct if a price changes later.
- Each service records whether it is exterior, interior or mixed work. The AI
  guidance will use this instead of hard-coded service names.
- The server checks the full appointment date **and time** against the current
  Central Time. The clickable prototype only checked the date.
- Staff accounts cannot create customer bookings in this version.
- The AI provider and model are not chosen yet. Choosing them is part of the next milestone.

## Scope boundaries (unchanged)

- No payments.
- No time-slot availability or capacity checks. "Saved" means the request is
  recorded, not that capacity is confirmed.
- No employee assignment or schedule optimization.
- No chatbot. The AI only explains the forecast for the selected booking and never changes a booking.
- All times are Central Time (America/Chicago) for one shop in Urbana, IL.
