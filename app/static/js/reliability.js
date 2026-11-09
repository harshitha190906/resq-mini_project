/**
 * ResQNet - Reliability & Error Recovery Lab (reliability.js)
 * Full Go-Back-N ARQ Sliding Window Visualizer, Animated Sender-Receiver Channel,
 * Space-Time Ladder Diagram, and Analytical Performance Telemetry.
 */
"use strict";

// Simulation Session State
let gbnSession = null;
let currentStepIndex = 0;
let isPlaying = false;
let playInterval = null;

// Chart.js global instances
let chartStatusInstance = null;
let chartAttemptsInstance = null;
let chartAcksInstance = null;
let chartDelaysInstance = null;
let chartEfficiencyInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    initReliabilityLab();
    bindEventListeners();
});

/**
 * Initialize lab on DOM ready
 */
async function initReliabilityLab() {
    try {
        await initializeSimulation();
    } catch (err) {
        console.error("Initialization error:", err);
        showToast("Error initializing Go-Back-N Lab: " + err.message, "error");
    }
}

/**
 * Bind UI buttons and input events
 */
function bindEventListeners() {
    const btnInit = document.getElementById("btn-init");
    const btnPlay = document.getElementById("btn-play");
    const btnPause = document.getElementById("btn-pause");
    const btnStep = document.getElementById("btn-step");
    const btnReset = document.getElementById("btn-reset");

    if (btnInit) btnInit.addEventListener("click", () => initializeSimulation());
    if (btnPlay) btnPlay.addEventListener("click", () => startPlayback());
    if (btnPause) btnPause.addEventListener("click", () => pausePlayback());
    if (btnStep) btnStep.addEventListener("click", () => stepForward());
    if (btnReset) btnReset.addEventListener("click", () => resetSimulation());

    // Event Log Filter Buttons
    const filterButtons = document.querySelectorAll(".log-filter-btn");
    filterButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            filterButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            filterEventLog(btn.dataset.filter);
        });
    });
}

/**
 * Initialize simulation session with backend API
 */
async function initializeSimulation() {
    pausePlayback();

    const totalFrames = parseInt(document.getElementById("total_frames").value, 10) || 8;
    const windowSize = parseInt(document.getElementById("window_size").value, 10) || 4;
    const timeoutTicks = parseInt(document.getElementById("timeout_ticks").value, 10) || 4;
    const lostFramesInput = document.getElementById("lost_frames").value.trim();
    const maxRetries = parseInt(document.getElementById("max_retries").value, 10) || 5;

    const payload = {
        total_frames: totalFrames,
        window_size: windowSize,
        timeout_ticks: timeoutTicks,
        lost_frames: lostFramesInput,
        max_retries: maxRetries
    };

    const res = await fetchJson("/api/go-back-n/init", {
        method: "POST",
        body: JSON.stringify(payload)
    });

    gbnSession = res;
    currentStepIndex = 0;

    // Reset UI Elements
    renderInitialSlidingWindowTrack(totalFrames, windowSize);
    resetSenderReceiverDiagram(windowSize);
    clearTimelineAndLog();
    updateParameterBadges(0, 0, 0, windowSize, res.modulus);
    updateStatusBadge("SIMULATION INITIALIZED — READY", "#00f2fe");
    updateTickStepDisplay(0, 0, res.total_events || (res.events ? res.events.length : 0));
    updateKPIs(res.analytics, 0);
    renderAnalyticalCharts(res.analytics);

    showToast("Go-Back-N session initialized.", "info");
}

/**
 * Render initial sliding window track cards
 */
