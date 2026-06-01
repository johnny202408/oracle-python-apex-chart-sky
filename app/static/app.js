const statusEl = document.querySelector("#status");
const rowsMetric = document.querySelector("#rowsMetric");
const queryMetric = document.querySelector("#queryMetric");
const browserMetric = document.querySelector("#browserMetric");
const payloadMetric = document.querySelector("#payloadMetric");
const presetButtons = Array.from(document.querySelectorAll(".preset-button"));

const numberFormat = new Intl.NumberFormat("en-US");

const chart = new ApexCharts(document.querySelector("#chart"), {
  chart: {
    type: "line",
    height: 520,
    animations: { enabled: false },
    toolbar: {
      show: true,
      tools: {
        download: true,
        selection: true,
        zoom: true,
        zoomin: true,
        zoomout: true,
        pan: true,
        reset: true,
      },
    },
    zoom: { enabled: true },
  },
  colors: ["#0f766e"],
  dataLabels: { enabled: false },
  grid: {
    borderColor: "#e4e8f1",
    strokeDashArray: 4,
  },
  markers: { size: 0 },
  series: [{ name: "Metric value", data: [] }],
  stroke: {
    curve: "straight",
    width: 1.7,
  },
  tooltip: {
    shared: false,
    x: {
      formatter: (value) => `Row ${numberFormat.format(value)}`,
    },
  },
  xaxis: {
    type: "numeric",
    tickAmount: 8,
    labels: {
      formatter: (value) => numberFormat.format(Math.round(value)),
    },
  },
  yaxis: {
    decimalsInFloat: 1,
    labels: {
      formatter: (value) => value.toFixed(1),
    },
  },
});

chart.render();

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-ready", state === "ready");
  statusEl.classList.toggle("is-error", state === "error");
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) {
    return `${numberFormat.format(Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

async function loadRows(rows) {
  setStatus("Loading", "loading");
  const started = performance.now();

  try {
    const response = await fetch(`/api/chart-data?rows=${rows}`, {
      headers: { Accept: "application/json" },
    });
    const rawPayload = await response.text();

    if (!response.ok) {
      throw new Error(rawPayload || response.statusText);
    }

    const payload = JSON.parse(rawPayload);
    const browserMs = performance.now() - started;

    await chart.updateSeries(payload.series, true);

    rowsMetric.textContent = numberFormat.format(payload.rows);
    queryMetric.textContent = `${numberFormat.format(payload.elapsed_ms)} ms`;
    browserMetric.textContent = `${numberFormat.format(Math.round(browserMs))} ms`;
    payloadMetric.textContent = formatBytes(new Blob([rawPayload]).size);
    setStatus("Ready", "ready");
  } catch (error) {
    console.error(error);
    setStatus("Error", "error");
    queryMetric.textContent = "-- ms";
    browserMetric.textContent = "-- ms";
    payloadMetric.textContent = "-- KB";
  }
}

presetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    presetButtons.forEach((candidate) => candidate.classList.remove("is-active"));
    button.classList.add("is-active");
    loadRows(button.dataset.rows);
  });
});

loadRows(100);
