/**
 * ResQNet - Dashboard Logic (dashboard.js)
 * Network Operations Center real-time telemetry, responsive SVG topology,
 * and Chart.js performance curve visualization.
 */
"use strict";

// Global Chart instances to safely destroy and re-create without canvas collision
let deliveryChartInstance = null;
let lossChartInstance = null;
let delayThroughputChartInstance = null;

// Initialize when DOM content is loaded
document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
    setupSimulationControls();
});

/**
 * Main dashboard data loader: fetches health, topology, and metrics from backend.
 */
async function initDashboard() {
    try {
        // Fetch health, topology and metrics in parallel
        const [healthRes, topoRes, metricsRes] = await Promise.all([
            fetchJson("/api/health").catch(err => ({ status: "error", error: err.message })),
            fetchJson("/api/topology"),
            fetchJson("/api/metrics")
        ]);

        // Update system status header
        updateSystemStatus(healthRes, metricsRes);

        // Populate summary metric cards
        populateMetricCards(topoRes, metricsRes);

        // Render responsive SVG Network Topology Preview
        renderTopologyPreview(topoRes);

        // Render or reset performance charts
        renderCharts(metricsRes);

    } catch (err) {
        console.error("Dashboard initialization error:", err);
        showToast("Failed to load dashboard telemetry: " + err.message, "error");
    }
}

/**
 * Update top-right status indicator
 */
function updateSystemStatus(healthRes, metrics) {
    const statusText = document.getElementById("sim-status-text");
    const statusDot = document.querySelector("#sim-status-badge .status-dot");
    
    if (healthRes.status !== "ok") {
        if (statusText) statusText.textContent = "BACKEND DISCONNECTED";
        if (statusDot) statusDot.style.background = "#f87171";
        return;
    }

    if (metrics && metrics.has_data) {
        if (statusText) statusText.textContent = `TELEMETRY ACTIVE — ${metrics.sent} PACKETS EVALUATED`;
        if (statusDot) statusDot.style.background = "#34d399";
    } else {
        if (statusText) statusText.textContent = "SYSTEM ONLINE — READY FOR SIMULATION";
        if (statusDot) statusDot.style.background = "#00f2fe";
    }
}

/**
 * Populate all 3 overview cards with real backend data
 */
