# DetailWise: Development Roadmap (draft)

*Draft prepared November 8, 2026. The first draft (P2-A3) is due November 9.
The final version (P2-A4) is due December 8.*

**Primary developer for the core Django implementation and integration:
Tejas Jaggi (tejasj2).**

Assignments marked **Proposed** have not yet been confirmed by the team. Each
proposed contribution is technical and can be checked independently (code,
tests or data work in the repository).

| Task | Current status | Responsible member | Expected completion |
|---|---|---|---|
| **Django core features:** project setup, custom user, registration, sign-in and sign-out, catalog, booking creation, My Bookings, booking detail, ownership checks | Done for the first draft (tested, see README) | Tejas Jaggi | Nov 8 |
| **Django core features:** edit booking and cancel booking (status change) with ownership and past-booking rules | Not started | Tejas Jaggi | Nov 16 |
| **Database and APIs:** Service and Booking models, constraints, indexes, seed migration | Done | Tejas Jaggi | Nov 8 |
| **Database and APIs:** staff-only JSON summary endpoint and CSV export with date-range filter | Not started | Tejas Jaggi (integration). *Proposed:* Yidan Huang writes and tests the aggregation queries (date range, Saved only, estimated value) | Nov 22 |
| **Database and APIs:** staff dashboard page with Vega-Lite charts | Not started | Tejas Jaggi (integration). *Proposed:* Bochen Zhang builds the Vega-Lite chart specs and tests the dashboard views | Nov 25 |
| **AI integration:** `guidance` app with Open-Meteo client (timeouts, caching, missing-forecast handling) | Not started (API checked manually: HTTP 200, 16-day horizon, Central Time) | Tejas Jaggi. *Proposed:* Sky Guo writes the forecast parser and its failure-case tests | Nov 18 |
| **AI integration:** LLM explanation with a provider layer, grounded prompt, output validation and template fallback | Not started. Provider and model not chosen | Tejas Jaggi. *Proposed:* Sky Guo compares hosted and local models for the model-selection rationale | Nov 25 |
| **Evaluation and testing:** unit and integration tests for Django features | 85 automated tests passing for the current features | Tejas Jaggi. *Proposed:* Bochen Zhang reviews pull requests and adds tests | Ongoing |
| **Evaluation and testing:** AI evaluation (5+ realistic cases, 2 failure analyses, 1 before-and-after improvement) | Not started | Tejas Jaggi. *Proposed:* Sky Guo runs and records the evaluation cases | Dec 2 |
| **Deployment:** hosting (Render or PythonAnywhere), Postgres, production settings, secrets management | Not started. Platform not chosen | Tejas Jaggi | Dec 4 |
| **Deployment:** cost comparison (self-hosted vs hosted AI) and scaling discussion for 10,000 daily users | Not started | Tejas Jaggi. *Proposed:* Yidan Huang drafts the cost table from measured latency and usage | Dec 5 |
| **Documentation:** README, product scope, roadmap | Draft done | Tejas Jaggi | Nov 9 |
| **Documentation:** `README_AI.md` (models, rationale, workflow, limitations, safety) and 3-minute demo video | Not started | Tejas Jaggi, with contributions from the AI work above | Dec 7 |

## Open decisions for the team

1. The final visual direction. The current theme is provisional: Bochen's layout with Lucy Moon's cyan and magenta accents.
2. The AI provider and model, and who holds the API key and budget.
3. The GitHub repository owner and visibility, and instructor access.
4. The hosting platform.
5. Confirming or changing the proposed assignments above.