function renderInitialSlidingWindowTrack(totalFrames, windowSize) {
    const track = document.getElementById("sliding-window-track");
    if (!track) return;
    track.innerHTML = "";

    const modulus = windowSize + 1;

    for (let i = 0; i < totalFrames; i++) {
        const frameBox = document.createElement("div");
        frameBox.id = `frame-box-${i}`;
        frameBox.className = "frame-card";
        
        const inWindow = i < windowSize;
        const bg = inWindow ? "rgba(0, 242, 254, 0.12)" : "rgba(15, 23, 42, 0.75)";
        const border = inWindow ? "1.5px solid #00f2fe" : "1px solid #334155";

        Object.assign(frameBox.style, {
            width: "82px",
            minWidth: "82px",
            padding: "0.6rem 0.4rem",
            borderRadius: "6px",
            background: bg,
            border: border,
            textAlign: "center",
            fontFamily: "'JetBrains Mono', monospace",
            position: "relative",
            transition: "all 0.25s ease",
            boxShadow: inWindow ? "0 0 10px rgba(0,242,254,0.25)" : "none"
        });

        const seqMod = i % modulus;
        frameBox.innerHTML = `
            <div style="font-size: 0.65rem; color: #94a3b8; text-transform: uppercase;">FRAME</div>
            <div style="font-size: 1.15rem; font-weight: 800; color: #ffffff;">#${i}</div>
            <div style="font-size: 0.72rem; color: #00f2fe; margin-top: 0.1rem;">Seq ${seqMod}</div>
            <div id="frame-tag-${i}" style="margin-top: 0.35rem; font-size: 0.65rem; font-weight: 700; padding: 0.15rem 0.3rem; border-radius: 3px; background: rgba(100,116,139,0.2); color: #94a3b8;">
                ${inWindow ? "IN-WIN" : "WAITING"}
            </div>
            <div id="frame-att-${i}" style="font-size: 0.62rem; color: #64748b; margin-top: 0.15rem;">Att: 0</div>
        `;

        track.appendChild(frameBox);
    }
}

/**
 * Reset Sender-Receiver diagram indicators
 */
function resetSenderReceiverDiagram(windowSize) {
    const senderBase = document.getElementById("sender-base-display");
    const senderNext = document.getElementById("sender-next-display");
    const senderLimit = document.getElementById("sender-limit-display");
    const timerBar = document.getElementById("sender-timer-bar");
    const timerText = document.getElementById("sender-timer-text");
    const rxExpected = document.getElementById("receiver-expected-display");
    const rxLastAck = document.getElementById("receiver-last-ack-display");
    const rxBuffer = document.getElementById("receiver-buffer-list");
    const banner = document.getElementById("channel-banner");
    const commentary = document.getElementById("commentary-text");
    const commentaryTag = document.getElementById("commentary-tag");

    if (senderBase) senderBase.textContent = "0";
    if (senderNext) senderNext.textContent = "0";
    if (senderLimit) senderLimit.textContent = windowSize;
    if (timerBar) timerBar.style.width = "0%";
    if (timerText) {
        timerText.textContent = "IDLE";
        timerText.style.color = "#94a3b8";
    }
    if (rxExpected) rxExpected.textContent = "0";
    if (rxLastAck) rxLastAck.textContent = "None";
    if (rxBuffer) rxBuffer.innerHTML = `<span style="color: #64748b; font-size: 0.7rem;">(empty)</span>`;
    if (banner) {
        banner.textContent = "CHANNEL STATUS: IDLE / READY";
        banner.style.background = "rgba(52, 211, 153, 0.15)";
        banner.style.color = "#34d399";
    }
    if (commentary) commentary.textContent = "Simulation initialized. Ready to step or play.";
    if (commentaryTag) {
        commentaryTag.textContent = "READY";
        commentaryTag.style.background = "rgba(0,242,254,0.15)";
        commentaryTag.style.color = "#00f2fe";
    }

    // Hide animation pills
    const animPkt = document.getElementById("anim-packet");
    const animAck = document.getElementById("anim-ack");
    if (animPkt) animPkt.style.opacity = "0";
    if (animAck) animAck.style.opacity = "0";
}

/**
 * Clear chronological ladder and event table
 */
function clearTimelineAndLog() {
    const ladder = document.getElementById("timeline-ladder");
    const tbody = document.getElementById("gbn-event-tbody");
    if (ladder) ladder.innerHTML = `<div style="color: #64748b; text-align: center; padding: 1.5rem 0;">Timeline empty. Advance steps to view transmission ladder.</div>`;
    if (tbody) tbody.innerHTML = "";
}

/**
 * Step Forward in simulation
 */
function stepForward() {
    if (!gbnSession || !gbnSession.events) return;
    const events = gbnSession.events;

    if (currentStepIndex >= events.length) {
        pausePlayback();
        updateStatusBadge("ALL FRAMES DELIVERED — COMPLETE", "#34d399");
        showToast("Go-Back-N simulation completed successfully.", "success");
        return;
    }

    const ev = events[currentStepIndex];
    applySimulationEvent(ev, currentStepIndex);
    currentStepIndex++;

    updateTickStepDisplay(ev.tick, currentStepIndex, events.length);

    if (currentStepIndex >= events.length) {
        pausePlayback();
        updateStatusBadge("ALL FRAMES DELIVERED — COMPLETE", "#34d399");
    }
}