function populateMetricCards(topology, metrics) {
    // 1. Network Overview Card
    const totalNodes = topology.summary ? topology.summary.total_nodes : (topology.nodes ? topology.nodes.length : 0);
    const activeLinks = topology.summary ? topology.summary.active_links : 0;
    const failedLinks = topology.summary ? topology.summary.failed_links : 0;

    const elTotalNodes = document.getElementById("val-total-nodes");
    const elActiveLinks = document.getElementById("val-active-links");
    const elFailedLinks = document.getElementById("val-failed-links");

    if (elTotalNodes) elTotalNodes.textContent = totalNodes;
    if (elActiveLinks) elActiveLinks.textContent = activeLinks;
    if (elFailedLinks) {
        elFailedLinks.textContent = failedLinks;
        elFailedLinks.style.color = failedLinks > 0 ? "#f87171" : "#94a3b8";
    }

    // Status badges on cards
    const badgeMsg = document.getElementById("badge-msg-status");
    const badgePerf = document.getElementById("badge-perf-status");

    // Elements for Message Statistics
    const elPacketsGen = document.getElementById("val-packets-generated");
    const elPacketsDel = document.getElementById("val-packets-delivered");
    const elPacketsLost = document.getElementById("val-packets-lost");
    const elRetrans = document.getElementById("val-retransmissions");

    // Elements for Performance Metrics
    const elDeliveryRatio = document.getElementById("val-delivery-ratio");
    const elLossRatio = document.getElementById("val-loss-ratio");
    const elAvgDelay = document.getElementById("val-avg-delay");
    const elThroughput = document.getElementById("val-throughput");

    if (metrics && metrics.has_data) {
        // Active simulation telemetry
        if (badgeMsg) {
            badgeMsg.textContent = "RECORDED";
            badgeMsg.style.background = "rgba(52, 211, 153, 0.15)";
            badgeMsg.style.color = "#34d399";
        }
        if (badgePerf) {
            badgePerf.textContent = "MEASURED";
            badgePerf.style.background = "rgba(0, 242, 254, 0.15)";
            badgePerf.style.color = "#00f2fe";
        }

        if (elPacketsGen) elPacketsGen.textContent = metrics.sent;
        if (elPacketsDel) elPacketsDel.textContent = metrics.delivered;
        if (elPacketsLost) elPacketsLost.textContent = metrics.lost;
        if (elRetrans) elRetrans.textContent = metrics.retransmissions;

        const delRatioPct = (metrics.delivery_ratio * 100).toFixed(1) + "%";
        const lossRatioPct = (metrics.loss_ratio * 100).toFixed(1) + "%";
        const delayStr = (metrics.avg_delay_ms !== undefined ? metrics.avg_delay_ms.toFixed(1) : (metrics.avg_delay_s * 1000).toFixed(1)) + " ms";
        const thrStr = (metrics.throughput_kbps !== undefined ? metrics.throughput_kbps.toFixed(1) : (metrics.throughput_bps / 1000).toFixed(1)) + " kbps";

        if (elDeliveryRatio) elDeliveryRatio.textContent = delRatioPct;
        if (elLossRatio) elLossRatio.textContent = lossRatioPct;
        if (elAvgDelay) elAvgDelay.textContent = delayStr;
        if (elThroughput) elThroughput.textContent = thrStr;

    } else {
        // Initial clean unsimulated state
        if (badgeMsg) {
            badgeMsg.textContent = "STANDBY";
            badgeMsg.style.background = "rgba(79, 172, 254, 0.15)";
            badgeMsg.style.color = "#4facfe";
        }
        if (badgePerf) {
            badgePerf.textContent = "IDLE";
            badgePerf.style.background = "rgba(100, 116, 139, 0.15)";
            badgePerf.style.color = "#94a3b8";
        }

        if (elPacketsGen) elPacketsGen.textContent = "–";
        if (elPacketsDel) elPacketsDel.textContent = "–";
        if (elPacketsLost) elPacketsLost.textContent = "–";
        if (elRetrans) elRetrans.textContent = "–";

        if (elDeliveryRatio) elDeliveryRatio.textContent = "Not yet measured";
        if (elLossRatio) elLossRatio.textContent = "Not yet measured";
        if (elAvgDelay) elAvgDelay.textContent = "Not yet measured";
        if (elThroughput) elThroughput.textContent = "Not yet measured";
    }
}

/**
 * Render responsive SVG Network Topology Preview inside #network-preview
 */
