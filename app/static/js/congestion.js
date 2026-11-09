/**
 * ResQNet - Congestion Control Lab (congestion.js)
 * Leaky Bucket physical queue animation, overflow drop visualization,
 * tick-by-tick simulation stepping, and traffic smoothing analysis.
 */
"use strict";

let congestionData = null;
let currentTickIndex = 0;
let isPlaying = false;
let playInterval = null;
let congestionChartInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    initCongestionLab();
    bindCongestionControls();
});

async function initCongestionLab() {
    try {
        await executeSimulation(false);
    } catch (err) {
        console.error("Congestion initialization error:", err);
        showToast("Error initializing Congestion Control: " + err.message, "error");
    }
}

function bindCongestionControls() {
    const btnInit = document.getElementById("btn-init");
    const btnPlay = document.getElementById("btn-play");
    const btnPause = document.getElementById("btn-pause");
    const btnStep = document.getElementById("btn-step");
    const btnReset = document.getElementById("btn-reset");

    if (btnInit) btnInit.addEventListener("click", () => executeSimulation(true));
    if (btnPlay) btnPlay.addEventListener("click", () => startPlayback());
    if (btnPause) btnPause.addEventListener("click", () => pausePlayback());
    if (btnStep) btnStep.addEventListener("click", () => stepForward());
    if (btnReset) btnReset.addEventListener("click", () => resetSimulation());

    // Presets
    const pSurge = document.getElementById("preset-surge");
    const pSteady = document.getElementById("preset-steady");
    const pOverflow = document.getElementById("preset-overflow");

    if (pSurge) {
        pSurge.addEventListener("click", () => {
            document.getElementById("bucket_capacity").value = 15;
            document.getElementById("leak_rate").value = 4;
            document.getElementById("incoming_packets").value = "12, 2, 14, 0, 8, 16, 2, 0";
            executeSimulation(true);
        });
    }
    if (pSteady) {
        pSteady.addEventListener("click", () => {
            document.getElementById("bucket_capacity").value = 10;
            document.getElementById("leak_rate").value = 3;
            document.getElementById("incoming_packets").value = "3, 3, 2, 3, 4, 3, 2, 3";
            executeSimulation(true);
        });
    }
    if (pOverflow) {
        pOverflow.addEventListener("click", () => {
            document.getElementById("bucket_capacity").value = 10;
            document.getElementById("leak_rate").value = 2;
            document.getElementById("incoming_packets").value = "20, 25, 18, 5, 0, 0";
            executeSimulation(true);
        });
    }
}

async function executeSimulation(showNotice = true) {
    pausePlayback();

    const cap = parseInt(document.getElementById("bucket_capacity").value, 10) || 15;
    const rate = parseInt(document.getElementById("leak_rate").value, 10) || 4;
    const arrivalsStr = document.getElementById("incoming_packets").value.trim();

    const payload = {
        capacity: cap,
        leak_rate: rate,
        arrivals: arrivalsStr
    };

    const res = await fetchJson("/api/congestion/simulate", {
        method: "POST",
        body: JSON.stringify(payload)
    });

    congestionData = res;
    currentTickIndex = 0;

    // Reset Diagram & Table
    resetDiagramDisplay(cap, rate);
    clearSimulationTable();
    updateStatusBadge("SIMULATION INITIALIZED — READY", "#00f2fe");
    updateTickDisplay(0, res.events ? res.events.length : 0);
    updateKPIs(res.metrics);
    renderCongestionChart(res);

    if (showNotice) {
        showToast(`Leaky bucket simulation started: Capacity=${cap}, Rate=${rate}`, "info");
    }
}

function resetDiagramDisplay(capacity, leakRate) {
    const fillEl = document.getElementById("bucket-fill-level");
    const queueText = document.getElementById("diag-queue-text");
    const queuePct = document.getElementById("diag-queue-pct");
    const capText = document.getElementById("diag-cap-text");
    const rateText = document.getElementById("diag-rate-text");
    const incomingCount = document.getElementById("diag-incoming-count");
    const transmittedCount = document.getElementById("diag-transmitted-count");
    const overflowPill = document.getElementById("overflow-pill");
    const commentary = document.getElementById("commentary-text");

    if (fillEl) fillEl.style.height = "0%";
    if (queueText) queueText.textContent = `0 / ${capacity}`;
    if (queuePct) queuePct.textContent = "0.0% FULL";
    if (capText) capText.textContent = capacity;
    if (rateText) rateText.textContent = `${leakRate} pkts/tick`;
    if (incomingCount) incomingCount.textContent = "+0 pkts";
    if (transmittedCount) transmittedCount.textContent = "Leaked: 0 pkts";
    if (overflowPill) overflowPill.style.opacity = "0";
    if (commentary) commentary.textContent = "Parameters applied. Click 'Step Forward' or 'Auto Play' to run.";
}

