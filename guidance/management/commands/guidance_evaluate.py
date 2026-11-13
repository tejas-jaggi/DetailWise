"""``manage.py guidance_evaluate``: the Task 10 fixed-facts evaluation (docs/task10_evaluation.md).

    python manage.py guidance_evaluate                    # dry run: build and show the cases
    python manage.py guidance_evaluate --live             # five-case Task 10 baseline
    python manage.py guidance_evaluate --live --cases A B # diagnostic subset (not the baseline)

Without ``--live`` nothing calls the model or the network and nothing is written.

With ``--live`` the command refuses to start, before any model call and without
writing anything, unless all of these hold, checked in this order:

1. the Ollama endpoint is this machine (the protocol requires local execution,
   and the memory check below measures this machine);
2. free memory could be measured (an unknown amount refuses: fail closed);
3. free memory is at least ``--min-free-gb`` (default 6);
4. Ollama answers ``GET /api/version``;
5. the configured model is installed (``GET /api/tags``; nothing is loaded).

It then runs each requested case once, stops after a timeout (the protocol's
stop rule), records free memory again, and writes one new JSON results file
(never overwriting an existing one).

Exit status: 0 the requested cases all ran; 1 refused to start; 2 invalid
arguments; 3 stopped by the timeout stop rule (the results file is still written).
"""

import argparse
import math
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from guidance import evaluation
from guidance.fallback import format_date, format_time

DEFAULT_OUTPUT_DIR = "eval_results"
DEFAULT_MIN_FREE_GB = 6.0
STOP_RULE_EXIT = 3


def positive_gb(text: str) -> float:
    """A finite memory threshold above zero (rejects 0, negatives, nan and inf)."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number of GB") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite number of GB above 0")
    return value


class Command(BaseCommand):
    help = "Task 10 fixed-facts evaluation. Dry run by default; --live calls the model."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true",
                            help="Actually call the model once per case and save the results.")
        parser.add_argument("--cases", nargs="+", choices=evaluation.ALL_CASE_IDS,
                            help="Only these cases: a diagnostic subset, not the Task 10 "
                                 "baseline (default: all five).")
        parser.add_argument("--output-dir", default=None,
                            help=f"Where results go (default: <project>/{DEFAULT_OUTPUT_DIR}).")
        parser.add_argument("--min-free-gb", type=positive_gb, default=DEFAULT_MIN_FREE_GB,
                            help="Refuse a live run below this much free memory (default 6).")

    def handle(self, *args, **options):
        cases = evaluation.build_all_cases(options["cases"])
        self.show_cases(cases)
        if not options["live"]:
            self.stdout.write("\nDry run: no model calls were made and nothing was written. "
                              "Add --live to run the evaluation.")
            return

        free_before, version, model_info = self.preflight(options["min_free_gb"])
        requested = list(cases)
        metadata = evaluation.run_metadata(version, free_before=free_before,
                                           model_info=model_info,
                                           requested_case_ids=requested)
        scope_text = ("full five-case Task 10 baseline"
                      if metadata["run_scope"] == evaluation.FULL_BASELINE
                      else f"{evaluation.SUBSET_LABEL} (cases {', '.join(requested)})")
        self.stdout.write(f"\nLive run ({scope_text}): model {metadata['model_configured']} "
                          f"-> {metadata['model_resolved']}, Ollama {version}, prompt "
                          f"{metadata['prompt_version']}, timeout {metadata['timeout_s']} s, "
                          f"free memory {free_before:.1f} GB")

        results = evaluation.run_cases(requested)
        metadata["free_memory_gb_after"] = evaluation.available_memory_gb()
        for result in results:
            line = f"{result.case_id}: {result.status}"
            if result.latency_ms is not None:
                line += f" in {result.latency_ms} ms"
            if result.reason_codes:
                line += f" (reasons: {', '.join(result.reason_codes)})"
            elif result.failure_kind:
                line += f" ({result.failure_kind})"
            self.stdout.write(line)

        output_dir = Path(options["output_dir"] or Path(settings.BASE_DIR) / DEFAULT_OUTPUT_DIR)
        path = evaluation.write_results(results, metadata, output_dir)
        summary = evaluation.summarize(results)
        self.stdout.write(f"Saved {path.name} in {output_dir}")
        self.stdout.write(f"Scope: {scope_text}; state: {summary['run_state']}. Counts: "
                          f"{summary['counts']}. Validator acceptance is not semantic "
                          "accuracy; complete each case's human_review.")
        if summary["run_state"] != evaluation.COMPLETE:
            raise CommandError("Stopped after a timeout (stop rule); remaining cases not run.",
                               returncode=STOP_RULE_EXIT)

    def preflight(self, min_free_gb: float):
        """Refuse (exit 1, nothing run or written) unless every live-run condition holds."""
        if not evaluation.endpoint_is_loopback():
            raise CommandError("This evaluation needs Ollama on this machine (a local "
                               "OLLAMA_BASE_URL). Nothing was run.")
        free = evaluation.available_memory_gb()
        if free is None:
            raise CommandError("Free memory could not be measured, so the live run was "
                               "refused (the protocol needs at least "
                               f"{min_free_gb:g} GB). Nothing was run.")
        if free < min_free_gb:
            raise CommandError(f"Only {free:.1f} GB of memory is free; the protocol needs "
                               f"{min_free_gb:g} GB. Nothing was run.")
        version = evaluation.ollama_version()
        if version is None:
            raise CommandError("Ollama did not answer /api/version. Nothing was run.")
        model = settings.GUIDANCE["OLLAMA_MODEL"]
        model_info = evaluation.ollama_model_info(model)
        if model_info is None:
            raise CommandError(f"The configured model {model} is not installed in Ollama "
                               "(nothing is downloaded by this command). Nothing was run.")
        return free, version, model_info

    def show_cases(self, cases):
        self.stdout.write(f"Task 10 fixed cases (reference today: "
                          f"{evaluation.REFERENCE_NOW:%a %b %d, %Y %H:%M} Central)")
        labels = {case.case_id: case.label for case in evaluation.CASES}
        for case_id, facts in cases.items():
            when = format_date(facts.date)
            if facts.time is not None:
                when += f" {format_time(facts.time)}"
            self.stdout.write(
                f"{case_id}: {labels[case_id]} | {facts.service_name} | {when} | "
                f"lead {facts.lead_days} ({facts.confidence}) | rain {facts.rain_level}, "
                f"wind {facts.wind_level}, temperature {facts.temperature_level} | "
                f"outlook {facts.outlook} {list(facts.concerns)} | "
                f"missing {list(facts.missing) or 'none'} | "
                f"facts {evaluation.facts_fingerprint(facts)[:12]}")
