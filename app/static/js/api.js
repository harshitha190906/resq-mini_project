/**
 * ResQNet - Frontend API Client (api.js)
 * Clean, promise-based fetch wrappers for all backend simulation endpoints.
 */
"use strict";

async function fetchJson(url, options = {}) {
    const defaultHeaders = {
        "Accept": "application/json"
    };
    if (options.body && typeof options.body === "string") {
        defaultHeaders["Content-Type"] = "application/json";
    }

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...(options.headers || {})
        }
    };

    const resp = await fetch(url, config);
    if (!resp.ok) {
        let errMessage = `HTTP ${resp.status} ${resp.statusText}`;
        try {
            const errData = await resp.json();
            if (errData && errData.error) errMessage = errData.error;
        } catch (_) {
            const txt = await resp.text();
            if (txt) errMessage = txt;
        }
        throw new Error(errMessage);
    }
    return await resp.json();
}

function showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        Object.assign(container.style, {
            position: "fixed",
            bottom: "1.25rem",
            right: "1.25rem",
            zIndex: "9999",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
            pointerEvents: "none"
        });
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.textContent = message;
    toast.className = `toast toast-${type}`;
    
    let bg = "var(--surface-2, #1b1b3a)";
    let border = "1px solid var(--border-color, #405d94)";
    let color = "var(--text-main, #f1f5f9)";
    if (type === "success") {
        bg = "rgba(16, 185, 129, 0.9)";
        color = "#042f1a";
        border = "1px solid #10b981";
    } else if (type === "error") {
        bg = "rgba(239, 68, 68, 0.9)";
        color = "#ffffff";
        border = "1px solid #ef4444";
    } else if (type === "warn" || type === "alert") {
        bg = "rgba(245, 158, 11, 0.9)";
        color = "#1f1300";
        border = "1px solid #f59e0b";
    }

    Object.assign(toast.style, {
        background: bg,
        color: color,
        border: border,
        padding: "0.65rem 1.1rem",
        borderRadius: "8px",
        fontSize: "0.85rem",
        fontWeight: "600",
        boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
        transition: "all 0.3s ease",
        opacity: "0",
        transform: "translateY(10px)",
        pointerEvents: "auto"
    });

    container.appendChild(toast);
    requestAnimationFrame(() => {
        toast.style.opacity = "1";
        toast.style.transform = "translateY(0)";
    });

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px)";
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// Global API Object
const ResQNetAPI = {
    getHealth: () => fetchJson("/api/health"),
    getTopology: () => fetchJson("/api/topology"),
    getMetrics: () => fetchJson("/api/metrics"),
    getEvents: () => fetchJson("/api/events"),
    startSimulation: (params = {}) => fetchJson("/api/simulation/start", {
        method: "POST",
        body: JSON.stringify(params)
    }),
    resetSimulation: () => fetchJson("/api/simulation/reset", {
        method: "POST"
    }),
    calculateDijkstra: (source, destination) => fetchJson("/api/routing/dijkstra", {
        method: "POST",
        body: JSON.stringify({ source, destination })
    }),
    calculateDistanceVector: (source, destination) => fetchJson("/api/routing/distance-vector", {
        method: "POST",
        body: JSON.stringify({ source, destination })
    }),
    toggleLink: (node_a, node_b) => fetchJson("/api/links/toggle", {
        method: "POST",
        body: JSON.stringify({ node_a, node_b })
    }),
    failLink: (node_a, node_b) => fetchJson("/api/links/fail", {
        method: "POST",
        body: JSON.stringify({ node_a, node_b })
    }),
    restoreLink: (node_a, node_b) => fetchJson("/api/links/restore", {
        method: "POST",
        body: JSON.stringify({ node_a, node_b })
    }),
    // Go-Back-N Protocol API
    runGBN: (params = {}) => fetchJson("/api/go-back-n/run", {
        method: "POST",
        body: JSON.stringify(params)
    }),
    initGBN: (params = {}) => fetchJson("/api/go-back-n/init", {
        method: "POST",
        body: JSON.stringify(params)
    }),
    stepGBN: (stepIndex = null) => fetchJson("/api/go-back-n/step", {
        method: "POST",
        body: JSON.stringify(stepIndex !== null ? { step_index: stepIndex } : {})
    }),
    playGBN: () => fetchJson("/api/go-back-n/play", {
        method: "POST"
    }),
    resetGBN: () => fetchJson("/api/go-back-n/reset", {
        method: "POST"
    }),
    getGBNState: () => fetchJson("/api/go-back-n/state"),
    getGBNStats: () => fetchJson("/api/go-back-n/stats"),

    // Congestion Control (Leaky Bucket) API
    getCongestionStatus: () => fetchJson("/api/congestion/status"),
    simulateCongestion: (params = {}) => fetchJson("/api/congestion/simulate", {
        method: "POST",
        body: JSON.stringify(params)
    }),
    resetCongestion: () => fetchJson("/api/congestion/reset", {
        method: "POST"
    }),

    // Performance Analytics API
    getAnalyticsOverview: () => fetchJson("/api/analytics/overview"),
    getAnalyticsPerformance: () => fetchJson("/api/analytics/performance"),
    compareAnalytics: (params = {}) => fetchJson("/api/analytics/compare", {
        method: "POST",
        body: JSON.stringify(params)
    }),

    // Simulation History API
    getHistory: (params = {}) => {
        const query = new URLSearchParams(params).toString();
        return fetchJson(`/api/history${query ? '?' + query : ''}`);
    },
    getHistoryDetail: (id) => fetchJson(`/api/history/${encodeURIComponent(id)}`),
    deleteHistory: (id) => fetchJson(`/api/history/${encodeURIComponent(id)}`, {
        method: "DELETE"
    }),
    clearHistory: () => fetchJson("/api/history/clear", {
        method: "DELETE"
    })
};

window.fetchJson = fetchJson;
window.showToast = showToast;
window.ResQNetAPI = ResQNetAPI;

