/**
 * ResQNet - Routing Simulator & Disaster Link Failure Interactive Controller
 */
"use strict";

let visualizer = null;
let currentTopology = null;
let lastDijkstraPath = [];

// Predefined disaster links mapping
const PREDEFINED_DISASTER_LINKS = {
    btnFailLink1: { u: "PS-01", v: "ECC-01", name: "POL ↔ ECC (Command Link)", badgeId: "badgeLink1" },
    btnFailLink2: { u: "PS-01", v: "RTR-01", name: "POL ↔ R1 (North Relay Link)", badgeId: "badgeLink2" },
    btnFailLink3: { u: "FS-01", v: "RTR-02", name: "FIRE ↔ R2 (East Sector Relay)", badgeId: "badgeLink3" }
};

document.addEventListener("DOMContentLoaded", async () => {
    initVisualizer();
    await loadTopology();
    initHandlers();
});

function initVisualizer() {
    const canvas = document.getElementById("networkCanvas");
    if (!canvas) return;

    if (typeof NetworkVisualizer !== "undefined") {
        visualizer = new NetworkVisualizer(
            "networkCanvas",
            (node) => onNodeSelected(node),
            (u, v) => onCanvasLinkToggled(u, v)
        );
    }
}

async function loadTopology() {
    try {
        const resp = await fetch("/api/topology");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        currentTopology = await resp.json();

        if (visualizer && currentTopology) {
            visualizer.setData(currentTopology);
            if (lastDijkstraPath.length > 0) {
                visualizer.setPath(lastDijkstraPath);
            }
        }

        populateNodeSelectors(currentTopology.nodes || []);
        populateNodeDirectory(currentTopology.nodes || []);
        updateDisasterLinkButtons(currentTopology.links || []);
    } catch (err) {
        console.error("Error loading topology:", err);
    }
}

function populateNodeSelectors(nodes) {
    const srcSel = document.getElementById("routeSource");
    const dstSel = document.getElementById("routeTarget");
    if (!srcSel || !dstSel) return;

    // Save previous selections if existing
    const currentSrc = srcSel.value;
    const currentDst = dstSel.value;

    srcSel.innerHTML = "";
    dstSel.innerHTML = "";

    nodes.forEach((n, idx) => {
        const opt1 = document.createElement("option");
        opt1.value = n.node_id || n.id;
        opt1.textContent = `${n.name} (${n.node_id || n.id})`;
        srcSel.appendChild(opt1);

        const opt2 = document.createElement("option");
        opt2.value = n.node_id || n.id;
        opt2.textContent = `${n.name} (${n.node_id || n.id})`;
        dstSel.appendChild(opt2);
    });

    // Default: Shelter North (SHL-01) -> Control Center (ECC-01)
    if (currentSrc && nodes.some(n => (n.node_id || n.id) === currentSrc)) {
        srcSel.value = currentSrc;
    } else {
        const defaultSrc = nodes.find(n => (n.node_id || n.id) === "SHL-01") ? "SHL-01" : nodes[0]?.node_id;
        if (defaultSrc) srcSel.value = defaultSrc;
    }

    if (currentDst && nodes.some(n => (n.node_id || n.id) === currentDst)) {
        dstSel.value = currentDst;
    } else {
        const defaultDst = nodes.find(n => (n.node_id || n.id) === "ECC-01") ? "ECC-01" : nodes[nodes.length - 1]?.node_id;
        if (defaultDst) dstSel.value = defaultDst;
    }
}

