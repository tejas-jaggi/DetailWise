/*
 * DetailWise weather guidance: pure logic, no DOM and no network (plan Task 8, D8).
 *
 * - createGuidanceState() tracks request tokens so that a response for an older
 *   service/date/time selection is never shown.
 * - interpretResponse() and failureView() turn an HTTP outcome into a view
 *   description with fixed customer messages.
 * - forecastRows() and the formatters build the forecast card's text.
 *
 * Every string returned here is plain text; guidance.js writes it with textContent.
 * Exported to window.DetailWiseGuidance in the browser and module.exports in Node.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.DetailWiseGuidance = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TIMING = { forecastAbortMs: 15000, explainAbortMs: 55000, stillWorkingMs: 20000 };

  var MESSAGES = {
    idle: "Choose a service and a date to see the forecast for your appointment.",
    loading: "Loading forecast…",
    generating: "Generating explanation… the AI model usually takes 10–25 seconds.",
    stillWorking: "Still working…",
    forecastError: "Forecast unavailable right now. You can still save your booking.",
    explainError: "The explanation is unavailable right now. You can still save your booking.",
    timeout: "The AI explanation took too long. You can still save your booking.",
    authRequired: "Your session has ended. Sign in again to see the forecast.",
    sessionExpired: "Your session may have expired. Reload the page.",
    invalid: "Check the service, date and time.",
  };

  var SOURCE_LABELS = { ai: "AI explanation", fallback: "Standard guidance" };

  var WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ---------- Stale-response protection ---------- */

  function createGuidanceState() {
    var nextId = 0;
    var currentKey = null;
    var forecast = null; // { id, key }
    var explain = null; // { id, key }
    var forecastReadyKey = null; // key whose forecast is available

    function token(kind, key) {
      nextId += 1;
      return { kind: kind, key: key, id: nextId };
    }

    return {
      inputKey: function (service, date, time) {
        return JSON.stringify([String(service || ""), String(date || ""), String(time || "")]);
      },

      /* The selection changed: forget everything that belongs to another key. */
      inputsChanged: function (key) {
        currentKey = key; // isCurrent() now rejects every token for another key
        if (explain && explain.key !== key) explain = null; // frees explainAllowed()
        if (forecastReadyKey !== key) forecastReadyKey = null;
      },

      beginForecast: function (key) {
        forecast = token("forecast", key);
        if (forecastReadyKey === key) forecastReadyKey = null;
        return forecast;
      },

      finishForecast: function (t, available) {
        if (!this.isCurrent(t)) return;
        forecastReadyKey = available ? t.key : null;
      },

      beginExplain: function (key) {
        explain = token("explain", key);
        return explain;
      },

      finishExplain: function (t) {
        if (this.isCurrent(t)) explain = null;
      },

      isCurrent: function (t) {
        if (!t || t.key !== currentKey) return false;
        var active = t.kind === "forecast" ? forecast : explain;
        return active !== null && active.id === t.id;
      },

      explainAllowed: function () {
        return currentKey !== null && forecastReadyKey === currentKey && explain === null;
      },
    };
  }

  /* ---------- Requests ---------- */

  function inputsComplete(inputs) {
    return Boolean(inputs.service) && Boolean(inputs.date);
  }

  /* Only these three fields are ever sent. */
  function requestFields(inputs) {
    var params = new URLSearchParams();
    params.set("service", inputs.service);
    params.set("date", inputs.date);
    if (inputs.time) params.set("time", inputs.time);
    return params.toString();
  }

  /* ---------- Responses ---------- */

  function errorMessage(kind) {
    return kind === "forecast" ? MESSAGES.forecastError : MESSAGES.explainError;
  }

  function failureView(kind, reason) {
    if (reason === "timeout" && kind === "explain") {
      return { state: "timeout", message: MESSAGES.timeout };
    }
    return { state: "error", message: errorMessage(kind), retry: kind === "forecast" };
  }

  function validSections(sections) {
    return (
      Array.isArray(sections) &&
      sections.length > 0 &&
      sections.every(function (s) {
        return s && typeof s.label === "string" && typeof s.text === "string";
      })
    );
  }

  /* response: { status: HTTP status, json: parsed body or null when not JSON } */
  function interpretResponse(kind, response) {
    var body = response.json;
    var isObject = body !== null && typeof body === "object";

    if (response.status === 401) return { state: "auth_required", message: MESSAGES.authRequired };
    if (response.status === 403) return { state: "session_expired", message: MESSAGES.sessionExpired };
    if (response.status === 400 && isObject && body.status === "invalid") {
      return { state: "invalid", message: firstError(body.errors) };
    }
    if (response.status !== 200 || !isObject) return failureView(kind, "error");

    if (body.status === "out_of_range" && typeof body.message === "string") {
      return { state: "out_of_range", message: body.message };
    }
    if (body.status === "weather_unavailable" && typeof body.message === "string") {
      return { state: "weather_unavailable", message: body.message, retry: true };
    }
    if (body.status === "available" && body.facts && typeof body.facts === "object") {
      if (kind === "forecast") return { state: "available", facts: body.facts };
      if (SOURCE_LABELS.hasOwnProperty(body.source) && validSections(body.sections)) {
        return {
          state: body.source,
          label: SOURCE_LABELS[body.source],
          sections: body.sections,
          facts: body.facts,
        };
      }
    }
    return failureView(kind, "error");
  }

  function firstError(errors) {
    if (errors && typeof errors === "object") {
      var keys = Object.keys(errors);
      for (var i = 0; i < keys.length; i += 1) {
        var list = errors[keys[i]];
        if (Array.isArray(list) && typeof list[0] === "string") return list[0];
      }
    }
    return MESSAGES.invalid;
  }

  /* ---------- Display helpers ---------- */

  function formatDate(iso) {
    var parts = String(iso).split("-").map(Number);
    var day = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return WEEKDAYS[day.getUTCDay()] + ", " + MONTHS[day.getUTCMonth()] + " " + day.getUTCDate();
  }

  function formatTime(hhmm) {
    var parts = String(hhmm).split(":").map(Number);
    var hour = parts[0] % 12 || 12;
    var minutes = String(parts[1]).padStart(2, "0");
    return hour + ":" + minutes + " " + (parts[0] < 12 ? "AM" : "PM");
  }

  function forecastHeading(facts) {
    var heading = formatDate(facts.date);
    return facts.time ? heading + " · " + formatTime(facts.time) : heading;
  }

  function known(value) {
    return typeof value === "number" && isFinite(value);
  }

  function temperatureText(facts) {
    var parts = [];
    if (known(facts.temp_high_f)) parts.push("High " + facts.temp_high_f + "°F");
    if (known(facts.temp_low_f)) parts.push("Low " + facts.temp_low_f + "°F");
    return parts.length ? parts.join(" · ") : "Not available";
  }

  function windText(facts) {
    var parts = [];
    if (known(facts.wind_max_mph)) parts.push("Up to " + facts.wind_max_mph + " mph");
    if (known(facts.gust_max_mph)) parts.push("gusts " + facts.gust_max_mph + " mph");
    if (!parts.length) return "Not available";
    if (!known(facts.wind_max_mph)) return "Gusts up to " + facts.gust_max_mph + " mph";
    return parts.join(" · ");
  }

  function percentText(value) {
    return known(value) ? value + "%" : "Not available";
  }

  /* The card never shows a bare "Rain chance": each rain value says which one it is. */
  function forecastRows(facts) {
    var rows = [
      { label: "Temperature", value: temperatureText(facts) },
      { label: "Highest hourly rain chance", value: percentText(facts.peak_rain_chance_pct) },
    ];
    if (facts.time && known(facts.appt_rain_chance_pct)) {
      rows.push({
        label: "Rain chance, hour containing your appointment",
        value: facts.appt_rain_chance_pct + "%",
      });
    }
    rows.push({ label: "Wind", value: windText(facts) });
    return rows;
  }

  return {
    TIMING: TIMING,
    MESSAGES: MESSAGES,
    SOURCE_LABELS: SOURCE_LABELS,
    createGuidanceState: createGuidanceState,
    inputsComplete: inputsComplete,
    requestFields: requestFields,
    interpretResponse: interpretResponse,
    failureView: failureView,
    forecastRows: forecastRows,
    forecastHeading: forecastHeading,
    formatDate: formatDate,
    formatTime: formatTime,
  };
});