/**
 * Apply one Go-Back-N event to UI visualizations
 */
function applySimulationEvent(ev, stepIdx) {
    const totalFrames = gbnSession.total_frames;
    const windowSize = gbnSession.window_size;
    const modulus = gbnSession.modulus;
    const base = ev.base !== undefined ? ev.base : 0;
    const nextSeq = ev.next_seq !== undefined ? ev.next_seq : 0;
    const expectedSeq = ev.expected_seq !== undefined ? ev.expected_seq : 0;

    // 1. Update Window Parameter Header Badges
    updateParameterBadges(base, nextSeq, expectedSeq, windowSize, modulus);

    // 2. Update Sender Host Indicators
    const senderBase = document.getElementById("sender-base-display");
    const senderNext = document.getElementById("sender-next-display");
    const senderLimit = document.getElementById("sender-limit-display");
    const timerBar = document.getElementById("sender-timer-bar");
    const timerText = document.getElementById("sender-timer-text");

    if (senderBase) senderBase.textContent = base;
    if (senderNext) senderNext.textContent = nextSeq;
    if (senderLimit) senderLimit.textContent = base + windowSize;

    // 3. Update Receiver Indicators
    const rxExpected = document.getElementById("receiver-expected-display");
    const rxLastAck = document.getElementById("receiver-last-ack-display");
    if (rxExpected) rxExpected.textContent = expectedSeq;

    // 4. Update Sliding Window Track Cards
    updateSlidingWindowTrackView(base, windowSize, totalFrames, ev);

    // 5. Animate Sender-Receiver Communication Channel
    animateChannelCommunication(ev);

    // 6. Update Timer Bar
    if (timerBar && timerText) {
        if (ev.event_type === "TIMEOUT") {
            timerBar.style.width = "100%";
            timerBar.style.background = "#f87171";
            timerText.textContent = "TIMEOUT!";
            timerText.style.color = "#f87171";
        } else if (ev.event_type === "DONE" || base >= totalFrames) {
            timerBar.style.width = "0%";
            timerText.textContent = "STOPPED";
            timerText.style.color = "#34d399";
        } else {
            const progress = Math.min(100, Math.round(((ev.tick % gbnSession.timeout_ticks) / gbnSession.timeout_ticks) * 100));
            timerBar.style.width = `${progress}%`;
            timerBar.style.background = "#fbbf24";
            timerText.textContent = `RUNNING (${progress}%)`;
            timerText.style.color = "#fbbf24";
        }
    }

    // 7. Update Receiver Buffer
    updateReceiverBufferDisplay(base, ev);

    // 8. Append to Space-Time Ladder Diagram
    appendLadderEntry(ev);

    // 9. Append to Chronological Event Log
    appendEventLogRow(ev);

    // 10. Update Step Commentary
    updateCommentary(ev);

    // 11. Update Cumulative KPIs & Live Chart Telemetry
    updateKPIsProgressive(stepIdx);
}

/**
 * Update sliding window visual frame cards
 */
function updateSlidingWindowTrackView(base, windowSize, totalFrames, ev) {
    const winLimit = base + windowSize;

    for (let i = 0; i < totalFrames; i++) {
        const box = document.getElementById(`frame-box-${i}`);
        const tag = document.getElementById(`frame-tag-${i}`);
        const attEl = document.getElementById(`frame-att-${i}`);
        if (!box) continue;

        if (i < base) {
            // Acknowledged
            box.style.background = "rgba(16, 185, 129, 0.15)";
            box.style.border = "1.5px solid #10b981";
            box.style.boxShadow = "none";
            if (tag) {
                tag.textContent = "ACKED";
                tag.style.background = "rgba(16, 185, 129, 0.25)";
                tag.style.color = "#34d399";
            }
        } else if (i >= base && i < winLimit) {
            // In Window
            box.style.background = "rgba(0, 242, 254, 0.12)";
            box.style.border = "1.5px solid #00f2fe";
            box.style.boxShadow = "0 0 10px rgba(0,242,254,0.3)";
            if (tag) {
                tag.textContent = "IN-WIN";
                tag.style.background = "rgba(0, 242, 254, 0.25)";
                tag.style.color = "#00f2fe";
            }
        } else {
            // Queued / Waiting
            box.style.background = "rgba(15, 23, 42, 0.75)";
            box.style.border = "1px solid #334155";
            box.style.boxShadow = "none";
            if (tag) {
                tag.textContent = "WAITING";
                tag.style.background = "rgba(100, 116, 139, 0.2)";
                tag.style.color = "#94a3b8";
            }
        }

        // Highlight active event on frame
        if (ev.frame_id === i) {
            if (attEl && ev.attempt) attEl.textContent = `Att: ${ev.attempt}`;
            if (ev.event_type === "LOSS") {
                box.style.background = "rgba(239, 68, 68, 0.25)";
                box.style.border = "2px solid #ef4444";
                if (tag) {
                    tag.textContent = "LOST";
                    tag.style.background = "#ef4444";
                    tag.style.color = "#ffffff";
                }
            } else if (ev.event_type === "SEND") {
                if (ev.attempt > 1) {
                    box.style.background = "rgba(249, 115, 22, 0.25)";
                    box.style.border = "2px solid #f97316";
                    if (tag) {
                        tag.textContent = "RETRY";
                        tag.style.background = "#f97316";
                        tag.style.color = "#ffffff";
                    }
                } else {
                    box.style.background = "rgba(59, 130, 246, 0.25)";
                    box.style.border = "2px solid #3b82f6";
                    if (tag) {
                        tag.textContent = "IN-FLIGHT";
                        tag.style.background = "#3b82f6";
                        tag.style.color = "#ffffff";
                    }
                }
            }
        }
    }
}