function populateNodeDirectory(nodes) {
    const dir = document.getElementById("nodeDirectoryList");
    if (!dir) return;
    dir.innerHTML = "";

    nodes.forEach(n => {
        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.justifyContent = "space-between";
        row.style.alignItems = "center";
        row.style.padding = "0.4rem 0.6rem";
        row.style.background = "rgba(255,255,255,0.03)";
        row.style.borderRadius = "6px";
        row.style.fontSize = "0.78rem";

        let typeClass = "service";
        const t = (n.node_type || n.type || "").toLowerCase();
        if (t.includes("control") || t.includes("center")) typeClass = "center";
        else if (t.includes("relay") || t.includes("router")) typeClass = "relay";
        else if (t.includes("shelter")) typeClass = "shelter";
        else if (t.includes("field")) typeClass = "field";

        row.innerHTML = `
            <div>
                <strong style="color: #fff;">${n.node_id || n.id}</strong> - 
                <span style="color: #94a3b8;">${n.name}</span>
            </div>
            <span class="tag-badge ${typeClass}">${n.node_type || n.type}</span>
        `;
        dir.appendChild(row);
    });
}

function updateDisasterLinkButtons(links) {
    Object.entries(PREDEFINED_DISASTER_LINKS).forEach(([btnId, cfg]) => {
        const btn = document.getElementById(btnId);
        const badge = document.getElementById(cfg.badgeId);
        if (!btn || !badge) return;

        // Check if link u -> v is operational
        const forwardLink = links.find(l => (l.source_id === cfg.u || l.u === cfg.u) && (l.target_id === cfg.v || l.v === cfg.v));
        const isActive = forwardLink ? (forwardLink.status === "operational" || forwardLink.is_active === true) : true;

        if (isActive) {
            badge.textContent = "ACTIVE";
            badge.style.background = "rgba(16, 185, 129, 0.2)";
            badge.style.color = "#34d399";
            btn.style.borderColor = "rgba(16, 185, 129, 0.4)";
            btn.style.background = "rgba(16, 185, 129, 0.08)";
        } else {
            badge.textContent = "FAILED";
            badge.style.background = "rgba(239, 68, 68, 0.25)";
            badge.style.color = "#f87171";
            btn.style.borderColor = "rgba(239, 68, 68, 0.7)";
            btn.style.background = "rgba(239, 68, 68, 0.25)";
        }
    });
}

function onNodeSelected(node) {
    const srcSel = document.getElementById("routeSource");
    const dstSel = document.getElementById("routeTarget");
    const nid = node.node_id || node.id;
    if (srcSel && srcSel.value !== nid) {
        srcSel.value = nid;
        calculateRoute();
    } else if (dstSel) {
        dstSel.value = nid;
        calculateRoute();
    }
}

async function onCanvasLinkToggled(u, v) {
    await toggleLink(u, v, `Link ${u} ↔ ${v}`);
}

async function toggleLink(u, v, description) {
    try {
        const resp = await fetch("/api/links/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ node_a: u, node_b: v })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Toggle failed");

        appendDisasterEvent(
            `[DISASTER SIM] ${description} ${data.is_active ? "RESTORED to ACTIVE status" : "SEVERED (Failed)"}.`,
            data.is_active ? "success" : "alert"
        );

        await loadTopology();

        // Automatically recalculate routes to show reroute or unreachable notice
        const src = document.getElementById("routeSource")?.value;
        const dst = document.getElementById("routeTarget")?.value;
        if (src && dst) {
            calculateRoute(true, description, data.is_active);
        }
    } catch (err) {
        console.error("Link toggle error:", err);
        appendDisasterEvent(`[ERROR] Failed to toggle link: ${err.message}`, "error");
    }
}

function appendDisasterEvent(text, type = "info") {
    const container = document.getElementById("disasterEventHistory");
    if (!container) return;

    const row = document.createElement("div");
    const time = new Date().toLocaleTimeString();
    let color = "#94a3b8";
    if (type === "alert") color = "#f87171";
    if (type === "success") color = "#34d399";
    if (type === "error") color = "#ef4444";

    row.innerHTML = `<span style="color: #64748b;">[${time}]</span> <span style="color: ${color};">${text}</span>`;
    container.insertBefore(row, container.firstChild);
}

