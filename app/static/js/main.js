/**
 * ResQNet — main.js
 * Handles UI interactions and calls the /simulate endpoint.
 */

"use strict";

// ── Slider live readouts ──────────────────────────────────────────────────────
const nodeSlider       = document.getElementById("node-count");
const nodeDisplay      = document.getElementById("node-display");
const congestionSlider = document.getElementById("congestion-level");
const congestionDisplay= document.getElementById("congestion-display");

if (nodeSlider) {
  nodeSlider.addEventListener("input", () => {
    nodeDisplay.textContent = nodeSlider.value;
  });
}

if (congestionSlider) {
  congestionSlider.addEventListener("input", () => {
    congestionDisplay.textContent = congestionSlider.value + "%";
  });
}

// ── Chart instance (Chart.js) ─────────────────────────────────────────────────
let resultsChart = null;

function renderChart(labels, data) {
  const ctx = document.getElementById("resultsChart").getContext("2d");

  if (resultsChart) resultsChart.destroy();

  resultsChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Metric Value",
        data: data,
        backgroundColor: "rgba(245, 158, 11, 0.6)",
        borderColor:     "rgba(245, 158, 11, 1)",
        borderWidth: 2,
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#e2e8f0" } }
      },
      scales: {
        x: { ticks: { color: "#94a3b8" }, grid: { color: "#1e2535" } },
        y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e2535" } }
      }
    }
  });
}

// ── Simulation call ───────────────────────────────────────────────────────────
async function runSimulation() {
  const statusEl  = document.getElementById("sim-status");
  const chartPanel= document.getElementById("chart-panel");

  statusEl.textContent = "⏳ Running simulation…";

  const payload = {
    nodes:      parseInt(nodeSlider.value, 10),
    congestion: parseInt(congestionSlider.value, 10) / 100,
  };

  try {
    const res  = await fetch("/simulate", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });
    const json = await res.json();

    statusEl.textContent = `✅ ${json.message}`;
    chartPanel.style.display = "block";

    // Placeholder chart data until the real engine is wired
    renderChart(
      ["Latency", "Throughput", "Packet Loss", "Reliability"],
      [
        Math.random() * 100,
        Math.random() * 100,
        Math.random() * 100,
        Math.random() * 100,
      ]
    );
  } catch (err) {
    statusEl.textContent = `❌ Error: ${err.message}`;
  }
}
