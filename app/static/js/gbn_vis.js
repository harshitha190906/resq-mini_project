/**
 * Interactive Go-Back-N ARQ Protocol Visualizer
 * Animates sliding window frames, cumulative ACKs, timer timeouts, and retransmissions.
 */

class GBNVisualizer {
    constructor(containerId, logContainerId) {
        this.container = document.getElementById(containerId);
        this.logContainer = document.getElementById(logContainerId);
        this.simulationData = null;
        this.currentStep = 0;
        this.timer = null;
        this.playbackSpeed = 800; // ms per step
    }

    loadSimulation(data) {
        this.stop();
        this.simulationData = data;
        this.currentStep = 0;
        this.renderInitialFrames();
        this.updateStepView();
    }

    renderInitialFrames() {
        if (!this.container || !this.simulationData) return;
        this.container.innerHTML = '';

        for (let i = 0; i < this.simulationData.total_frames; i++) {
            const frameBox = document.createElement('div');
            frameBox.className = 'frame-box';
            frameBox.id = `gbn-frame-${i}`;
            frameBox.innerHTML = `
                <div class="seq-title">FRAME</div>
                <div class="seq-num">#${i}</div>
                <div class="frame-tag" id="tag-${i}" style="font-size: 0.65rem; color: #64748b;">READY</div>
            `;
            this.container.appendChild(frameBox);
        }
    }

    updateStepView() {
        if (!this.simulationData || !this.simulationData.events) return;
        const events = this.simulationData.events;
        if (this.currentStep >= events.length) {
            this.stop();
            return;
        }

        const ev = events[this.currentStep];

        // Highlight window frames
        const base = ev.window.base;
        const winSize = ev.window.size;
        const winLimit = base + winSize;

        for (let i = 0; i < this.simulationData.total_frames; i++) {
            const el = document.getElementById(`gbn-frame-${i}`);
            const tag = document.getElementById(`tag-${i}`);
            if (!el) continue;

            el.className = 'frame-box';

            if (i < base) {
                el.classList.add('acked');
                tag.textContent = "ACKED";
                tag.style.color = "#34d399";
            } else if (i >= base && i < winLimit) {
                el.classList.add('in-window');
                tag.textContent = "IN-WIN";
                tag.style.color = "#00f2fe";
            } else {
                tag.textContent = "QUEUED";
                tag.style.color = "#64748b";
            }

            // Check if this frame was dropped in this tick
            if (ev.seq === i) {
                if (ev.type.includes('LOST') || ev.type.includes('DROP')) {
                    el.classList.add('lost');
                    tag.textContent = "DROPPED";
                    tag.style.color = "#ef4444";
                } else if (ev.type === 'SEND') {
                    el.classList.add('sent');
                    tag.textContent = "IN-FLIGHT";
                    tag.style.color = "#60a5fa";
                }
            }
        }

        // Add event to log
        this.appendLog(ev);

        // Update step counter UI
        const stepDisplay = document.getElementById('gbnStepCounter');
        if (stepDisplay) {
            stepDisplay.textContent = `Tick: ${ev.tick} | Event: ${this.currentStep + 1} / ${events.length}`;
        }
    }

    appendLog(ev) {
        if (!this.logContainer) return;

        let tagClass = "tag-info";
        if (ev.type.includes('LOST') || ev.type.includes('DROP') || ev.type === 'TIMEOUT') tagClass = "tag-error";
        else if (ev.type.includes('ACCEPT') || ev.type.includes('RECV')) tagClass = "tag-success";
        else if (ev.type.includes('CORRUPT')) tagClass = "tag-warn";

        const row = document.createElement('div');
        row.className = 'log-entry';
        row.innerHTML = `
            <span style="color: #64748b;">[T+${ev.tick}]</span>
            <span class="log-tag ${tagClass}">${ev.actor}</span>
            <span>${ev.message}</span>
        `;
        this.logContainer.prepend(row);
    }

    stepForward() {
        if (!this.simulationData || this.currentStep >= this.simulationData.events.length - 1) return;
        this.currentStep++;
        this.updateStepView();
    }

    stepBackward() {
        if (this.currentStep > 0) {
            this.currentStep--;
            this.updateStepView();
        }
    }

    play() {
        if (this.timer) return;
        this.timer = setInterval(() => {
            if (this.currentStep < this.simulationData.events.length - 1) {
                this.stepForward();
            } else {
                this.stop();
            }
        }, this.playbackSpeed);
    }

    stop() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }

    reset() {
        this.stop();
        this.currentStep = 0;
        if (this.logContainer) this.logContainer.innerHTML = '';
        this.renderInitialFrames();
        this.updateStepView();
    }
}

window.GBNVisualizer = GBNVisualizer;
