// app.js – tiny helper utilities
"use strict";

/** Simple wrapper for GET JSON **/
async function fetchJson(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${txt}`);
  }
  return await resp.json();
}

/** Toast UI – shows a temporary message **/
function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.textContent = message;
  toast.className = `toast toast-${type}`;
  Object.assign(toast.style, {
    position: "fixed",
    bottom: "1rem",
    right: "1rem",
    background: type === "error" ? "var(--error)" : "var(--accent)",
    color: "#000",
    padding: "0.6rem 1rem",
    borderRadius: "6px",
    zIndex: 2000,
    boxShadow: "0 2px 8px rgba(0,0,0,0.3)"
  });
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// Export for other modules (if using modules, but we keep globals for simplicity)
window.fetchJson = fetchJson;
window.showToast = showToast;