async function calculateRoute(isRecalculation = false, triggeringLink = null, linkRestored = null) {
    const srcSel = document.getElementById("routeSource");
    const dstSel = document.getElementById("routeTarget");
    if (!srcSel || !dstSel) return;

    const source = srcSel.value;
    const target = dstSel.value;

    if (!source || !target) {
        alert("Please select both Source and Destination nodes.");
        return;
    }

    if (source === target) {
        alert("Source and Destination must be different nodes.");
        return;
    }

    // Set loading indicator
    const loading = document.getElementById("routeLoadingIndicator");
    const resultsContainer = document.getElementById("routeResultsContainer");
    const initialInstructions = document.getElementById("routeInitialInstructions");
    const unreachableAlert = document.getElementById("routeUnreachableAlert");
    const matchBadge = document.getElementById("routeMatchBadge");

    if (initialInstructions) initialInstructions.style.display = "none";
    if (loading) loading.style.display = "block";
    if (unreachableAlert) unreachableAlert.style.display = "none";

    // Clear previous relaxation log
    const stepList = document.getElementById("dijkstraStepList");
    if (stepList) {
        stepList.innerHTML = '<div class="log-entry" style="color: #64748b;"><span>Running Dijkstra relaxation min-heap...</span></div>';
    }

    try {
        // Fetch both Dijkstra and Distance Vector concurrently
        const [dijkstraResp, dvResp] = await Promise.all([
            fetch("/api/routing/dijkstra", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ source: source, destination: target })
            }),
            fetch("/api/routing/distance-vector", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ source: source, destination: target })
            })
        ]);

        const dijkstraData = await dijkstraResp.json();
        const dvData = await dvResp.json();

        if (loading) loading.style.display = "none";

        if (!dijkstraResp.ok || !dvResp.ok) {
            const errorMsg = dijkstraData.error || dvData.error || "Routing computation failed";
            throw new Error(errorMsg);
        }

        // Render relaxation log
        renderDijkstraLog(dijkstraData.log || []);

        // Process Reachability
        if (dijkstraData.reachable && dijkstraData.path && dijkstraData.path.length > 0) {
            if (unreachableAlert) unreachableAlert.style.display = "none";
            if (resultsContainer) resultsContainer.style.display = "block";

            lastDijkstraPath = dijkstraData.path;
            if (visualizer) {
                visualizer.setPath(dijkstraData.path);
            }

            renderDijkstraResults(dijkstraData);
            renderDistanceVectorResults(dvData);
            compareProtocols(dijkstraData, dvData);

            if (isRecalculation && triggeringLink) {
                const action = linkRestored ? "restored" : "failed";
                appendDisasterEvent(
                    `[REROUTE EVENT] Link ${triggeringLink} ${action} -> Alternative optimal path calculated: ${dijkstraData.path.join(" ➔ ")} (Cost: ${dijkstraData.total_cost})`,
                    "info"
                );
            }
        } else {
            // Unreachable State: NEVER show misleading zeros or fake routes
            lastDijkstraPath = [];
            if (visualizer) {
                visualizer.setPath([]);
            }

            if (resultsContainer) resultsContainer.style.display = "none";
            if (unreachableAlert) {
                unreachableAlert.style.display = "block";
                const msgEl = document.getElementById("unreachableMessage");
                if (msgEl) {
                    msgEl.textContent = `No available route between '${source}' and '${target}'. Destination unreachable.`;
                }
            }

            if (isRecalculation && triggeringLink) {
                appendDisasterEvent(
                    `[CRITICAL ALERT] Failure of ${triggeringLink} has severed all paths from ${source} to ${target}! Destination is UNREACHABLE.`,
                    "alert"
                );
            }
        }
    } catch (err) {
        if (loading) loading.style.display = "none";
        console.error("Routing error:", err);
        if (unreachableAlert) {
            unreachableAlert.style.display = "block";
            const msgEl = document.getElementById("unreachableMessage");
            if (msgEl) msgEl.textContent = `Error: ${err.message}`;
        }
    }
}