function clearSimulationTable() {
    const tbody = document.getElementById("congestion-table-tbody");
    if (tbody) tbody.innerHTML = "";
}

function stepForward() {
    if (!congestionData || !congestionData.events) return;
    const events = congestionData.events;

    if (currentTickIndex >= events.length) {
        pausePlayback();
        updateStatusBadge("TRAFFIC SHAPING COMPLETED", "#34d399");
        showToast("Leaky bucket simulation reached end of timeline.", "success");
        return;
    }

    const ev = events[currentTickIndex];
    applyTickEvent(ev, congestionData.capacity, congestionData.leak_rate);
    currentTickIndex++;

    updateTickDisplay(currentTickIndex, events.length);

    if (currentTickIndex >= events.length) {
        pausePlayback();
        updateStatusBadge("TRAFFIC SHAPING COMPLETED", "#34d399");
    }
}

function applyTickEvent(ev, capacity, leakRate) {
    const fillEl = document.getElementById("bucket-fill-level");
    const queueText = document.getElementById("diag-queue-text");
    const queuePct = document.getElementById("diag-queue-pct");
    const incomingPill = document.getElementById("incoming-packet-pill");
    const incomingCount = document.getElementById("diag-incoming-count");
    const transmittedCount = document.getElementById("diag-transmitted-count");
    const overflowPill = document.getElementById("overflow-pill");
    const droppedCount = document.getElementById("diag-dropped-count");
    const diagTick = document.getElementById("diag-tick");
    const commentary = document.getElementById("commentary-text");

    if (diagTick) diagTick.textContent = ev.tick;

    // 1. Incoming packets animation
    if (incomingCount) incomingCount.textContent = `+${ev.arriving} pkts`;
    if (incomingPill) {
        incomingPill.style.transform = "scale(1.08)";
        setTimeout(() => { incomingPill.style.transform = "scale(1)"; }, 250);
    }

    // 2. Queue fill height
    const pct = capacity > 0 ? Math.min(100, Math.round((ev.queue_after / capacity) * 100)) : 0;
    if (fillEl) fillEl.style.height = `${pct}%`;
    if (queueText) queueText.textContent = `${ev.queue_after} / ${capacity}`;
    if (queuePct) queuePct.textContent = `${pct.toFixed(1)}% FULL`;

    // 3. Overflow drops
    if (overflowPill && droppedCount) {
        if (ev.dropped > 0) {
            droppedCount.textContent = `-${ev.dropped} pkts`;
            overflowPill.style.opacity = "1";
        } else {
            overflowPill.style.opacity = "0";
        }
    }

    // 4. Transmitted output
    if (transmittedCount) {
        transmittedCount.textContent = `Leaked: ${ev.leaked} pkts`;
    }

    // 5. Commentary
    if (commentary) {
        commentary.textContent = `[Tick ${ev.tick}] Arrived: ${ev.arriving} | Admitted: ${ev.admitted} | Dropped: ${ev.dropped} | Leaked: ${ev.leaked} | Residual Queue: ${ev.queue_after}`;
    }

    // 6. Append table row
    appendTableRow(ev);
}

function appendTableRow(ev) {
    const tbody = document.getElementById("congestion-table-tbody");
    if (!tbody) return;

    const tr = document.createElement("tr");
    tr.style.cssText = "border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.2s;";

    const dropColor = ev.dropped > 0 ? "#f87171" : "#64748b";
    tr.innerHTML = `
        <td style="padding: 0.5rem 0.75rem; color: #64748b;">${ev.tick}</td>
        <td style="padding: 0.5rem 0.75rem; color: #00f2fe; font-weight: 700;">${ev.arriving}</td>
        <td style="padding: 0.5rem 0.75rem; color: #34d399; font-weight: 700;">${ev.leaked}</td>
        <td style="padding: 0.5rem 0.75rem; color: ${dropColor}; font-weight: 700;">${ev.dropped}</td>
        <td style="padding: 0.5rem 0.75rem; color: #cbd5e1;">${ev.queue_before}</td>
        <td style="padding: 0.5rem 0.75rem; color: #fbbf24; font-weight: 700;">${ev.queue_after}</td>
        <td style="padding: 0.5rem 0.75rem; color: #94a3b8;">${ev.description}</td>
    `;

    tbody.appendChild(tr);
    tbody.parentElement.parentElement.scrollTop = tbody.parentElement.parentElement.scrollHeight;
}