/**
 * Animate packets travelling across communication diagram
 */
function animateChannelCommunication(ev) {
    const banner = document.getElementById("channel-banner");
    const animPkt = document.getElementById("anim-packet");
    const animPktBody = document.getElementById("anim-packet-body");
    const animPktText = document.getElementById("anim-packet-text");
    const animAck = document.getElementById("anim-ack");
    const animAckBody = document.getElementById("anim-ack-body");
    const animAckText = document.getElementById("anim-ack-text");
    const rxLastAck = document.getElementById("receiver-last-ack-display");

    if (ev.event_type === "SEND") {
        const isRetry = ev.attempt > 1;
        if (banner) {
            banner.textContent = `CHANNEL: ${isRetry ? 'RETRANSMITTING' : 'TRANSMITTING'} FRAME #${ev.frame_id} (SEQ ${ev.seq_num})`;
            banner.style.background = isRetry ? "rgba(249, 115, 22, 0.2)" : "rgba(59, 130, 246, 0.2)";
            banner.style.color = isRetry ? "#fb923c" : "#60a5fa";
        }
        if (animPkt && animPktBody && animPktText) {
            animPktText.textContent = `${isRetry ? 'RETRY' : 'FRAME'} #${ev.frame_id} (s=${ev.seq_num})`;
            animPktBody.style.background = isRetry ? "#ea580c" : "#2563eb";
            animPkt.style.left = "15%";
            animPkt.style.opacity = "1";
            requestAnimationFrame(() => {
                animPkt.style.left = "80%";
            });
        }
    } else if (ev.event_type === "LOSS") {
        if (banner) {
            banner.textContent = `CHANNEL: NOISE INTERFERENCE — FRAME #${ev.frame_id} (SEQ ${ev.seq_num}) DROPPED!`;
            banner.style.background = "rgba(239, 68, 68, 0.25)";
            banner.style.color = "#f87171";
        }
        if (animPkt && animPktBody && animPktText) {
            animPktText.textContent = `💥 LOST: Frame #${ev.frame_id}`;
            animPktBody.style.background = "#dc2626";
            animPkt.style.left = "15%";
            animPkt.style.opacity = "1";
            requestAnimationFrame(() => {
                animPkt.style.left = "48%";
            });
        }
    } else if (ev.event_type === "ACK") {
        if (banner) {
            banner.textContent = `CHANNEL: RECEIVER TRANSMITTING CUMULATIVE ACK ${ev.seq_num}`;
            banner.style.background = "rgba(16, 185, 129, 0.2)";
            banner.style.color = "#34d399";
        }
        if (rxLastAck) rxLastAck.textContent = `ACK ${ev.seq_num}`;
        if (animAck && animAckBody && animAckText) {
            animAckText.textContent = `ACK ${ev.seq_num}`;
            animAckBody.style.background = "#059669";
            animAck.style.right = "15%";
            animAck.style.opacity = "1";
            requestAnimationFrame(() => {
                animAck.style.right = "80%";
            });
        }
    } else if (ev.event_type === "TIMEOUT") {
        if (banner) {
            banner.textContent = `CHANNEL: SENDER TIMER EXPIRED! GOING BACK TO RETRANSMIT UNACKED WINDOW`;
            banner.style.background = "rgba(245, 158, 11, 0.25)";
            banner.style.color = "#fbbf24";
        }
    } else if (ev.event_type === "DISCARD") {
        if (banner) {
            banner.textContent = `CHANNEL: OUT-OF-ORDER FRAME #${ev.frame_id} DISCARDED AT RECEIVER`;
            banner.style.background = "rgba(239, 68, 68, 0.18)";
            banner.style.color = "#f87171";
        }
    } else if (ev.event_type === "DONE") {
        if (banner) {
            banner.textContent = "CHANNEL: ALL TRANSMISSIONS ACKNOWLEDGED & DELIVERED";
            banner.style.background = "rgba(52, 211, 153, 0.25)";
            banner.style.color = "#34d399";
        }
    }
}