function renderDijkstraResults(data) {
    document.getElementById("metricDijkstraCost").textContent = data.total_cost != null ? data.total_cost.toFixed(1) : "N/A";
    document.getElementById("metricDijkstraDelay").textContent = data.total_delay_ms != null ? data.total_delay_ms.toFixed(1) + " ms" : "N/A";
    document.getElementById("metricDijkstraHops").textContent = data.hops != null ? data.hops : "0";
    document.getElementById("metricDijkstraBW").textContent = data.bottleneck_bw_mbps != null ? data.bottleneck_bw_mbps + " Mbps" : "N/A";

    const pathContainer = document.getElementById("dijkstraPathDisplay");
    if (pathContainer && data.path) {
        pathContainer.innerHTML = data.path.map((nodeId, idx) => {
            const isSrc = idx === 0;
            const isDst = idx === data.path.length - 1;
            const name = (data.path_names && data.path_names[idx]) ? data.path_names[idx] : nodeId;
            return `
                <span class="path-node ${isSrc ? 'src' : (isDst ? 'dst' : '')}" title="${name}">
                    ${name} (${nodeId})
                </span>
                ${idx < data.path.length - 1 ? '<span class="path-arrow">➔</span>' : ''}
            `;
        }).join("");
    }

    // Populate Hop-by-Hop Link Diagnostics Table
    const tbody = document.getElementById("routeLinksTableBody");
    if (tbody && data.links) {
        tbody.innerHTML = "";
        data.links.forEach((lnk, idx) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>Hop ${idx + 1}</strong></td>
                <td><code>${lnk.source_id} ➔ ${lnk.target_id}</code></td>
                <td>${lnk.cost}</td>
                <td>${lnk.latency_ms} ms</td>
                <td>${lnk.bandwidth_mbps} Mbps</td>
                <td><span class="tag-badge ${lnk.status === 'operational' ? 'shelter' : 'center'}">${lnk.status.toUpperCase()}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }
}

function renderDistanceVectorResults(data) {
    document.getElementById("metricDvCost").textContent = data.total_cost != null ? data.total_cost.toFixed(1) : "N/A";
    document.getElementById("metricDvDelay").textContent = data.total_delay_ms != null ? data.total_delay_ms.toFixed(1) + " ms" : "N/A";
    document.getElementById("metricDvHops").textContent = data.hops != null ? data.hops : "0";
    document.getElementById("metricDvBW").textContent = data.bottleneck_bw_mbps != null ? data.bottleneck_bw_mbps + " Mbps" : "N/A";

    const pathContainer = document.getElementById("dvPathDisplay");
    if (pathContainer) {
        if (data.reachable && data.path && data.path.length > 0) {
            pathContainer.innerHTML = data.path.map((nodeId, idx) => {
                const name = (data.path_names && data.path_names[idx]) ? data.path_names[idx] : nodeId;
                return `
                    <span class="path-node" style="border-color: #a855f7; color: #d8b4fe;" title="${name}">
                        ${name} (${nodeId})
                    </span>
                    ${idx < data.path.length - 1 ? '<span class="path-arrow" style="color: #c084fc;">➔</span>' : ''}
                `;
            }).join("");
        } else {
            pathContainer.innerHTML = '<span style="color: #f87171;">Unreachable via Distance Vector</span>';
        }
    }

    const badge = document.getElementById("dvConvergedBadge");
    if (badge) {
        badge.textContent = data.converged ? `CONVERGED (${data.iterations} ROUNDS)` : "NOT CONVERGED";
    }
}

function compareProtocols(dijkstra, dv) {
    const badge = document.getElementById("routeMatchBadge");
    const text = document.getElementById("routeMatchText");
    if (!badge || !text) return;

    badge.style.display = "inline-flex";
    const dPath = (dijkstra.path || []).join("->");
    const dvPath = (dv.path || []).join("->");

    if (dPath === dvPath) {
        badge.className = "status-badge";
        text.textContent = "Dijkstra & DV Paths Match (Optimal)";
    } else {
        badge.className = "status-badge alert";
        text.textContent = "Routes Diverge (DV Multi-Path / Asymmetric)";
    }
}

function renderDijkstraLog(log) {
    const stepList = document.getElementById("dijkstraStepList");
    const countBadge = document.getElementById("logStepCount");
    if (!stepList) return;

    stepList.innerHTML = "";
    if (countBadge) {
        countBadge.textContent = `${log.length} steps`;
    }

    if (log.length === 0) {
        stepList.innerHTML = '<div class="log-entry" style="color: #64748b;"><span>No events recorded.</span></div>';
        return;
    }

    log.forEach(item => {
        const row = document.createElement("div");
        row.className = "log-entry";

        let tagClass = "tag-info";
        let tagLabel = "EVAL";

        switch (item.event_type) {
            case "start":
                tagClass = "tag-info"; tagLabel = "START"; break;
            case "init":
                tagClass = "tag-info"; tagLabel = "INIT"; break;
            case "visit":
                tagClass = "tag-info"; tagLabel = "VISIT"; break;
            case "evaluate":
                tagClass = "tag-info"; tagLabel = "EVAL"; break;
            case "update":
                tagClass = "tag-success"; tagLabel = "RELAX / UPDATE"; break;
            case "skip_failed":
                tagClass = "tag-error"; tagLabel = "FAILED LINK SKIPPED"; break;
            case "skip_visited":
                tagClass = "tag-warn"; tagLabel = "SETTLED"; break;
            case "destination_reached":
                tagClass = "tag-success"; tagLabel = "DEST REACHED"; break;
            case "complete":
                tagClass = "tag-success"; tagLabel = "SUCCESS"; break;
            case "unreachable":
                tagClass = "tag-error"; tagLabel = "UNREACHABLE"; break;
            default:
                tagClass = "tag-info"; tagLabel = item.event_type.toUpperCase();
        }

        row.innerHTML = `
            <span style="color: #64748b; font-size: 0.72rem; min-width: 45px;">[#${item.step}]</span>
            <span class="log-tag ${tagClass}">${tagLabel}</span>
            <span style="color: #cbd5e1;">${item.message}</span>
        `;
        stepList.appendChild(row);
    });

    stepList.scrollTop = stepList.scrollHeight;
}

function initHandlers() {
    document.getElementById("btnCalculateRoute")?.addEventListener("click", () => calculateRoute(false));
    document.getElementById("routeSource")?.addEventListener("change", () => calculateRoute(false));
    document.getElementById("routeTarget")?.addEventListener("change", () => calculateRoute(false));

    // Three disaster failure buttons
    document.getElementById("btnFailLink1")?.addEventListener("click", () => {
        const cfg = PREDEFINED_DISASTER_LINKS.btnFailLink1;
        toggleLink(cfg.u, cfg.v, cfg.name);
    });

    document.getElementById("btnFailLink2")?.addEventListener("click", () => {
        const cfg = PREDEFINED_DISASTER_LINKS.btnFailLink2;
        toggleLink(cfg.u, cfg.v, cfg.name);
    });

    document.getElementById("btnFailLink3")?.addEventListener("click", () => {
        const cfg = PREDEFINED_DISASTER_LINKS.btnFailLink3;
        toggleLink(cfg.u, cfg.v, cfg.name);
    });

    // Reset button
    document.getElementById("btnResetTopology")?.addEventListener("click", async () => {
        try {
            await fetch("/api/simulation/reset", { method: "POST" });
            appendDisasterEvent("[MAINTENANCE] Topology reset to factory disaster-safe state.", "success");
            await loadTopology();
            calculateRoute(false);
        } catch (err) {
            console.error("Reset error:", err);
        }
    });
}

