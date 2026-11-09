/**
 * Lightweight Pure HTML5 Canvas Multi-Line & Bar Chart Engine.
 * Zero external CDN dependencies - 100% offline capable.
 */

class SimpleCanvasChart {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.title = options.title || "";
        this.xLabel = options.xLabel || "X";
        this.yLabel = options.yLabel || "Y";
        this.datasets = []; // [{ label, color, data: [{x, y}] }]
        this.initCanvasSize();
        window.addEventListener('resize', () => {
            this.initCanvasSize();
            this.render();
        });
    }

    initCanvasSize() {
        if (!this.canvas) return;
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height || 320;
    }

    setData(datasets) {
        this.datasets = datasets;
        this.render();
    }

    render() {
        if (!this.canvas || !this.ctx) return;
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;

        ctx.clearRect(0, 0, w, h);

        const padLeft = 60;
        const padRight = 30;
        const padTop = 40;
        const padBottom = 45;

        const plotW = w - padLeft - padRight;
        const plotH = h - padTop - padBottom;

        if (this.datasets.length === 0 || !this.datasets[0].data || this.datasets[0].data.length === 0) {
            ctx.fillStyle = "#64748b";
            ctx.font = "14px 'Inter'";
            ctx.textAlign = "center";
            ctx.fillText("No simulation data available", w / 2, h / 2);
            return;
        }

        // Calculate min & max
        let minY = 0;
        let maxY = 0;
        let allX = this.datasets[0].data.map(p => p.x);

        this.datasets.forEach(ds => {
            ds.data.forEach(p => {
                if (p.y > maxY) maxY = p.y;
            });
        });
        maxY = maxY === 0 ? 10 : maxY * 1.15; // 15% headroom

        // Draw Axes & Grid
        ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
        ctx.lineWidth = 1;
        ctx.fillStyle = "#94a3b8";
        ctx.font = "10px 'JetBrains Mono'";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";

        const yTicks = 5;
        for (let i = 0; i <= yTicks; i++) {
            const val = minY + (maxY - minY) * (i / yTicks);
            const yPos = padTop + plotH - (i / yTicks) * plotH;

            // Gridline
            ctx.beginPath();
            ctx.moveTo(padLeft, yPos);
            ctx.lineTo(padLeft + plotW, yPos);
            ctx.stroke();

            ctx.fillText(val.toFixed(1), padLeft - 8, yPos);
        }

        // X Axis labels
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        const xCount = allX.length;
        const xStep = plotW / Math.max(1, xCount - 1);

        allX.forEach((xVal, idx) => {
            const xPos = padLeft + idx * xStep;
            ctx.fillText(xVal, xPos, padTop + plotH + 8);
        });

        // Axis Titles
        ctx.fillStyle = "#cbd5e1";
        ctx.font = "bold 11px 'Outfit'";
        ctx.textAlign = "center";
        ctx.fillText(this.xLabel, padLeft + plotW / 2, h - 14);

        // Datasets Lines
        this.datasets.forEach(ds => {
            ctx.save();
            ctx.strokeStyle = ds.color || "#00f2fe";
            ctx.lineWidth = 2.5;
            ctx.fillStyle = ds.color || "#00f2fe";

            ctx.beginPath();
            ds.data.forEach((pt, idx) => {
                const xPos = padLeft + idx * xStep;
                const yPos = padTop + plotH - ((pt.y - minY) / (maxY - minY)) * plotH;
                if (idx === 0) ctx.moveTo(xPos, yPos);
                else ctx.lineTo(xPos, yPos);
            });
            ctx.stroke();

            // Draw points
            ds.data.forEach((pt, idx) => {
                const xPos = padLeft + idx * xStep;
                const yPos = padTop + plotH - ((pt.y - minY) / (maxY - minY)) * plotH;
                ctx.beginPath();
                ctx.arc(xPos, yPos, 4, 0, Math.PI * 2);
                ctx.fill();
            });
            ctx.restore();
        });

        // Legend at top
        ctx.save();
        let legX = padLeft + 10;
        ctx.font = "11px 'Inter'";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";

        this.datasets.forEach(ds => {
            ctx.fillStyle = ds.color;
            ctx.fillRect(legX, 15, 12, 12);
            ctx.fillStyle = "#f1f5f9";
            ctx.fillText(ds.label, legX + 18, 21);
            legX += ctx.measureText(ds.label).width + 40;
        });
        ctx.restore();
    }
}

window.SimpleCanvasChart = SimpleCanvasChart;