/**
 * Update Receiver In-Order Buffer Display
 */
function updateReceiverBufferDisplay(base, ev) {
    const rxBuffer = document.getElementById("receiver-buffer-list");
    if (!rxBuffer) return;

    if (base === 0 && (!ev.delivered || ev.delivered.length === 0)) {
        rxBuffer.innerHTML = `<span style="color: #64748b; font-size: 0.7rem;">(empty)</span>`;
        return;
    }

    let pills = "";
    for (let i = 0; i < base; i++) {
        pills += `<span class="tag-badge" style="background:#065f46; color:#6ee7b7; font-size:0.7rem; padding:0.1rem 0.35rem; border-radius:3px;">#${i}</span>`;
    }
    rxBuffer.innerHTML = pills || `<span style="color: #64748b; font-size: 0.7rem;">(empty)</span>`;
}

/**
 * Append entry to Space-Time Ladder diagram
 */
function appendLadderEntry(ev) {
    const ladder = document.getElementById("timeline-ladder");
    if (!ladder) return;

    if (ladder.querySelector("div[style*='text-align: center']")) {
        ladder.innerHTML = "";
    }

    const row = document.createElement("div");
    row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 0.35rem 0.6rem; border-radius: 4px; background: rgba(15, 23, 42, 0.6); margin-bottom: 0.25rem; border-left: 3px solid #334155;";

    let arrowHtml = "";
    if (ev.event_type === "SEND") {
        const isRetry = ev.attempt > 1;
        row.style.borderLeftColor = isRetry ? "#f97316" : "#3b82f6";
        arrowHtml = `
            <span style="color: #38bdf8;">SENDER</span>
            <span style="color: ${isRetry ? '#fb923c' : '#60a5fa'}; flex: 1; text-align: center; overflow: hidden; white-space: nowrap; padding: 0 0.5rem;">
                ───[ ${isRetry ? 'RETRY' : 'FRAME'} #${ev.frame_id} (Seq ${ev.seq_num}) ]───&gt;
            </span>
            <span style="color: #94a3b8;">RECEIVER</span>
        `;
    } else if (ev.event_type === "LOSS") {
        row.style.borderLeftColor = "#ef4444";
        arrowHtml = `
            <span style="color: #38bdf8;">SENDER</span>
            <span style="color: #f87171; flex: 1; text-align: center; overflow: hidden; white-space: nowrap; padding: 0 0.5rem;">
                ───[ Frame #${ev.frame_id} (Seq ${ev.seq_num}) ]───✕ [DROPPED IN CHANNEL]
            </span>
            <span style="color: #64748b;">(LOST)</span>
        `;
    } else if (ev.event_type === "ACK") {
        row.style.borderLeftColor = "#10b981";
        arrowHtml = `
            <span style="color: #94a3b8;">SENDER</span>
            <span style="color: #34d399; flex: 1; text-align: center; overflow: hidden; white-space: nowrap; padding: 0 0.5rem;">
                &lt;───[ ACK ${ev.seq_num} (Cumulative) ]───
            </span>
            <span style="color: #34d399;">RECEIVER</span>
        `;
    } else if (ev.event_type === "TIMEOUT") {
        row.style.borderLeftColor = "#f59e0b";
        arrowHtml = `
            <span style="color: #fbbf24; font-weight: 700;">⏱ TIMEOUT EXPIRED at Seq ${ev.seq_num} &mdash; GOING BACK TO RETRANSMIT OUTSTANDING WINDOW</span>
        `;
    } else if (ev.event_type === "DISCARD") {
        row.style.borderLeftColor = "#f87171";
        arrowHtml = `
            <span style="color: #f87171;">RECEIVER DISCARDED out-of-order Frame #${ev.frame_id} (Expected Seq ${ev.expected_seq})</span>
        `;
    } else if (ev.event_type === "DELIVERED") {
        row.style.borderLeftColor = "#34d399";
        arrowHtml = `
            <span style="color: #34d399;">✔ RECEIVER ACCEPTED in-order Frame #${ev.frame_id} (Seq ${ev.seq_num})</span>
        `;
    } else {
        arrowHtml = `<span>${ev.description}</span>`;
    }

    row.innerHTML = `
        <span style="color: #64748b; font-weight: 700; min-width: 65px;">[T+${ev.tick}]</span>
        <div style="flex: 1; display: flex; align-items: center; justify-content: space-between; padding: 0 0.5rem;">
            ${arrowHtml}
        </div>
    `;

    ladder.appendChild(row);
    ladder.parentElement.scrollTop = ladder.parentElement.scrollHeight;
}

