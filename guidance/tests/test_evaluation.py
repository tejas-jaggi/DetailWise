"""Tests for the Task 10 fixed-facts evaluation runner (docs/task10_evaluation.md).

No test calls a real model or the network: ``guidance.llm.urlopen`` (model
calls) and ``guidance.evaluation.urlopen`` (Ollama version probe) are patched
in every test that could reach them, and the import/dry-run tests patch both to
fail loudly.
"""

import datetime
import importlib
import io
import json
import socket
import tempfile
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from django.conf import settings as django_settings
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from guidance import evaluation, llm

SECRET = "http://10.0.0.5:11434 internal-host-detail"
CASE_IDS = ("A", "B", "C", "D", "E")


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns (a readable context manager)."""


def ollama_reply(output=None, content=None):
    content = json.dumps(output) if content is None else content
    body = {"model": "llama3", "done": True, "message": {"role": "assistant", "content": content}}
    return FakeResponse(json.dumps(body).encode("utf-8"))


def valid_output(facts, **changes):
    """A reply the validator accepts for case A (peak and hour rain are both 10%)."""
    output = {field: getattr(facts, field) for field in
              ("rain_level", "wind_level", "temperature_level", "confidence", "outlook")}
    output.update(summary="The highest hourly rain probability on this date is 10%.",
                  service_explanation="Rain can make an exterior wash dirty again sooner.",
                  uncertainty_note="")
    output.update(changes)
    return output


def fake_ollama_api(version="0.30.6", models=("llama3:latest",)):
    """A side_effect for guidance.evaluation.urlopen serving /api/version and /api/tags."""
    def respond(request, timeout=None):
        url = request.full_url
        if url.endswith("/api/version"):
            return FakeResponse(json.dumps({"version": version}).encode())
        if url.endswith("/api/tags"):
            entries = [{"name": name, "digest": "365c0bd3c000a25d28ddbf732fe1c6ad",
                        "size": 4661224676,
                        "details": {"parameter_size": "8.0B", "quantization_level": "Q4_0",
                                    "family": "llama"}} for name in models]
            return FakeResponse(json.dumps({"models": entries}).encode())
        raise AssertionError(f"unexpected Ollama endpoint {url}")
    return respond


def no_network():
    """Patch both network entry points to fail loudly if anything calls them."""
    return (mock.patch("guidance.llm.urlopen", side_effect=AssertionError("model called")),
            mock.patch("guidance.evaluation.urlopen", side_effect=AssertionError("network used")))


class CaseConstructionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cases = evaluation.build_all_cases()

    def test_exactly_the_five_documented_cases(self):
        self.assertEqual(tuple(self.cases), CASE_IDS)
        self.assertEqual([c.case_id for c in evaluation.CASES], list(CASE_IDS))

    def test_documented_inputs_are_preserved(self):
        expected = {  # service, lead days, time, peak rain, hour rain, low, high, wind
            "A": ("Exterior Wash", 1, datetime.time(10), 10, 10, 52, 72, 8),
            "B": ("Exterior Wash", 1, datetime.time(10), 70, 10, 50, 68, 8),
            "C": ("Interior Clean", 1, None, 90, None, 65, 85, 32),
            "D": ("Full Detail", 7, None, None, None, None, 72, 8),
            "E": ("Exterior Wash", 7, None, 20, None, 30, 45, 22),
        }
        for case_id, values in expected.items():
            f = self.cases[case_id]
            with self.subTest(case=case_id):
                self.assertEqual((f.service_name, f.lead_days, f.time, f.peak_rain_chance_pct,
                                  f.appt_rain_chance_pct, f.temp_low_f, f.temp_high_f,
                                  f.wind_max_mph), values)

    def test_approved_completion_values(self):
        # Values approved on Nov 12 to complete the protocol (precipitation, gusts,
        # A/B appointment-hour temperature and wind); none of them changes a class.
        expected = {"A": (0.0, 14, 60, 6), "B": (0.12, 15, 56, 6), "C": (0.35, 41, None, None),
                    "D": (0.0, 14, None, None), "E": (0.01, 31, None, None)}
        for case_id, values in expected.items():
            f = self.cases[case_id]
            with self.subTest(case=case_id):
                self.assertEqual((f.precipitation_in, f.gust_max_mph, f.appt_temp_f,
                                  f.appt_wind_mph), values)

    def test_classes_match_the_protocol(self):
        expected = {  # rain, wind, temperature, outlook, concerns, confidence
            "A": ("low", "light", "mild", "favorable", (), "higher"),
            "B": ("likely", "light", "mild", "concerns", ("rain",), "higher"),
            "C": ("very likely", "very windy", "warm", "weather_minor", ("rain", "wind"), "higher"),
            "D": ("unknown", "light", "unknown", "incomplete", (), "lower"),
            "E": ("possible", "windy", "freezing risk", "concerns", ("wind", "freezing"), "lower"),
        }
        for case_id, values in expected.items():
            f = self.cases[case_id]
            with self.subTest(case=case_id):
                self.assertEqual((f.rain_level, f.wind_level, f.temperature_level, f.outlook,
                                  f.concerns, f.confidence), values)

    def test_missing_values_stay_missing(self):
        d = self.cases["D"]
        self.assertEqual(d.missing, ("temp_low_f", "peak_rain_chance_pct"))
        prompt = d.as_prompt_dict()
        self.assertNotIn("low_temperature_f", prompt)
        self.assertNotIn("peak_hourly_rain_probability_pct", prompt)
        self.assertEqual(prompt["not_available"], ["low temperature", "peak hourly rain probability"])
        for case_id in ("A", "B", "C", "E"):
            with self.subTest(case=case_id):
                self.assertEqual(self.cases[case_id].missing, ())

    def test_daily_only_cases_have_no_appointment_hour_values(self):
        for case_id in ("C", "D", "E"):
            prompt = self.cases[case_id].as_prompt_dict()
            with self.subTest(case=case_id):
                self.assertNotIn("appointment_time", prompt)
                self.assertFalse(any(key.startswith("appointment_hour") for key in prompt))

    def test_dates_are_pinned_to_the_reference_day(self):
        self.assertEqual(evaluation.REFERENCE_NOW.isoformat(), "2026-11-16T09:00:00-06:00")
        self.assertEqual(self.cases["A"].date, datetime.date(2026, 11, 17))
        self.assertEqual(self.cases["E"].date, datetime.date(2026, 11, 23))

    def test_facts_do_not_depend_on_the_real_date(self):
        later = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=later):
            rebuilt = evaluation.build_all_cases()
        for case_id in CASE_IDS:
            with self.subTest(case=case_id):
                self.assertEqual(rebuilt[case_id], self.cases[case_id])

    def test_building_restores_the_real_clock(self):
        from bookings import timeutils
        from guidance import facts
        evaluation.build_all_cases()
        self.assertIs(facts.central_now, timeutils.central_now)


class SameFactsTests(SimpleTestCase):
    def test_same_facts_sent_for_every_prompt_version(self):
        facts = evaluation.build_all_cases()["B"]
        v1_user = llm.build_messages(facts)[1]
        with mock.patch.object(llm, "PROMPT_VERSION", "v2"):
            v2_user = llm.build_messages(evaluation.build_all_cases()["B"])[1]
        self.assertEqual(v1_user, v2_user)

    def test_fingerprint_is_of_exactly_what_the_model_receives(self):
        import hashlib
        for case_id, facts in evaluation.build_all_cases().items():
            sent = json.loads(llm.build_messages(facts)[1]["content"])
            expected = hashlib.sha256(json.dumps(sent, sort_keys=True).encode("utf-8")).hexdigest()
            with self.subTest(case=case_id):
                self.assertEqual(evaluation.facts_fingerprint(facts), expected)

    def test_memory_probe_returns_a_plausible_number_or_none(self):
        free = evaluation.available_memory_gb()  # reads the OS only; no network
        self.assertTrue(free is None or 0 < free < 4096)

    def test_facts_fingerprint_is_stable_and_case_specific(self):
        first = {cid: evaluation.facts_fingerprint(f) for cid, f in evaluation.build_all_cases().items()}
        second = {cid: evaluation.facts_fingerprint(f) for cid, f in evaluation.build_all_cases().items()}
        self.assertEqual(first, second)
        self.assertEqual(len(set(first.values())), 5)
        self.assertRegex(first["A"], r"^[0-9a-f]{64}$")


class RunCaseTests(SimpleTestCase):
    def setUp(self):
        self.facts = evaluation.build_all_cases()["A"]

    def run_with(self, **patch_kwargs):
        with mock.patch("guidance.llm.urlopen", **patch_kwargs):
            return evaluation.run_case("A", self.facts)

    def test_accepted_reply(self):
        result = self.run_with(return_value=ollama_reply(valid_output(self.facts)))
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.reason_codes, [])
        self.assertIsNone(result.failure_kind)
        self.assertEqual(result.model_output["summary"],
                         "The highest hourly rain probability on this date is 10%.")
        self.assertEqual(result.facts_sha256, evaluation.facts_fingerprint(self.facts))

    def test_validator_rejection_records_reason_codes(self):
        reply = valid_output(self.facts, summary="We guarantee a dry day; apply a ceramic coating.")
        result = self.run_with(return_value=ollama_reply(reply))
        self.assertEqual(result.status, "rejected")
        self.assertIn("certainty", result.reason_codes)
        self.assertIn("advice", result.reason_codes)

    def test_timeout(self):
        result = self.run_with(side_effect=socket.timeout("timed out"))
        self.assertEqual((result.status, result.failure_kind), ("timeout", "timeout"))
        self.assertIsNone(result.model_output)

    def test_model_unavailable(self):
        for error, kind in ((URLError(ConnectionRefusedError(10061, "refused")), "unreachable"),
                            (HTTPError("http://x/api/chat", 404, "Not Found", {}, None), "http")):
            with self.subTest(kind=kind):
                result = self.run_with(side_effect=error)
                self.assertEqual((result.status, result.failure_kind), ("model_unavailable", kind))

    def test_malformed_reply_is_a_parse_failure(self):
        for content in ("not json", "", "[]"):
            with self.subTest(content=content):
                result = self.run_with(return_value=ollama_reply(content=content))
                self.assertEqual((result.status, result.failure_kind), ("parse_failure", "malformed"))

    def test_latency_is_the_model_call_duration(self):
        with mock.patch("guidance.evaluation.clock.monotonic", side_effect=[100.0, 101.25]):
            result = self.run_with(return_value=ollama_reply(valid_output(self.facts)))
        self.assertEqual(result.latency_ms, 1250)

    def test_rejected_output_is_sanitized(self):
        reply = valid_output(self.facts, summary="Guaranteed\x00 dry\u200b day " + "x" * 2000,
                             extra_field="should not be stored")
        reply["wind_level"] = 7  # not a string
        result = self.run_with(return_value=ollama_reply(reply))
        self.assertEqual(result.status, "rejected")
        self.assertNotIn("extra_field", result.model_output)
        self.assertNotIn("wind_level", result.model_output)
        self.assertNotIn("\x00", result.model_output["summary"])
        self.assertLessEqual(len(result.model_output["summary"]), evaluation.MAX_STORED_CHARS)


class RunCasesTests(SimpleTestCase):
    def test_stop_rule_after_a_timeout(self):
        with mock.patch("guidance.llm.urlopen", side_effect=socket.timeout("timed out")) as fake:
            results = evaluation.run_cases()
        self.assertEqual(fake.call_count, 1)
        self.assertEqual([r.status for r in results],
                         ["timeout", "not_run", "not_run", "not_run", "not_run"])

    def test_case_subset(self):
        facts = evaluation.build_all_cases()
        replies = [ollama_reply(valid_output(facts["A"]))]
        with mock.patch("guidance.llm.urlopen", side_effect=replies) as fake:
            results = evaluation.run_cases(["A"])
        self.assertEqual(fake.call_count, 1)
        self.assertEqual([(r.case_id, r.status) for r in results], [("A", "accepted")])

    def test_timeout_marks_remaining_requested_cases_not_run(self):
        with mock.patch("guidance.llm.urlopen", side_effect=socket.timeout("timed out")) as fake:
            results = evaluation.run_cases(["B", "D"])
        self.assertEqual(fake.call_count, 1)
        self.assertEqual([(r.case_id, r.status) for r in results],
                         [("B", "timeout"), ("D", "not_run")])


def result(case_id, status, latency_ms=None, **kwargs):
    return evaluation.CaseResult(case_id, status, latency_ms=latency_ms,
                                 facts_sha256=case_id.lower(), **kwargs)


class ScopeAndSummaryTests(SimpleTestCase):
    """A Task 10 baseline is all five cases A–E, completed. Anything else is labelled."""

    def full_run(self):
        return [result("A", "accepted", 1000), result("B", "rejected", 3000,
                reason_codes=["advice"]), result("C", "parse_failure", 2000,
                failure_kind="malformed"), result("D", "model_unavailable", 5,
                failure_kind="unreachable"), result("E", "accepted", 4000)]

    def test_complete_five_case_run_is_the_task10_baseline(self):
        summary = evaluation.summarize(self.full_run())
        self.assertEqual(summary["scope"], "full_baseline")
        self.assertEqual(summary["run_state"], "complete")
        self.assertEqual(summary["requested_case_ids"], list(CASE_IDS))
        self.assertEqual(summary["counts"], {"accepted": 2, "rejected": 1, "timeout": 0,
                                             "model_unavailable": 1, "parse_failure": 1,
                                             "not_run": 0})
        # Denominator is the five baseline cases.
        self.assertEqual(summary["task10_baseline"],
                         {"cases": 5, "validator_acceptance": 0.4, "fallback": 0.6})
        self.assertIsNone(summary["subset_statistics"])
        # The 5 ms "model unavailable" call is not an inference duration and is excluded.
        self.assertEqual(summary["latency_ms"], {"median": 2500, "max": 4000, "n": 4})

    def test_denominators_for_a_mostly_accepted_baseline(self):
        runs = [result(c, "accepted", 1000) for c in "ABC"]
        runs += [result("D", "rejected", 1000, reason_codes=["spelled_number"]),
                 result("E", "timeout", 45000, failure_kind="timeout")]
        baseline = evaluation.summarize(runs)["task10_baseline"]
        self.assertEqual(baseline, {"cases": 5, "validator_acceptance": 0.6, "fallback": 0.4})

    def test_completed_subset_is_labelled_and_never_a_baseline(self):
        summary = evaluation.summarize([result("A", "accepted", 1000), result("B", "rejected",
                                        2000, reason_codes=["advice"])])
        self.assertEqual(summary["scope"], "subset")
        self.assertEqual(summary["run_state"], "complete")
        self.assertEqual(summary["requested_case_ids"], ["A", "B"])
        self.assertIsNone(summary["task10_baseline"])
        self.assertEqual(summary["subset_statistics"],
                         {"label": "diagnostic subset, not the five-case Task 10 baseline",
                          "cases": 2, "validator_acceptance": 0.5, "fallback": 0.5})

    def test_interrupted_full_run_reports_no_rates(self):
        runs = [result("A", "timeout", 45000, failure_kind="timeout")]
        runs += [result(c, "not_run") for c in "BCDE"]
        summary = evaluation.summarize(runs)
        self.assertEqual((summary["scope"], summary["run_state"]), ("full_baseline", "incomplete"))
        self.assertIsNone(summary["task10_baseline"])
        self.assertIsNone(summary["subset_statistics"])

    def test_interrupted_subset_reports_no_rates(self):
        summary = evaluation.summarize([result("A", "timeout", 45000, failure_kind="timeout"),
                                        result("B", "not_run")])
        self.assertEqual((summary["scope"], summary["run_state"]), ("subset", "incomplete"))
        self.assertIsNone(summary["task10_baseline"])
        self.assertIsNone(summary["subset_statistics"])


class MetadataAndOutputTests(SimpleTestCase):
    def test_metadata_records_the_run_configuration(self):
        with mock.patch("guidance.evaluation.urlopen", side_effect=fake_ollama_api()):
            info = evaluation.ollama_model_info("llama3")
            meta = evaluation.run_metadata("0.30.6", free_before=6.79, model_info=info,
                                           requested_case_ids=["A", "B"])
        import hashlib
        self.assertEqual(meta["prompt_version"], llm.PROMPT_VERSION)
        # The configured name and the tag Ollama resolves it to are kept separate.
        self.assertEqual(meta["model_configured"], "llama3")
        self.assertEqual(meta["model_resolved"], "llama3:latest")
        self.assertEqual(meta["model_digest"], "365c0bd3c000")
        self.assertEqual(meta["model_details"], {"parameter_size": "8.0B",
                                                 "quantization_level": "Q4_0"})
        self.assertEqual(meta["requested_case_ids"], ["A", "B"])
        self.assertEqual(meta["run_scope"], "subset")
        self.assertIsNone(meta["free_memory_gb_after"])
        self.assertEqual(meta["ollama_version"], "0.30.6")
        self.assertEqual(meta["options"], {"temperature": 0, "num_predict": 220})
        self.assertEqual(meta["timeout_s"], 45)
        self.assertEqual(meta["system_prompt_sha256"],
                         hashlib.sha256(llm.SYSTEM_PROMPT.encode("utf-8")).hexdigest())
        self.assertEqual(meta["free_memory_gb_before"], 6.79)
        self.assertEqual(meta["reference_today"], "2026-11-16T09:00:00-06:00")
        self.assertTrue(meta["endpoint_is_loopback"])
        self.assertRegex(meta["timestamp_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

    def test_model_resolution_by_tag(self):
        api = fake_ollama_api(models=["llama3:latest", "llama3.1:latest"])
        with mock.patch("guidance.evaluation.urlopen", side_effect=api):
            self.assertEqual(evaluation.ollama_model_info("llama3")["resolved_name"],
                             "llama3:latest")
            self.assertIsNone(evaluation.ollama_model_info("llama3:8b"))
            self.assertIsNone(evaluation.ollama_model_info("mistral"))

    def test_model_info_failure_is_none(self):
        with mock.patch("guidance.evaluation.urlopen", side_effect=URLError(SECRET)):
            self.assertIsNone(evaluation.ollama_model_info("llama3"))

    def test_ollama_version_failure_is_none_without_details(self):
        with mock.patch("guidance.evaluation.urlopen", side_effect=URLError(SECRET)):
            self.assertIsNone(evaluation.ollama_version())

    def test_written_results_are_sanitized_json_and_never_overwritten(self):
        facts = evaluation.build_all_cases()
        replies = [ollama_reply(valid_output(facts["A"]))]
        with mock.patch("guidance.llm.urlopen", side_effect=replies):
            results = evaluation.run_cases(["A"])
        meta = {"prompt_version": "v1", "timestamp_utc": "2026-11-16T15:00:00+00:00"}
        with tempfile.TemporaryDirectory() as tmp:
            first = evaluation.write_results(results, meta, Path(tmp))
            second = evaluation.write_results(results, meta, Path(tmp))
            self.assertNotEqual(first, second)
            self.assertEqual(first.name, "task10-v1-20261116T150000Z.json")
            data = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "detailwise-task10-results-v1")
        self.assertEqual(data["cases"][0]["status"], "accepted")
        self.assertIsNone(data["cases"][0]["human_review"])
        self.assertIn("not semantic accuracy", data["note"])
        text = json.dumps(data)
        for forbidden in ("Traceback", "SECRET_KEY", "password", "10.0.0.5"):
            self.assertNotIn(forbidden, text)

    def test_failure_details_never_contain_exception_text(self):
        facts = evaluation.build_all_cases()["A"]
        with mock.patch("guidance.llm.urlopen", side_effect=URLError(SECRET)):
            result = evaluation.run_case("A", facts)
        self.assertNotIn("10.0.0.5", json.dumps(evaluation.result_dict(result)))


class SafetyTests(SimpleTestCase):
    def test_import_and_case_building_make_no_model_or_network_calls(self):
        model, network = no_network()
        with model as fake_model, network as fake_network:
            importlib.reload(evaluation)
            evaluation.build_all_cases()
        fake_model.assert_not_called()
        fake_network.assert_not_called()

    def test_dry_run_command_makes_no_calls_and_writes_nothing(self):
        model, network = no_network()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, model as fake_model, network as fake_network:
            call_command("guidance_evaluate", "--output-dir", tmp, stdout=out)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        fake_model.assert_not_called()
        fake_network.assert_not_called()
        text = out.getvalue()
        self.assertIn("Dry run", text)
        for case_id in CASE_IDS:
            self.assertIn(f"{case_id}:", text)

class LiveGuardTests(SimpleTestCase):
    """Every refusal happens before any model call and leaves no results file.

    Each test uses a temporary --output-dir, so even a regressed guard cannot
    write into the repository.
    """

    def refuse(self, *args, memory=8.0, api=None, settings_changes=None):
        """Run --live expecting CommandError; return (error, model mock, files written)."""
        guidance_settings = dict(django_settings.GUIDANCE, **(settings_changes or {}))
        memory_patch = (mock.patch("guidance.evaluation.available_memory_gb",
                                   side_effect=memory) if callable(memory) else
                        mock.patch("guidance.evaluation.available_memory_gb",
                                   return_value=memory))
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(GUIDANCE=guidance_settings), memory_patch, \
                    mock.patch("guidance.evaluation.urlopen",
                               side_effect=api or fake_ollama_api()), \
                    mock.patch("guidance.llm.urlopen",
                               side_effect=AssertionError("model called")) as fake_model, \
                    self.assertRaises(CommandError) as caught:
                call_command("guidance_evaluate", "--live", "--output-dir", tmp, *args,
                             stdout=io.StringIO())
            written = list(Path(tmp).iterdir())
        return caught.exception, fake_model, written

    def assertRefusedBeforeAnyCall(self, error, fake_model, written, message):
        self.assertIn(message, str(error))
        self.assertEqual(error.returncode, 1)
        fake_model.assert_not_called()
        self.assertEqual(written, [])

    def test_memory_below_threshold_refuses(self):
        self.assertRefusedBeforeAnyCall(*self.refuse(memory=2.0), "Only 2.0 GB")

    def test_memory_just_below_default_threshold_refuses(self):
        self.assertRefusedBeforeAnyCall(*self.refuse(memory=5.99), "needs 6 GB")

    def test_unmeasurable_memory_refuses(self):
        self.assertRefusedBeforeAnyCall(*self.refuse(memory=None), "could not be measured")

    def test_sufficient_memory_continues_to_the_ollama_check(self):
        down = mock.Mock(side_effect=URLError("down"))
        error, fake_model, written = self.refuse(memory=6.0, api=down)
        self.assertRefusedBeforeAnyCall(error, fake_model, written, "Ollama did not answer")
        self.assertTrue(down.called)  # the memory guard passed and the next check ran

    def test_explicit_lower_threshold_is_honoured(self):
        down = mock.Mock(side_effect=URLError("down"))
        error, *_ = self.refuse("--min-free-gb", "4", memory=4.5, api=down)
        self.assertIn("Ollama did not answer", str(error))

    def test_non_local_endpoint_refuses_without_revealing_the_host(self):
        memory = mock.Mock(side_effect=AssertionError("memory probed"))
        error, fake_model, written = self.refuse(
            memory=memory, settings_changes={"OLLAMA_BASE_URL": SECRET.split()[0]})
        self.assertRefusedBeforeAnyCall(error, fake_model, written, "on this machine")
        self.assertNotIn("10.0.0.5", str(error))
        memory.assert_not_called()

    def test_model_not_installed_refuses(self):
        self.assertRefusedBeforeAnyCall(*self.refuse(api=fake_ollama_api(models=["mistral:latest"])),
                                        "is not installed")

    def test_invalid_arguments_are_command_errors(self):
        for args in (["--cases", "Z"], ["--min-free-gb", "0"], ["--min-free-gb", "-1"],
                     ["--min-free-gb", "nan"], ["--min-free-gb", "inf"],
                     ["--min-free-gb", "abc"]):
            with self.subTest(args=args), self.assertRaises(CommandError):
                call_command("guidance_evaluate", *args, stdout=io.StringIO())


class LiveRunTests(SimpleTestCase):
    def live(self, *args, replies, memory=(8.0, 7.5)):
        facts = evaluation.build_all_cases()
        out = io.StringIO()
        error = None
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("guidance.evaluation.available_memory_gb", side_effect=list(memory)), \
                mock.patch("guidance.evaluation.urlopen", side_effect=fake_ollama_api()), \
                mock.patch("guidance.llm.urlopen", side_effect=replies(facts)) as fake_model:
            try:
                call_command("guidance_evaluate", "--live", "--output-dir", tmp, *args,
                             stdout=out)
            except CommandError as exc:
                error = exc
            files = list(Path(tmp).iterdir())
            data = json.loads(files[0].read_text(encoding="utf-8")) if files else None
        return data, out.getvalue(), error, fake_model, files

    def test_full_run_writes_one_baseline_file(self):
        data, out, error, fake_model, files = self.live(
            replies=lambda facts: [ollama_reply(valid_output(facts[c]) if c == "A" else
                                                {"summary": "not a full reply"}) for c in CASE_IDS])
        self.assertIsNone(error)
        self.assertEqual(len(files), 1)
        self.assertEqual(fake_model.call_count, 5)
        self.assertEqual(data["metadata"]["run_scope"], "full_baseline")
        self.assertEqual(data["metadata"]["requested_case_ids"], list(CASE_IDS))
        self.assertEqual(data["metadata"]["model_configured"], "llama3")
        self.assertEqual(data["metadata"]["model_resolved"], "llama3:latest")
        self.assertEqual(data["metadata"]["free_memory_gb_before"], 8.0)
        self.assertEqual(data["metadata"]["free_memory_gb_after"], 7.5)
        self.assertEqual(data["summary"]["task10_baseline"]["cases"], 5)
        self.assertIn("full five-case Task 10 baseline", out)

    def test_subset_run_is_labelled_diagnostic(self):
        data, out, error, *_ = self.live(
            "--cases", "A", "B",
            replies=lambda facts: [ollama_reply(valid_output(facts["A"])),
                                   ollama_reply(valid_output(facts["B"]))])
        self.assertIsNone(error)
        self.assertEqual(data["metadata"]["run_scope"], "subset")
        self.assertEqual(data["metadata"]["requested_case_ids"], ["A", "B"])
        self.assertIsNone(data["summary"]["task10_baseline"])
        self.assertIn("not the five-case Task 10 baseline", out)
        self.assertIn("A: accepted", out)

    def test_failed_post_run_memory_probe_is_recorded_not_fatal(self):
        data, _, error, *_ = self.live("--cases", "A", memory=(8.0, None),
                                       replies=lambda facts: [ollama_reply(valid_output(facts["A"]))])
        self.assertIsNone(error)
        self.assertIsNone(data["metadata"]["free_memory_gb_after"])
        self.assertEqual(data["cases"][0]["status"], "accepted")

    def test_stop_rule_exits_3_and_still_records_the_run(self):
        data, _, error, fake_model, files = self.live(
            replies=lambda facts: socket.timeout("timed out"))
        self.assertEqual(error.returncode, 3)
        self.assertEqual(fake_model.call_count, 1)
        self.assertEqual(len(files), 1)
        self.assertEqual(data["summary"]["run_state"], "incomplete")
        self.assertEqual([c["status"] for c in data["cases"]],
                         ["timeout", "not_run", "not_run", "not_run", "not_run"])