function renderTopologyPreview(topology) {
    const container = document.getElementById("network-preview");
    if (!container) return;

    const nodes = topology.nodes || [];
    const links = topology.links || topology.edges || [];

    if (!nodes.length) {
        container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;">No topology data available.</div>`;
        return;
    }

    // Map node IDs to positions and metadata
    const nodeMap = new Map();
    nodes.forEach(n => {
        nodeMap.set(n.id || n.node_id, n);
    });

    // Deduplicate undirected edges for clean rendering
    const edgeMap = new Map();
    links.forEach(l => {
        const u = l.u || l.source_id;
        const v = l.v || l.target_id;
        if (!u || !v) return;
        const key = [u, v].sort().join("---");
        if (!edgeMap.has(key)) {
            edgeMap.set(key, {
                u,
                v,
                is_active: l.is_active,
                cost: l.cost,
                bandwidth_mbps: l.bandwidth_mbps,
                latency_ms: l.latency_ms || l.delay_ms
            });
        } else {
            // If either direction is disabled, mark link disabled
            if (!l.is_active) {
                edgeMap.get(key).is_active = false;
            }
        }
    });

    // Node visual style definitions
    const getNodeStyle = (type) => {
        const t = (type || "").toLowerCase();
        if (t.includes("control") || t.includes("ecc")) {
            return { color: "#00f2fe", fill: "rgba(0, 242, 254, 0.18)", stroke: "#00f2fe", icon: "ECC", label: "Control Center" };
        }
        if (t.includes("police")) {
            return { color: "#38bdf8", fill: "rgba(56, 189, 248, 0.18)", stroke: "#38bdf8", icon: "POL", label: "Police" };
        }
        if (t.includes("fire")) {
            return { color: "#fb923c", fill: "rgba(251, 146, 60, 0.18)", stroke: "#fb923c", icon: "FIRE", label: "Fire Station" };
        }
        if (t.includes("ambulance")) {
            return { color: "#34d399", fill: "rgba(52, 211, 153, 0.18)", stroke: "#34d399", icon: "AMB", label: "Ambulance" };
        }
        if (t.includes("field")) {
            return { color: "#c084fc", fill: "rgba(192, 132, 252, 0.18)", stroke: "#c084fc", icon: "FT", label: "Field Team" };
        }
        if (t.includes("shelter")) {
            return { color: "#fbbf24", fill: "rgba(251, 191, 36, 0.18)", stroke: "#fbbf24", icon: "SHT", label: "Shelter" };
        }
        if (t.includes("router") || t.includes("relay")) {
            return { color: "#818cf8", fill: "rgba(129, 140, 248, 0.18)", stroke: "#818cf8", icon: "R", label: "Relay Router" };
        }
        return { color: "#94a3b8", fill: "rgba(148, 163, 184, 0.18)", stroke: "#94a3b8", icon: "NODE", label: "Node" };
    };

    // Build SVG elements
    let svgContent = `
    <svg viewBox="0 0 900 650" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style="display:block;">
        <defs>
            <filter id="glow-active" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="#00f2fe" flood-opacity="0.6"/>
            </filter>
            <filter id="glow-failed" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="4" flood-color="#ef4444" flood-opacity="0.8"/>
            </filter>
        </defs>

        <!-- Background grid pattern -->
        <g stroke="rgba(255,255,255,0.03)" stroke-width="1">
            ${Array.from({ length: 9 }, (_, i) => `<line x1="${(i+1)*100}" y1="0" x2="${(i+1)*100}" y2="650"/>`).join("")}
            ${Array.from({ length: 6 }, (_, i) => `<line x1="0" y1="${(i+1)*100}" x2="900" y2="${(i+1)*100}"/>`).join("")}
        </g>

        <!-- Edges / Links -->
        <g id="svg-links">
    `;

    edgeMap.forEach((edge) => {
        const nodeA = nodeMap.get(edge.u);
        const nodeB = nodeMap.get(edge.v);
        if (!nodeA || !nodeB) return;

        const x1 = nodeA.x;
        const y1 = nodeA.y;
        const x2 = nodeB.x;
        const y2 = nodeB.y;
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;

        if (edge.is_active) {
            svgContent += `
            <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" 
                  stroke="rgba(0, 242, 254, 0.45)" stroke-width="2.5" />
            <circle cx="${mx}" cy="${my}" r="3" fill="#00f2fe" opacity="0.6" />
            `;
        } else {
            // Failed link: dashed red line with central [FAILED] warning pill
            svgContent += `
            <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" 
                  stroke="#ef4444" stroke-width="2.5" stroke-dasharray="6,5" filter="url(#glow-failed)" />
            <g transform="translate(${mx}, ${my})">
                <rect x="-30" y="-10" width="60" height="20" rx="4" fill="#ef4444" stroke="#7f1d1d" stroke-width="1"/>
                <text x="0" y="4" text-anchor="middle" fill="#ffffff" font-size="9" font-weight="800" font-family="'JetBrains Mono', monospace">FAILED</text>
            </g>
            `;
        }
    });

    svgContent += `</g><!-- Nodes -->\n<g id="svg-nodes">`;

    // Render nodes
    nodes.forEach(n => {
        const x = n.x;
        const y = n.y;
        const style = getNodeStyle(n.node_type || n.type);
        const shortName = n.name || n.node_id;

        svgContent += `
        <g class="topology-node" style="cursor: pointer;" data-node="${n.id || n.node_id}">
            <!-- Node Outer Aura -->
            <circle cx="${x}" cy="${y}" r="26" fill="${style.fill}" stroke="${style.stroke}" stroke-width="2" filter="url(#glow-active)"/>
            <!-- Node Core -->
            <circle cx="${x}" cy="${y}" r="17" fill="#0b1120" stroke="${style.color}" stroke-width="1.5"/>
            <!-- Node Short Code -->
            <text x="${x}" y="${y + 4}" text-anchor="middle" fill="#ffffff" font-size="10" font-weight="700" font-family="'JetBrains Mono', monospace">${style.icon}</text>
            <!-- Node Label Text -->
            <text x="${x}" y="${y + 40}" text-anchor="middle" fill="#e2e8f0" font-size="11" font-weight="600" font-family="system-ui, sans-serif">${shortName}</text>
            <!-- Node Subtitle / Type -->
            <text x="${x}" y="${y + 53}" text-anchor="middle" fill="#94a3b8" font-size="9" font-family="system-ui, sans-serif">${style.label}</text>
        </g>
        `;
    });

    svgContent += `</g>`;

    // Overlay Legend inside SVG
    svgContent += `
    <g transform="translate(20, 20)">
        <rect x="0" y="0" width="180" height="85" rx="6" fill="rgba(8, 12, 22, 0.85)" stroke="rgba(64, 93, 148, 0.4)" stroke-width="1"/>
        <text x="12" y="18" fill="#94a3b8" font-size="10" font-weight="700">TOPOLOGY STATUS</text>
        
        <!-- Active link sample -->
        <line x1="14" y1="36" x2="36" y2="36" stroke="#00f2fe" stroke-width="2.5"/>
        <circle cx="25" cy="36" r="2.5" fill="#00f2fe"/>
        <text x="44" y="40" fill="#e2e8f0" font-size="10">Active Link</text>
        
        <!-- Failed link sample -->
        <line x1="14" y1="58" x2="36" y2="58" stroke="#ef4444" stroke-width="2.5" stroke-dasharray="4,3"/>
        <text x="44" y="62" fill="#f87171" font-size="10">Failed Link</text>
    </g>
    </svg>`;

    container.innerHTML = svgContent;
}

