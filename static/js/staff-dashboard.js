/* Server-aggregated data, Vega-Lite charts and shared design tokens.
 * Tables remain available if JavaScript or the pinned CDN libraries fail.
 * Service names are data, never executable expressions.
 */
(function () {
  "use strict";
  const source = document.getElementById("dashboard-chart-data");
  if (!source) return;
  const data = JSON.parse(source.textContent);
  const tokens = getComputedStyle(document.documentElement);
  const color = (name) => tokens.getPropertyValue(name).trim();

  function spec(values, encoding, description) {
    return {
      $schema: "https://vega.github.io/schema/vega-lite/v6.json",
      description,
      width: "container",
      height: 260,
      autosize: {type: "fit", contains: "padding"},
      background: "transparent",
      data: {values},
      mark: {type: "bar", color: color("--color-info")},
      encoding,
      config: {
        view: {stroke: null},
        axis: {
          labelColor: color("--color-text-muted"),
          titleColor: color("--color-text"),
          gridColor: color("--color-border"),
          domainColor: color("--color-border"),
          tickColor: color("--color-border"),
        },
      },
    };
  }

  function draw(id, statusId, chart) {
    const status = document.getElementById(statusId);
    if (typeof window.vegaEmbed !== "function") {
      status.textContent = "Chart unavailable. Use the data table below.";
      return;
    }
    window.vegaEmbed("#" + id, chart, {actions: false, renderer: "svg", tooltip: false})
      .then(() => { status.textContent = "The same values are available in the data table below."; })
      .catch(() => { status.textContent = "Chart unavailable. Use the data table below."; });
  }

  draw("booking-trends", "trends-status", spec(data.trends, {
    // One category per ISO appointment date, rather than sub-day time ticks.
    // ISO sorting is chronological; UTC formatting avoids viewer-timezone shifts.
    x: {field: "date", type: "ordinal", sort: "ascending", title: "Appointment date (CT)",
      axis: {labelExpr: "utcFormat(toDate(datum.label), '%b %d, %Y')",
        labelAngle: 0, labelOverlap: true}},
    y: {field: "count", type: "quantitative", title: "Bookings", axis: {tickMinStep: 1}},
  }, "Total bookings by appointment date, including cancellations."));

  const popularity = spec(data.popularity, {
    y: {field: "service", type: "nominal", title: null, sort: "-x", axis: {labelLimit: 120}},
    x: {field: "count", type: "quantitative", title: "Bookings", axis: {tickMinStep: 1}},
  }, "Total bookings by service, including cancellations.");
  popularity.height = Math.max(180, data.popularity.length * 36);
  draw("service-popularity", "popularity-status", popularity);
}());
