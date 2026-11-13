// Tests for static/js/guidance-state.js (plan Task 8, D8). Run: node --test guidance/tests/js/
// The module is pure: no DOM, no network. It is loaded the same way the browser
// would not need to: through CommonJS module.exports.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const G = require("../../../static/js/guidance-state.js");

const K1 = G.createGuidanceState().inputKey("1", "2026-11-12", "10:00");

function readyState(key = K1) {
  const state = G.createGuidanceState();
  state.inputsChanged(key);
  const forecast = state.beginForecast(key);
  state.finishForecast(forecast, true);
  return state;
}

// ---- Stale-response protection (plan tests) ----

test("newer forecast supersedes older", () => {
  const state = G.createGuidanceState();
  state.inputsChanged(K1);
  const older = state.beginForecast(K1);
  const newer = state.beginForecast(K1);
  assert.equal(state.isCurrent(older), false);
  assert.equal(state.isCurrent(newer), true);
  const k2 = state.inputKey("1", "2026-11-13", "10:00");
  state.inputsChanged(k2);
  const third = state.beginForecast(k2);
  assert.equal(state.isCurrent(newer), false);
  assert.equal(state.isCurrent(third), true);
});

test("explain result ignored after date change", () => {
  const state = readyState();
  const explain = state.beginExplain(K1);
  state.inputsChanged(state.inputKey("1", "2026-11-13", "10:00"));
  assert.equal(state.isCurrent(explain), false);
});

test("explain result ignored after service change", () => {
  const state = readyState();
  const explain = state.beginExplain(K1);
  state.inputsChanged(state.inputKey("2", "2026-11-12", "10:00"));
  assert.equal(state.isCurrent(explain), false);
});

test("explain result ignored after time change", () => {
  const state = readyState();
  const explain = state.beginExplain(K1);
  state.inputsChanged(state.inputKey("1", "2026-11-12", "14:00"));
  assert.equal(state.isCurrent(explain), false);
});

test("forecast retry for same key keeps explanation valid", () => {
  const state = readyState();
  const explain = state.beginExplain(K1);
  state.inputsChanged(K1);
  state.beginForecast(K1);
  assert.equal(state.isCurrent(explain), true);
});

test("explain not allowed while one is in flight", () => {
  const state = readyState();
  assert.equal(state.explainAllowed(), true);
  const explain = state.beginExplain(K1);
  assert.equal(state.explainAllowed(), false);
  state.finishExplain(explain);
  assert.equal(state.explainAllowed(), true);
});

test("explain not allowed without available forecast", () => {
  const state = G.createGuidanceState();
  assert.equal(state.explainAllowed(), false);
  state.inputsChanged(K1);
  const forecast = state.beginForecast(K1);
  assert.equal(state.explainAllowed(), false); // still loading
  state.finishForecast(forecast, false); // out of range or unavailable
  assert.equal(state.explainAllowed(), false);
});

test("explain not allowed after inputs change until the new forecast arrives", () => {
  const state = readyState();
  const k2 = state.inputKey("1", "2026-11-13", "");
  state.inputsChanged(k2);
  assert.equal(state.explainAllowed(), false);
  const forecast = state.beginForecast(k2);
  state.finishForecast(forecast, true);
  assert.equal(state.explainAllowed(), true);
});

test("a stale forecast cannot mark the new key available", () => {
  const state = G.createGuidanceState();
  state.inputsChanged(K1);
  const stale = state.beginForecast(K1);
  state.inputsChanged(state.inputKey("1", "2026-11-13", ""));
  state.finishForecast(stale, true);
  assert.equal(state.explainAllowed(), false);
});

test("a stale explanation cannot end the current one", () => {
  const state = readyState();
  const first = state.beginExplain(K1);
  state.inputsChanged(state.inputKey("2", "2026-11-12", "10:00"));
  const f2 = state.beginForecast(state.inputKey("2", "2026-11-12", "10:00"));
  state.finishForecast(f2, true);
  const second = state.beginExplain(state.inputKey("2", "2026-11-12", "10:00"));
  state.finishExplain(first);
  assert.equal(state.isCurrent(second), true);
  assert.equal(state.explainAllowed(), false);
});

test("changing the selection during an explanation frees the Explain button for the new one", () => {
  const state = readyState();
  state.beginExplain(K1); // still generating for the old selection
  const k2 = state.inputKey("1", "2026-11-13", "");
  state.inputsChanged(k2);
  state.finishForecast(state.beginForecast(k2), true);
  assert.equal(state.explainAllowed(), true);
});

