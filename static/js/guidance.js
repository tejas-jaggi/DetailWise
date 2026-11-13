/*
 * DetailWise weather guidance: DOM and fetch (plan Task 8, D6, D8).
 *
 * - Reads the booking form's service, date and time values and listens for their
 *   change events. It never writes to, submits, blocks or disables the form.
 * - Fetches the forecast for each new selection (aborting the previous request),
 *   and asks for an explanation when the customer presses the Explain button.
 * - Renders only through textContent and createElement; nothing from a response
 *   is ever parsed as HTML.
 * - Any error leaves a fixed message in the panel; the booking form is unaffected.
 */
(function () {
  "use strict";

  var G = window.DetailWiseGuidance;
  var panel = document.getElementById("weather-panel");
  if (!G || !panel) return;

  var fields = {
    service: document.getElementById(panel.dataset.serviceInput),
    date: document.getElementById(panel.dataset.dateInput),
    time: document.getElementById(panel.dataset.timeInput),
  };
  if (!fields.service || !fields.date) return;

  var weatherSlot = document.getElementById("weather-slot");
  var explainButton = document.getElementById("explain-btn");
  var explainStatus = document.getElementById("explain-status");
  var explainSlot = document.getElementById("explain-slot");
  var state = G.createGuidanceState();
  var forecastController = null;
  var explainController = null;
  var explainTimers = [];
  var lastKey = null;

  /* ---------- Small DOM helpers (text only) ---------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function show(container, nodes) {
    container.replaceChildren.apply(container, nodes);
  }

  function readInputs() {
    return {
      service: fields.service.value,
      date: fields.date.value,
      time: fields.time ? fields.time.value : "",
    };
  }

  function updateExplainButton() {
    explainButton.disabled = !state.explainAllowed();
  }

  function clearExplanation() {
    explainTimers.forEach(clearTimeout);
    explainTimers = [];
    if (explainController) explainController.abort();
    explainController = null;
    explainStatus.textContent = "";
    show(explainSlot, []);
    explainButton.textContent = "Explain this forecast";
  }

  /* ---------- Fetch ---------- */

  /* Resolves to a view from G.interpretResponse/failureView, or null when the
     request was aborted because a newer one replaced it. Never rejects. */
  function request(url, init, controller, kind, timeoutMs) {
    var timedOut = false;
    var timer = setTimeout(function () {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    init.credentials = "same-origin";
    init.signal = controller.signal;
    return fetch(url, init)
      .then(function (response) {
        var type = response.headers.get("Content-Type") || "";
        var json = type.indexOf("application/json") === 0 ? response.json() : Promise.resolve(null);
        return json.catch(function () { return null; }).then(function (body) {
          return G.interpretResponse(kind, { status: response.status, json: body });
        });
      })
      .catch(function () {
        return controller.signal.aborted && !timedOut
          ? null // replaced by a newer request: nothing to show
          : G.failureView(kind, timedOut ? "timeout" : "network");
      })
      .finally(function () {
        clearTimeout(timer);
      });
  }

  /* ---------- Forecast ---------- */

  function selectionChanged() {
    var inputs = readInputs();
    var key = state.inputKey(inputs.service, inputs.date, inputs.time);
    if (key === lastKey) return;
    lastKey = key;
    state.inputsChanged(key);
    clearExplanation();
    if (forecastController) forecastController.abort();
    forecastController = null;
    if (!G.inputsComplete(inputs)) {
      show(weatherSlot, [el("p", "weather-panel__empty", G.MESSAGES.idle)]);
      updateExplainButton();
      return;
    }
    loadForecast(key, inputs);
  }

  function loadForecast(key, inputs) {
    var token = state.beginForecast(key);
    var controller = new AbortController();
    forecastController = controller;
    updateExplainButton();
    show(weatherSlot, [loadingLine(G.MESSAGES.loading)]);

    var url = panel.dataset.forecastUrl + "?" + G.requestFields(inputs);
    request(url, {
      method: "GET",
      headers: { Accept: "application/json" },
    }, controller, "forecast", G.TIMING.forecastAbortMs).then(function (view) {
      if (!view || !state.isCurrent(token)) return; // stale: a newer selection exists
      state.finishForecast(token, view.state === "available");
      renderForecast(view, key, inputs);
      updateExplainButton();
    });
  }

  function renderForecast(view, key, inputs) {
    if (view.state === "available") {
      show(weatherSlot, [forecastCard(view.facts)]);
      return;
    }
    var nodes = [el("p", "weather-panel__message", view.message)];
    if (view.retry) {
      var retry = el("button", "link-button weather-panel__retry", "Retry forecast");
      retry.type = "button";
      retry.addEventListener("click", function () {
        if (state.inputKey(inputs.service, inputs.date, inputs.time) === lastKey) {
          loadForecast(key, inputs);
        }
      });
      nodes.push(retry);
    }
    show(weatherSlot, nodes);
  }

  function forecastCard(facts) {
    var card = el("div", "forecast-card");
    card.appendChild(el("h3", "forecast-card__title", G.forecastHeading(facts)));
    var list = el("dl", "forecast-card__rows");
    G.forecastRows(facts).forEach(function (row) {
      var item = el("div", "forecast-card__row");
      item.appendChild(el("dt", null, row.label));
      item.appendChild(el("dd", null, row.value));
      list.appendChild(item);
    });
    card.appendChild(list);
    return card;
  }

  function loadingLine(text) {
    var line = el("p", "weather-panel__loading");
    line.appendChild(el("span", "weather-panel__dot"));
    line.lastChild.setAttribute("aria-hidden", "true");
    line.appendChild(document.createTextNode(text));
    return line;
  }

  /* ---------- Explanation ---------- */

  function explain() {
    if (!state.explainAllowed()) return;
    var inputs = readInputs();
    var key = state.inputKey(inputs.service, inputs.date, inputs.time);
    if (key !== lastKey) return;
    clearExplanation();
    var token = state.beginExplain(key);
    var controller = new AbortController();
    explainController = controller;
    updateExplainButton();
    explainButton.textContent = "Generating…";
    explainStatus.textContent = G.MESSAGES.generating;
    show(explainSlot, [loadingLine(G.MESSAGES.generating)]);
    explainTimers.push(setTimeout(function () {
      if (state.isCurrent(token)) {
        explainStatus.textContent = G.MESSAGES.stillWorking;
        show(explainSlot, [loadingLine(G.MESSAGES.generating + " " + G.MESSAGES.stillWorking)]);
      }
    }, G.TIMING.stillWorkingMs));

    request(panel.dataset.explainUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": panel.dataset.csrfToken,
      },
      body: G.requestFields(inputs),
    }, controller, "explain", G.TIMING.explainAbortMs).then(function (view) {
      if (!view || !state.isCurrent(token)) return; // stale: the selection changed
      state.finishExplain(token);
      explainTimers.forEach(clearTimeout);
      explainTimers = [];
      explainController = null;
      explainButton.textContent = "Explain this forecast";
      renderExplanation(view);
      updateExplainButton();
    });
  }

  function renderExplanation(view) {
    if (view.state !== "ai" && view.state !== "fallback") {
      explainStatus.textContent = view.message;
      show(explainSlot, [el("p", "weather-panel__message", view.message)]);
      return;
    }
    explainStatus.textContent = view.label + " ready.";
    var result = el("div", "guidance-result guidance-result--" + view.state);
    result.appendChild(el("p", "guidance-result__source", view.label));
    view.sections.forEach(function (section) {
      var block = el("section", "guidance-section");
      block.appendChild(el("h3", "guidance-section__label", section.label));
      block.appendChild(el("p", "guidance-section__text", section.text));
      result.appendChild(block);
    });
    var note = view.state === "ai"
      ? "Written by DetailWise's AI model from the forecast above and checked against it. The recommendation is DetailWise's own."
      : "The AI explanation could not be used, so DetailWise's standard guidance is shown.";
    result.appendChild(el("p", "guidance-result__note", note));
    show(explainSlot, [result]);
  }

  /* ---------- Wiring ---------- */

  [fields.service, fields.date, fields.time].forEach(function (field) {
    if (field) field.addEventListener("change", selectionChanged);
  });
  explainButton.addEventListener("click", explain);
  selectionChanged(); // a selection may already be there (?service= or a re-rendered form)
})();