/**
 * Append row to chronological event table
 */
function appendEventLogRow(ev) {
    const tbody = document.getElementById("gbn-event-tbody");
    if (!tbody) return;

    const tr = document.createElement("tr");
    tr.className = `gbn-log-row log-type-${ev.event_type}`;
    tr.style.cssText = "border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.2s;";

    let typeColor = "#94a3b8";
    if (ev.event_type === "SEND") typeColor = ev.attempt > 1 ? "#fb923c" : "#60a5fa";
    else if (ev.event_type === "ACK") typeColor = "#34d399";
    else if (ev.event_type === "LOSS") typeColor = "#f87171";
    else if (ev.event_type === "TIMEOUT") typeColor = "#fbbf24";
    else if (ev.event_type === "DELIVERED") typeColor = "#34d399";
    else if (ev.event_type === "DISCARD") typeColor = "#f87171";

    tr.innerHTML = `
        <td style="padding: 0.5rem 0.75rem; color: #64748b;">${ev.tick}</td>
        <td style="padding: 0.5rem 0.75rem; font-weight: 700; color: ${typeColor};">${ev.event_type}</td>
        <td style="padding: 0.5rem 0.75rem; color: #ffffff;">${ev.frame_id !== null ? `#${ev.frame_id} (s=${ev.seq_num})` : '—'}</td>
        <td style="padding: 0.5rem 0.75rem; color: #fbbf24;">${ev.attempt || '—'}</td>
        <td style="padding: 0.5rem 0.75rem; color: #00f2fe;">[${ev.window_state ? ev.window_state.join(", ") : ''}]</td>
        <td style="padding: 0.5rem 0.75rem; color: #cbd5e1;">${ev.description}</td>
    `;

    tbody.appendChild(tr);
    tbody.parentElement.parentElement.scrollTop = tbody.parentElement.parentElement.scrollHeight;
}

/**
 * Filter chronological event log
 */
function filterEventLog(type) {
    const rows = document.querySelectorAll(".gbn-log-row");
    rows.forEach(r => {
        if (type === "all" || r.classList.contains(`log-type-${type}`)) {
            r.style.display = "";
        } else {
            r.style.display = "none";
        }
    });
}

/**
 * Update step commentary banner
 */
function updateCommentary(ev) {
    const text = document.getElementById("commentary-text");
    const tag = document.getElementById("commentary-tag");
    if (!text || !tag) return;

    text.textContent = ev.description;
    tag.textContent = ev.action || ev.event_type;

    if (ev.event_type === "LOSS" || ev.event_type === "DISCARD") {
        tag.style.background = "rgba(239, 68, 68, 0.25)";
        tag.style.color = "#f87171";
    } else if (ev.event_type === "ACK" || ev.event_type === "DELIVERED" || ev.event_type === "DONE") {
        tag.style.background = "rgba(16, 185, 129, 0.25)";
        tag.style.color = "#34d399";
    } else if (ev.event_type === "TIMEOUT") {
        tag.style.background = "rgba(245, 158, 11, 0.25)";
        tag.style.color = "#fbbf24";
    } else {
        tag.style.background = "rgba(0, 242, 254, 0.15)";
        tag.style.color = "#00f2fe";
    }
}

/**
 * Update parameter badges
 */
function updateParameterBadges(base, nextSeq, expectedSeq, windowSize, modulus) {
    const dBase = document.getElementById("disp-base");
    const dNext = document.getElementById("disp-next-seq");
    const dWin = document.getElementById("disp-window-size");
    const dMod = document.getElementById("disp-modulus");

    if (dBase) dBase.textContent = base;
    if (dNext) dNext.textContent = nextSeq;
    if (dWin) dWin.textContent = windowSize;
    if (dMod) dMod.textContent = modulus;
}

/**
 * Update header status and ticks
 */
function updateStatusBadge(text, color) {
    const badgeText = document.getElementById("gbn-status-text");
    const dot = document.querySelector("#gbn-status-badge .status-dot");
    if (badgeText) badgeText.textContent = text;
    if (dot) dot.style.background = color;
}

function updateTickStepDisplay(tick, step, total) {
    const dTick = document.getElementById("disp-tick-num");
    const dStep = document.getElementById("disp-step-num");
    const dTotal = document.getElementById("disp-total-steps");
    if (dTick) dTick.textContent = tick;
    if (dStep) dStep.textContent = step;
    if (dTotal) dTotal.textContent = total;
}

/**
 * Update KPI cards
 */
function updateKPIs(analytics, currentStep) {
    if (!analytics) return;

    const elTrans = document.getElementById("val-total-transmissions");
    const elFrames = document.getElementById("val-total-frames");
    const elDelPct = document.getElementById("val-delivery-pct");
    const elDelFrames = document.getElementById("val-delivered-frames");
    const elLost = document.getElementById("val-lost-frames");
    const elRetries = document.getElementById("val-retransmissions");
    const elEff = document.getElementById("val-channel-efficiency");
    const elDelay = document.getElementById("val-avg-delay");

    if (elTrans) elTrans.textContent = analytics.total_transmissions;
    if (elFrames) elFrames.textContent = analytics.total_frames;
    if (elDelPct) elDelPct.textContent = `${analytics.delivery_pct.toFixed(1)}%`;
    if (elDelFrames) elDelFrames.textContent = analytics.delivered_frames;
    if (elLost) elLost.textContent = analytics.lost_transmissions;
    if (elRetries) elRetries.textContent = analytics.retransmissions;
    if (elEff) elEff.textContent = `${analytics.channel_efficiency_pct.toFixed(1)}%`;
    if (elDelay) elDelay.textContent = analytics.avg_delay_ticks.toFixed(1);
}

/**
 * Update KPIs progressively during stepping
 */
function updateKPIsProgressive(stepIdx) {
    if (!gbnSession || !gbnSession.events) return;
    const events = gbnSession.events.slice(0, stepIdx + 1);

    const totalTrans = events.filter(e => e.event_type === "SEND").length;
    const losses = events.filter(e => e.event_type === "LOSS").length;
    const retries = events.filter(e => e.event_type === "SEND" && e.attempt > 1).length;
    const deliveredCount = events.filter(e => e.event_type === "DELIVERED").length;
    const totalFrames = gbnSession.total_frames;

    const delPct = totalFrames > 0 ? (deliveredCount / totalFrames * 100).toFixed(1) : "0.0";
    const effPct = totalTrans > 0 ? (totalFrames / totalTrans * 100).toFixed(1) : "0.0";

    const elTrans = document.getElementById("val-total-transmissions");
    const elFrames = document.getElementById("val-total-frames");
    const elDelPct = document.getElementById("val-delivery-pct");
    const elDelFrames = document.getElementById("val-delivered-frames");
    const elLost = document.getElementById("val-lost-frames");
    const elRetries = document.getElementById("val-retransmissions");
    const elEff = document.getElementById("val-channel-efficiency");

    if (elTrans) elTrans.textContent = totalTrans;
    if (elFrames) elFrames.textContent = totalFrames;
    if (elDelPct) elDelPct.textContent = `${delPct}%`;
    if (elDelFrames) elDelFrames.textContent = deliveredCount;
    if (elLost) elLost.textContent = losses;
    if (elRetries) elRetries.textContent = retries;
    if (elEff) elEff.textContent = `${effPct}%`;
}

/**
 * Render all 5 Chart.js Performance Charts
 */
function renderAnalyticalCharts(analytics) {
    if (!analytics) return;

    // Destroy existing instances
    if (chartStatusInstance) chartStatusInstance.destroy();
    if (chartAttemptsInstance) chartAttemptsInstance.destroy();
    if (chartAcksInstance) chartAcksInstance.destroy();
    if (chartDelaysInstance) chartDelaysInstance.destroy();
    if (chartEfficiencyInstance) chartEfficiencyInstance.destroy();

    const chartScales = {
        x: { ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(255, 255, 255, 0.05)" } },
        y: { beginAtZero: true, ticks: { color: "#94a3b8", font: { size: 10 } }, grid: { color: "rgba(255, 255, 255, 0.05)" } }
    };

    // 1. Frame Transmission Status (Doughnut)
    const ctx1 = document.getElementById("chart-status");
    if (ctx1) {
        chartStatusInstance = new Chart(ctx1.getContext("2d"), {
            type: "doughnut",
            data: {
                labels: ["Delivered", "Lost in Channel", "Retransmitted"],
                datasets: [{
                    data: [
                        analytics.status_distribution.delivered,
                        analytics.status_distribution.lost,
                        analytics.status_distribution.retransmitted
                    ],
                    backgroundColor: ["#10b981", "#ef4444", "#f97316"],
                    borderColor: "#0b1120",
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "right", labels: { color: "#cbd5e1", font: { size: 10 } } }
                }
            }
        });
    }

    // 2. Transmission Attempts per Frame (Bar)
    const ctx2 = document.getElementById("chart-attempts");
    if (ctx2) {
        const frameLabels = analytics.attempts_per_frame.map((_, i) => `F #${i}`);
        chartAttemptsInstance = new Chart(ctx2.getContext("2d"), {
            type: "bar",
            data: {
                labels: frameLabels,
                datasets: [{
                    label: "Attempts",
                    data: analytics.attempts_per_frame,
                    backgroundColor: analytics.attempts_per_frame.map(att => att > 1 ? "#f97316" : "#3b82f6"),
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: chartScales
            }
        });
    }

    // 3. Cumulative ACK Progression (Line)
    const ctx3 = document.getElementById("chart-acks");
    if (ctx3) {
        chartAcksInstance = new Chart(ctx3.getContext("2d"), {
            type: "line",
            data: {
                labels: analytics.timeline.ticks.map(t => `T+${t}`),
                datasets: [
                    {
                        label: "Cumulative ACKs",
                        data: analytics.timeline.cumulative_acks,
                        borderColor: "#34d399",
                        backgroundColor: "rgba(52, 211, 153, 0.15)",
                        borderWidth: 2,
                        fill: true,
                        tension: 0.2
                    },
                    {
                        label: "Transmissions",
                        data: analytics.timeline.cumulative_transmissions,
                        borderColor: "#38bdf8",
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: "#cbd5e1", font: { size: 10 } } } },
                scales: chartScales
            }
        });
    }

    // 4. Transmission Delay per Frame (Bar)
    const ctx4 = document.getElementById("chart-delays");
    if (ctx4) {
        const frameLabels = analytics.delay_per_frame.map((_, i) => `F #${i}`);
        chartDelaysInstance = new Chart(ctx4.getContext("2d"), {
            type: "bar",
            data: {
                labels: frameLabels,
                datasets: [{
                    label: "Ticks to Delivery",
                    data: analytics.delay_per_frame,
                    backgroundColor: "#fbbf24",
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: chartScales
            }
        });
    }

    // 5. Channel Efficiency Analysis (Comparison Bar)
    const ctx5 = document.getElementById("chart-efficiency");
    if (ctx5) {
        chartEfficiencyInstance = new Chart(ctx5.getContext("2d"), {
            type: "bar",
            data: {
                labels: ["Channel Transmissions Breakdown"],
                datasets: [
                    {
                        label: "Useful Delivered Frames",
                        data: [analytics.delivered_frames],
                        backgroundColor: "#10b981",
                        stack: "Stack 0"
                    },
                    {
                        label: "Retransmission Overhead",
                        data: [analytics.retransmissions],
                        backgroundColor: "#f97316",
                        stack: "Stack 0"
                    },
                    {
                        label: "Lost Packets",
                        data: [analytics.lost_transmissions],
                        backgroundColor: "#ef4444",
                        stack: "Stack 0"
                    }
                ]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: "#cbd5e1", font: { size: 10 } } }
                },
                scales: chartScales
            }
        });
    }
}

/**
 * Playback Controls: Play / Pause / Reset
 */
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
        if (!gbnSession || !gbnSession.events || currentStepIndex >= gbnSession.events.length) {
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

    if (gbnSession && currentStepIndex > 0 && currentStepIndex < gbnSession.events.length) {
        updateStatusBadge("SIMULATION PAUSED", "#fbbf24");
    }
}

async function resetSimulation() {
    pausePlayback();
    try {
        await fetchJson("/api/go-back-n/reset", { method: "POST" });
        await initializeSimulation();
        showToast("Simulation session reset.", "info");
    } catch (err) {
        console.error("Reset error:", err);
    }
}