function updateKPIs(metrics) {
    if (!metrics) return;

    const elIn = document.getElementById("val-total-incoming");
    const elTrans = document.getElementById("val-total-transmitted");
    const elDrop = document.getElementById("val-total-dropped");
    const elQueue = document.getElementById("val-remaining-queue");
    const elLoss = document.getElementById("val-loss-pct");
    const elEff = document.getElementById("val-eff-pct");

    if (elIn) elIn.textContent = metrics.total_incoming;
    if (elTrans) elTrans.textContent = metrics.total_transmitted;
    if (elDrop) elDrop.textContent = metrics.total_dropped;
    if (elQueue) elQueue.textContent = metrics.remaining_queue;
    if (elLoss) elLoss.textContent = `${metrics.loss_percentage.toFixed(1)}%`;
    if (elEff) elEff.textContent = `${metrics.efficiency_percentage.toFixed(1)}%`;
}

function updateStatusBadge(text, color) {
    const badgeText = document.getElementById("congestion-status-text");
    const dot = document.querySelector("#congestion-status-badge .status-dot");
    if (badgeText) badgeText.textContent = text;
    if (dot) dot.style.background = color;
}

function updateTickDisplay(current, total) {
    const dTick = document.getElementById("disp-tick-num");
    const dTotal = document.getElementById("disp-total-ticks");
    if (dTick) dTick.textContent = current;
    if (dTotal) dTotal.textContent = total;
}

function renderCongestionChart(data) {
    const canvas = document.getElementById("leakyBucketChart");
    if (!canvas || !data.time_series) return;

    if (congestionChartInstance) {
        congestionChartInstance.destroy();
        congestionChartInstance = null;
    }

    const ts = data.time_series;
    const labels = ts.ticks.map(t => `Tick ${t}`);

    congestionChartInstance = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Incoming Burst (pkts)",
                    data: ts.incoming,
                    borderColor: "#00f2fe",
                    backgroundColor: "rgba(0, 242, 254, 0.15)",
                    borderWidth: 2,
                    tension: 0.1
                },
                {
                    label: "Leaked / Transmitted (pkts)",
                    data: ts.transmitted,
                    borderColor: "#34d399",
                    backgroundColor: "rgba(52, 211, 153, 0.2)",
                    borderWidth: 2.5,
                    tension: 0.1
                },
                {
                    label: "Queue Fill (pkts)",
                    data: ts.queue_level,
                    borderColor: "#fbbf24",
                    backgroundColor: "rgba(251, 191, 36, 0.12)",
                    borderWidth: 2,
                    borderDash: [4, 4],
                    fill: true,
                    tension: 0.2
                },
                {
                    label: "Dropped Overflows (pkts)",
                    data: ts.dropped,
                    borderColor: "#f87171",
                    backgroundColor: "rgba(248, 113, 113, 0.4)",
                    borderWidth: 2,
                    type: "bar"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#cbd5e1", font: { size: 10 } } }
            },
            scales: {
                x: { ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(255, 255, 255, 0.05)" } },
                y: { beginAtZero: true, ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(255, 255, 255, 0.05)" } }
            }
        }
    });
}

function startPlayback() {
    if (isPlaying) return;
    isPlaying = true;

    const playBtn = document.getElementById("btn-play");
    const pauseBtn = document.getElementById("btn-pause");
    if (playBtn) playBtn.disabled = true;
    if (pauseBtn) pauseBtn.disabled = false;

    updateStatusBadge("SIMULATION RUNNING — AUTO PLAY", "#00f2fe");

    const speedMs = parseInt(document.getElementById("sim_speed").value, 10) || 750;

    playInterval = setInterval(() => {
        if (!congestionData || !congestionData.events || currentTickIndex >= congestionData.events.length) {
            pausePlayback();
            return;
        }
        stepForward();
    }, speedMs);
}

function pausePlayback() {
    isPlaying = false;
    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
    }

    const playBtn = document.getElementById("btn-play");
    const pauseBtn = document.getElementById("btn-pause");
    if (playBtn) playBtn.disabled = false;
    if (pauseBtn) pauseBtn.disabled = true;

    if (congestionData && currentTickIndex > 0 && currentTickIndex < congestionData.events.length) {
        updateStatusBadge("SIMULATION PAUSED", "#fbbf24");
    }
}

async function resetSimulation() {
    pausePlayback();
    try {
        await fetchJson("/api/congestion/reset", { method: "POST" });
        await executeSimulation(false);
        showToast("Congestion simulation reset.", "info");
    } catch (err) {
        console.error("Reset error:", err);
    }
}