/**
 * Render or reset performance charts
 */
function renderCharts(metrics) {
    const deliveryCanvas = document.getElementById("deliveryChart");
    const lossCanvas = document.getElementById("lossChart");
    const delayThroughputCanvas = document.getElementById("delayThroughputChart");

    const deliveryEmpty = document.getElementById("deliveryChart-empty");
    const lossEmpty = document.getElementById("lossChart-empty");
    const delayThroughputEmpty = document.getElementById("delayThroughputChart-empty");

    // Destroy existing instances before recreating
    if (deliveryChartInstance) {
        deliveryChartInstance.destroy();
        deliveryChartInstance = null;
    }
    if (lossChartInstance) {
        lossChartInstance.destroy();
        lossChartInstance = null;
    }
    if (delayThroughputChartInstance) {
        delayThroughputChartInstance.destroy();
        delayThroughputChartInstance = null;
    }

    if (!metrics || !metrics.has_data || !metrics.time_series) {
        // Show placeholders
        if (deliveryEmpty) deliveryEmpty.style.display = "flex";
        if (lossEmpty) lossEmpty.style.display = "flex";
        if (delayThroughputEmpty) delayThroughputEmpty.style.display = "flex";
        return;
    }

    // Hide placeholders
    if (deliveryEmpty) deliveryEmpty.style.display = "none";
    if (lossEmpty) lossEmpty.style.display = "none";
    if (delayThroughputEmpty) delayThroughputEmpty.style.display = "none";

    const ts = metrics.time_series;
    const labels = ts.labels || [];

    // Chart.js dark theme defaults
    const commonScales = {
        x: {
            ticks: { color: "#94a3b8", font: { size: 10 } },
            grid: { color: "rgba(255, 255, 255, 0.05)" }
        },
        y: {
            beginAtZero: true,
            ticks: { color: "#94a3b8", font: { size: 10 } },
            grid: { color: "rgba(255, 255, 255, 0.05)" }
        }
    };

    // 1. Packet Delivery Over Time Chart
    if (deliveryCanvas) {
        const ctx1 = deliveryCanvas.getContext("2d");
        deliveryChartInstance = new Chart(ctx1, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Packets Delivered (Cumulative)",
                    data: ts.delivery_cumulative || [],
                    borderColor: "#34d399",
                    backgroundColor: "rgba(52, 211, 153, 0.15)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: "#e2e8f0", font: { size: 11 } } },
                    tooltip: { mode: "index", intersect: false }
                },
                scales: commonScales
            }
        });
    }

    // 2. Packet Loss Over Time Chart
    if (lossCanvas) {
        const ctx2 = lossCanvas.getContext("2d");
        lossChartInstance = new Chart(ctx2, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: "Packets Lost (Cumulative)",
                    data: ts.loss_cumulative || [],
                    borderColor: "#f87171",
                    backgroundColor: "rgba(248, 113, 113, 0.18)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: "#e2e8f0", font: { size: 11 } } },
                    tooltip: { mode: "index", intersect: false }
                },
                scales: commonScales
            }
        });
    }

    // 3. Delay & Throughput Dual-Axis Chart
    if (delayThroughputCanvas) {
        const ctx3 = delayThroughputCanvas.getContext("2d");
        delayThroughputChartInstance = new Chart(ctx3, {
            type: "line",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "End-to-End Latency (ms)",
                        data: ts.delay_ms || [],
                        borderColor: "#fbbf24",
                        backgroundColor: "rgba(251, 191, 36, 0.12)",
                        borderWidth: 2,
                        tension: 0.25,
                        yAxisID: "y",
                        pointRadius: 3
                    },
                    {
                        label: "Throughput (kbps)",
                        data: ts.throughput_kbps || [],
                        borderColor: "#00f2fe",
                        backgroundColor: "rgba(0, 242, 254, 0.12)",
                        borderWidth: 2,
                        tension: 0.25,
                        yAxisID: "y1",
                        pointRadius: 3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: "#e2e8f0", font: { size: 11 } } },
                    tooltip: { mode: "index", intersect: false }
                },
                scales: {
                    x: {
                        ticks: { color: "#94a3b8", font: { size: 10 } },
                        grid: { color: "rgba(255, 255, 255, 0.05)" }
                    },
                    y: {
                        type: "linear",
                        display: true,
                        position: "left",
                        title: { display: true, text: "Delay (ms)", color: "#fbbf24" },
                        ticks: { color: "#fbbf24", font: { size: 10 } },
                        grid: { color: "rgba(255, 255, 255, 0.05)" }
                    },
                    y1: {
                        type: "linear",
                        display: true,
                        position: "right",
                        title: { display: true, text: "Throughput (kbps)", color: "#00f2fe" },
                        ticks: { color: "#00f2fe", font: { size: 10 } },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
    }
}