test("an old forecast is stale as soon as the selection changes, before any new request", () => {
  const state = G.createGuidanceState();
  state.inputsChanged(K1);
  const old = state.beginForecast(K1);
  state.inputsChanged(state.inputKey("", "2026-11-12", "10:00")); // service cleared
  assert.equal(state.isCurrent(old), false);
});

test("a late stale forecast cannot disable Explain for the current selection", () => {
  const state = G.createGuidanceState();
  state.inputsChanged(K1);
  const stale = state.beginForecast(K1);
  const k2 = state.inputKey("1", "2026-11-13", "");
  state.inputsChanged(k2);
  state.finishForecast(state.beginForecast(k2), true);
  state.finishForecast(stale, false);
  assert.equal(state.explainAllowed(), true);
});

test("input keys separate service, date and time", () => {
  const state = G.createGuidanceState();
  assert.notEqual(state.inputKey("1", "2026-11-12", ""), state.inputKey("1", "2026-11-12", "10:00"));
  assert.notEqual(state.inputKey("1", "2", "3"), state.inputKey("12", "", "3"));
});

// ---- Request fields ----

test("request fields carry exactly service, date and optional time", () => {
  assert.equal(G.requestFields({ service: "3", date: "2026-11-12", time: "10:00" }),
    "service=3&date=2026-11-12&time=10%3A00");
  assert.equal(G.requestFields({ service: "3", date: "2026-11-12", time: "" }),
    "service=3&date=2026-11-12");
});

test("inputs are complete only with a service and a date", () => {
  assert.equal(G.inputsComplete({ service: "3", date: "2026-11-12", time: "" }), true);
  assert.equal(G.inputsComplete({ service: "", date: "2026-11-12", time: "10:00" }), false);
  assert.equal(G.inputsComplete({ service: "3", date: "", time: "10:00" }), false);
});

// ---- Response interpretation ----

const FACTS = {
  date: "2026-11-12", time: "10:00", lead_days: 2, confidence: "higher",
  temp_high_f: 52, temp_low_f: 37, peak_rain_chance_pct: 20, appt_rain_chance_pct: 11,
  wind_max_mph: 10, gust_max_mph: 17,
};
const SECTIONS = [
  { label: "Conditions", text: "<b>Rain</b> & wind" },
  { label: "For your service", text: "b" },
  { label: "Forecast confidence", text: "c" },
  { label: "Recommendation", text: "d" },
];

function ok(json) {
  return { status: 200, json };
}

test("forecast available", () => {
  const view = G.interpretResponse("forecast", ok({ status: "available", facts: FACTS }));
  assert.equal(view.state, "available");
  assert.equal(view.facts, FACTS);
});

test("explanation from the AI and from the fallback", () => {
  const ai = G.interpretResponse("explain", ok({
    status: "available", facts: FACTS, sections: SECTIONS, source: "ai",
  }));
  assert.equal(ai.state, "ai");
  assert.equal(ai.label, "AI explanation");
  assert.deepEqual(ai.sections, SECTIONS);
  assert.equal(ai.sections[0].text, "<b>Rain</b> & wind"); // passed through as text
  const fallback = G.interpretResponse("explain", ok({
    status: "available", facts: FACTS, sections: SECTIONS, source: "fallback",
    fallback_reason: "ai_rejected",
  }));
  assert.equal(fallback.state, "fallback");
  assert.equal(fallback.label, "Standard guidance");
});

test("out of range and weather unavailable use the server message", () => {
  const out = G.interpretResponse("forecast", ok({
    status: "out_of_range", message: "No forecast for this date yet. Forecasts are available through Wed, Nov 25.",
  }));
  assert.equal(out.state, "out_of_range");
  assert.match(out.message, /Wed, Nov 25/);
  const down = G.interpretResponse("explain", ok({
    status: "weather_unavailable", message: "Forecast unavailable right now. You can still save your booking.",
  }));
  assert.equal(down.state, "weather_unavailable");
  assert.equal(down.retry, true);
});

test("400 shows the fixed field message", () => {
  const view = G.interpretResponse("forecast", {
    status: 400, json: { status: "invalid", errors: { date: ["Choose today or a later date (Central Time)."] } },
  });
  assert.equal(view.state, "invalid");
  assert.equal(view.message, "Choose today or a later date (Central Time).");
});

test("401 asks the customer to sign in again", () => {
  const view = G.interpretResponse("explain", { status: 401, json: { status: "auth_required" } });
  assert.equal(view.state, "auth_required");
  assert.match(view.message, /sign in/i);
});

test("a non-JSON 403 (CSRF failure) means the session may have expired", () => {
  const view = G.interpretResponse("explain", { status: 403, json: null });
  assert.equal(view.state, "session_expired");
  assert.equal(view.message, "Your session may have expired. Reload the page.");
});

