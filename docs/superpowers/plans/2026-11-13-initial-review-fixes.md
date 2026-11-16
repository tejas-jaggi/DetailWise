# Initial Review Fixes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks in order.

**Goal:** Preserve booking selection across header authentication links and describe hourly forecasts accurately.

**Architecture:** Reuse validated authentication context and the existing hourly weather lookup. Keep the current Django views, fallback, and JavaScript state handling.

**Tech Stack:** Django 5.2, Python 3.13, vanilla JavaScript, Node's test runner.

**Spec:** `DetailWise_initial_review.md`, supplied with the repair request on November 13, 2026.

## Constraints and review focus

- Work on `codex/initial-review-fixes` in the current checkout, as requested.
- Keep safe-redirect rejection, selected appointment minutes, and forecast values intact.
- Cover both header switching directions, absent/unsafe `next`, and 10:00/10:30 forecasts.
- Use focused verification; do not download models or change AI fallback behavior.
- The user authorized committing and pushing this branch in the November 13 follow-up. Deployment remains outside scope.

## Task 1: Authentication continuity

- [x] Add failing navigation tests in `accounts/tests.py`, asserting actual header targets and the final preselected booking form after registration/login.
- [x] Append encoded validated `next` in `templates/base.html`; run `accounts` and booking view tests.

## Task 2: Hourly forecast wording

- [x] Update existing JS and fallback expectations before changing production text; observe the expected failures.
- [x] Correct `static/js/guidance-state.js`, `guidance/fallback.py`, `guidance/facts.py` comments, and `docs/ai_plan.md`. Add the provider name to the existing panel subtitle.
- [x] Verify JS, fallback, facts, and panel tests, including unchanged 10:00/10:30 lookup values and appointment times.
- [x] Correct the same wording in `guidance/classify.py` missing-value labels, identified by independent review; verify classification and fallback tests after observing the new regression fail.

## Task 3: Live environment and final verification

- [x] Inspect the existing Ollama installation/model list, then run the diagnostic and browser explanation if the installed model is available. Record any external dependency separately.
- [x] Run Django's system check, the focused regression suite, and `git diff --check`; review the final diff and report tested versus unverified behavior.

## Verification record

- Authentication regression: two expected failures before the header change; all three tests passed afterward.
- First focused batch: 122 Django tests passed, including the 30-test Node subprocess.
- Review follow-up: the missing-hourly-value Recommendation regression failed before the label correction; 129 classification, fallback, service, and endpoint tests passed afterward. These batches overlap and are not a combined unique-test count.
- Django system check and `git diff --check` passed. The full project suite was not run.
- Real browser: Home -> Book Full Detail -> header Register -> header Sign In -> header Register -> registration -> sign-in -> booking form, with Full Detail retained. The real November 14, 10:30 forecast and Standard guidance showed the corrected wording.
- Initial environment dependency: Ollama was reachable, but configured model `llama3` was not installed. The initial diagnostic and browser both used Standard guidance. No model was downloaded and no model configuration changed during the repair.
- Follow-up after user-installed `llama3` (November 13): a real uncached diagnostic for Full Detail, November 14 at 10:30 was accepted in 24,515 ms; an independent browser request was accepted in 11,425 ms and visibly showed AI EXPLANATION. This resolves the missing-model dependency. These two calls verify one scenario, not broad reliability or output accuracy.
