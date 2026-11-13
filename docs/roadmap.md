# DetailWise: Development Roadmap

*Updated November 12, 2026. Team 3: Yidan Huang, Bochen Zhang, Tianze Guo and
Tejas Jaggi.*

**Confirmed course deadlines:** P2-A3 first draft, **November 16, 2026, 11:59 PM**;
P2-A4 final GitHub push and demo video, **December 8, 2026, 11:59 PM**.

**Primary developer for the core Django implementation and integration:
Tejas Jaggi.**

How to read these tables:

- **Status** lists only what is implemented and verified in this repository.
  Test counts come from `python manage.py test` on November 12 (464 tests, OK)
  and `node --test "guidance/tests/js/*.test.mjs"` (29 tests, OK). These tests
  replace the network and the AI model with fixed replies.
- **Proposed** owners and dates have **not** been confirmed by the team. Each
  proposed contribution is technical and can be checked in the repository
  (code, tests or data work).
- **Team to confirm** means nobody is assigned yet.

## Completed

| Task | Status | Responsible member | Completed |
|---|---|---|---|
| **Django core:** project setup, custom user, registration, sign-in/out, catalog, booking creation, My Bookings, booking detail, ownership checks | **Done.** 91 original tests (accounts 24, bookings 67) | Tejas Jaggi | Committed Nov 10 |
| **Database:** Service and Booking models, constraints, seed migration | **Done** | Tejas Jaggi | Committed Nov 10 |
| **APIs:** Open-Meteo forecast integration (timeouts, validation, 30-min cache) | **Done.** Live fetch verified Nov 12 (454 ms) | Tejas Jaggi | By Nov 12 |
| **APIs:** customer-only JSON endpoints for forecast and explanation | **Done** | Tejas Jaggi | By Nov 12 |
| **AI integration:** deterministic facts, Ollama client, validator, fallback, service layer, booking-page panel, live-check command | **Done in code and automated tests** (live measurement is in the next table) | Tejas Jaggi | By Nov 12 |
| **AI integration:** first controlled application-level AI smoke test (one `guidance_check` run on a disposable project copy) | **Done (one run).** Accepted by the validator in about 11.3 s with no fallback; it does not establish reliability or acceptance rates | Tejas Jaggi | Nov 12 |
| **Evaluation:** Task 10 fixed-facts runner (`guidance_evaluate`: five fixed cases, dry run by default, results file per live run; refuses a live run unless Ollama is local, free memory is measured at 6 GB or more and the model is installed; separates the five-case baseline from diagnostic subsets) | **Implemented and tested** with mocked replies; used for the v1 baseline (next row) | Tejas Jaggi | Nov 12 |
| **Evaluation (Task 10):** prompt v1 baseline, one complete run of the five fixed cases | **Done (one run).** Validator acceptance 5 of 5, fallback 0 of 5, median latency 11.4 s; AI-assisted preliminary review done; independent human review pending ([`task10_evaluation.md`](task10_evaluation.md), [review packet](task10_v1_review_packet.md)) | Tejas Jaggi | Nov 12 |
| **Design:** Bochen Zhang's approved prototype applied to every page | **Done.** 11 design-system tests; checked in a browser at 1280 px and 390 px with a simulated model | Tejas Jaggi (design by Bochen Zhang) | Nov 12 |
| **Documentation:** README, AI documentation, product scope, roadmap, A3 first draft, Task 10 protocol, team handoff | **Done for the first draft** | Tejas Jaggi | Nov 12 |

## Remaining before December 8

| Task | Current status | Responsible member | Expected completion |
|---|---|---|---|
| **AI integration:** live AI explanation demonstrated in the browser on the booking page | Planned. The command-line smoke test passed; the first app call (Nov 12) had timed out after 45 s and fallen back. Each attempt needs about 6 GB of free memory | Tejas Jaggi | Team to confirm |
| **Evaluation (Task 10):** human review of the v1 replies, two failure analyses, one measured prompt improvement (v2 on the same five cases) | Planned. v1 baseline done (above); review packet ready; two failure analyses drafted (cases B and C, preliminary); prompt v2 proposed for case B, not implemented; human review and v1/v2 comparison not yet done | *Proposed:* Tianze Guo runs and records the cases | Proposed: Dec 2 |
| **AI integration:** model-selection comparison (local vs one hosted model on latency, cost, privacy) | Local Llama 3 8B chosen and documented in [`ai_plan.md`](ai_plan.md); hosted comparison planned | *Proposed:* Tianze Guo | Proposed: Nov 28 |
| **Django core:** edit and cancel a booking (status change) with ownership and past-booking rules | Planned | Tejas Jaggi | Proposed: Nov 22 |
| **APIs:** staff-only JSON summary and CSV export with a date-range filter | Planned | Tejas Jaggi (integration). *Proposed:* Yidan Huang writes and tests the aggregation queries | Proposed: Nov 25 |
| **APIs:** staff dashboard page with Vega-Lite charts | Planned | Tejas Jaggi (integration). *Proposed:* Bochen Zhang builds the chart specs and tests the dashboard views | Proposed: Nov 28 |
| **Testing:** review changes and add tests for new features | Ongoing | *Proposed:* Bochen Zhang | Ongoing |
| **Deployment:** hosting, Postgres, production settings, secrets | Planned. The hosted server needs its own reachable model or inference provider ([`ai_plan.md` §10](ai_plan.md#10-where-the-model-must-run-deployment)) and the four HTTPS settings from `check --deploy` (W004, W008, W012, W016) | Team to confirm | Proposed: Dec 4 |
| **Deployment:** cost, scalability (10,000 daily users), security and rate-limiting write-up | Limitations documented in [`ai_plan.md` §14](ai_plan.md#14-known-limitations); write-up planned | *Proposed:* Yidan Huang drafts the cost table from measured latency | Proposed: Dec 5 |
| **Presentation:** mid-point video (4 minutes); outline in [`team_update.md`](team_update.md) | Planned | Team to confirm | Course deadline |
| **Documentation:** 3-minute final demo video and final README | Planned | Team to confirm | By Dec 8 (course deadline) |

## Open decisions for the team

1. **Hosting**, and where the model runs for the deployed version.
2. **Confirming or changing** the proposed owners and dates above.

*Decided:* the visual design is Bochen Zhang's prototype, approved by the team
and applied to every page on November 12.