test("server errors and unexpected bodies give a safe message", () => {
  for (const response of [
    { status: 500, json: null },
    { status: 200, json: null },
    { status: 200, json: { status: "surprise" } },
    { status: 200, json: { status: "available" } }, // explain without sections
    { status: 200, json: { status: "available", sections: "x", source: "ai" } },
    { status: 502, json: { detail: "Traceback (most recent call last)" } },
    // facts present, but no usable sections or source
    { status: 200, json: { status: "available", facts: FACTS } },
    { status: 200, json: { status: "available", facts: FACTS, sections: [], source: "ai" } },
    { status: 200, json: { status: "available", facts: FACTS, sections: "x", source: "ai" } },
    { status: 200, json: { status: "available", facts: FACTS, sections: [{ label: 1 }], source: "ai" } },
    { status: 200, json: { status: "available", facts: FACTS, sections: SECTIONS, source: "model" } },
    { status: 200, json: { status: "available", facts: FACTS, sections: SECTIONS, source: "toString" } },
  ]) {
    const view = G.interpretResponse("explain", response);
    assert.equal(view.state, "error");
    assert.equal(view.message, "The explanation is unavailable right now. You can still save your booking.");
    assert.doesNotMatch(JSON.stringify(view), /Traceback/);
  }
  const forecast = G.interpretResponse("forecast", { status: 500, json: null });
  assert.equal(forecast.message, "Forecast unavailable right now. You can still save your booking.");
  assert.equal(forecast.retry, true);
});

test("failures: network and timeout", () => {
  assert.equal(G.failureView("explain", "timeout").state, "timeout");
  assert.equal(G.failureView("explain", "timeout").message,
    "The AI explanation took too long. You can still save your booking.");
  assert.equal(G.failureView("forecast", "network").state, "error");
  assert.equal(G.failureView("forecast", "network").retry, true);
});

// ---- Display helpers ----

test("forecast rows name both rain values and never a bare rain chance", () => {
  const rows = G.forecastRows(FACTS);
  const labels = rows.map((row) => row.label);
  assert.ok(labels.includes("Highest hourly rain chance"));
  assert.ok(labels.includes("Rain chance, hour starting 10:00 AM"));
  assert.ok(!labels.includes("Rain chance"));
  assert.deepEqual(rows.find((r) => r.label === "Highest hourly rain chance").value, "20%");
  assert.deepEqual(rows.find((r) => r.label === "Temperature").value, "High 52°F · Low 37°F");
  assert.deepEqual(rows.find((r) => r.label === "Wind").value, "Up to 10 mph · gusts 17 mph");
});

test("forecast rows omit the hour rain row without a value and mark missing values", () => {
  const rows = G.forecastRows({ ...FACTS, time: null, appt_rain_chance_pct: null,
    peak_rain_chance_pct: null, gust_max_mph: null });
  const labels = rows.map((row) => row.label);
  assert.ok(!labels.some((label) => label.startsWith("Rain chance")));
  assert.equal(rows.find((r) => r.label === "Highest hourly rain chance").value, "Not available");
  assert.equal(rows.find((r) => r.label === "Wind").value, "Up to 10 mph");
  for (const row of rows) assert.doesNotMatch(row.value, /null|undefined|NaN/);
});

test("with a time but no hour value, there is no hour rain row", () => {
  const rows = G.forecastRows({ ...FACTS, appt_rain_chance_pct: null });
  assert.ok(!rows.some((row) => row.label.startsWith("Rain chance")));
  for (const row of rows) assert.doesNotMatch(row.value, /null|undefined|NaN/);
});

test("forecast heading, dates and times", () => {
  assert.equal(G.formatDate("2026-11-12"), "Thu, Nov 12");
  assert.equal(G.formatDate("2026-03-08"), "Sun, Mar 8");
  assert.equal(G.formatTime("00:30"), "12:30 AM");
  assert.equal(G.formatTime("12:00"), "12:00 PM");
  assert.equal(G.formatTime("14:05"), "2:05 PM");
  assert.equal(G.forecastHeading(FACTS), "Thu, Nov 12 · 10:00 AM");
  assert.equal(G.forecastHeading({ ...FACTS, time: null }), "Thu, Nov 12");
});

test("timing matches the plan", () => {
  assert.equal(G.TIMING.explainAbortMs, 55000);
  assert.equal(G.TIMING.stillWorkingMs, 20000);
  assert.match(G.MESSAGES.generating, /10–25 seconds/);
  assert.equal(G.MESSAGES.stillWorking, "Still working…");
});