/**
 * Wire the Start Simulation and Reset Simulation action buttons
 */
function setupSimulationControls() {
    const startBtn = document.getElementById("start-sim");
    const resetBtn = document.getElementById("reset-sim");

    if (startBtn) {
        startBtn.addEventListener("click", async () => {
            const originalHtml = startBtn.innerHTML;
            try {
                startBtn.disabled = true;
                startBtn.innerHTML = `<span class="fas fa-spinner fa-spin"></span> Simulating...`;

                const res = await fetchJson("/api/simulation/start", {
                    method: "POST",
                    body: JSON.stringify({ count: 20, traffic_level: "low" })
                });

                showToast(res.message || "Disaster communication simulation completed.", "success");
                await initDashboard();

            } catch (err) {
                console.error("Simulation execution error:", err);
                showToast("Simulation error: " + err.message, "error");
            } finally {
                startBtn.disabled = false;
                startBtn.innerHTML = originalHtml;
            }
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener("click", async () => {
            const originalHtml = resetBtn.innerHTML;
            try {
                resetBtn.disabled = true;
                resetBtn.innerHTML = `<span class="fas fa-spinner fa-spin"></span> Resetting...`;

                await fetchJson("/api/simulation/reset", { method: "POST" });
                showToast("Simulation engine and telemetry reset.", "info");
                await initDashboard();

            } catch (err) {
                console.error("Simulation reset error:", err);
                showToast("Reset error: " + err.message, "error");
            } finally {
                resetBtn.disabled = false;
                resetBtn.innerHTML = originalHtml;
            }
        });
    }
}
