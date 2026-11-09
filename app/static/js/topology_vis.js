/**
 * Interactive Network Topology Visualizer using HTML5 Canvas
 * Renders nodes, links, failure states, packet flow particles, and path highlighting.
 */

class NetworkVisualizer {
    constructor(canvasId, onNodeSelect, onLinkToggle) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.onNodeSelect = onNodeSelect;
        this.onLinkToggle = onLinkToggle;

        this.nodes = [];
        this.links = [];
        this.highlightedPath = [];
        this.sourceNode = "SHT1";
        this.targetNode = "ECC";

        this.particles = [];
        this.draggedNode = null;
        this.hoveredNode = null;
        this.hoveredLink = null;

        this.colors = {
            center: "#ef4444",   // Red (ECC)
            service: "#3b82f6",  // Blue (Police, Fire, Ambulance)
            relay: "#a855f7",    // Purple (Disaster Microwave Relays)
            field: "#f59e0b",    // Amber (Search & Rescue Field Teams)
            shelter: "#10b981",  // Emerald (Civilian Emergency Shelters)
            linkNormal: "#334155",
            linkActive: "#00f2fe",
            linkFailed: "#ef4444",
            linkCongested: "#f59e0b"
        };

        this.initCanvasSize();
        this.bindEvents();
        this.startAnimationLoop();
    }

    initCanvasSize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height || 580;
    }

    setData(topologyData) {
        // Adjust coordinates proportionally to fit canvas
        const srcW = 900;
        const srcH = 700;
        const scaleX = (this.canvas.width - 120) / srcW;
        const scaleY = (this.canvas.height - 100) / srcH;

        this.nodes = topologyData.nodes.map(n => ({
            ...n,
            renderX: 60 + n.x * scaleX,
            renderY: 50 + n.y * scaleY,
            radius: n.type === 'center' ? 24 : 18
        }));

        this.links = topologyData.links;
        this.initParticles();
    }

    setPath(pathArray) {
        this.highlightedPath = pathArray || [];
        this.initParticles();
    }

    initParticles() {
        this.particles = [];
        if (!this.highlightedPath || this.highlightedPath.length < 2) return;

        // Generate glowing moving packets along highlighted route
        for (let i = 0; i < 4; i++) {
            this.particles.push({
                segmentIndex: 0,
                progress: i * 0.25,
                speed: 0.012
            });
        }
    }

    bindEvents() {
        window.addEventListener('resize', () => {
            this.initCanvasSize();
        });

        this.canvas.addEventListener('mousedown', (e) => {
            const pos = this.getMousePos(e);
            const clickedNode = this.findNodeAt(pos.x, pos.y);
            if (clickedNode) {
                this.draggedNode = clickedNode;
                if (this.onNodeSelect) this.onNodeSelect(clickedNode);
            }
        });

        this.canvas.addEventListener('mousemove', (e) => {
            const pos = this.getMousePos(e);
            if (this.draggedNode) {
                this.draggedNode.renderX = pos.x;
                this.draggedNode.renderY = pos.y;
            } else {
                this.hoveredNode = this.findNodeAt(pos.x, pos.y);
                this.hoveredLink = this.findLinkAt(pos.x, pos.y);
                this.canvas.style.cursor = (this.hoveredNode || this.hoveredLink) ? 'pointer' : 'default';
            }
        });

        this.canvas.addEventListener('mouseup', () => {
            this.draggedNode = null;
        });

        this.canvas.addEventListener('click', (e) => {
            const pos = this.getMousePos(e);
            const link = this.findLinkAt(pos.x, pos.y);
            if (link && this.onLinkToggle) {
                this.onLinkToggle(link.u, link.v);
            }
        });
    }

    getMousePos(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };
    }

    findNodeAt(x, y) {
        return this.nodes.find(n => {
            const dx = n.renderX - x;
            const dy = n.renderY - y;
            return Math.sqrt(dx * dx + dy * dy) <= n.radius + 6;
        });
    }

    findLinkAt(x, y) {
        const threshold = 8;
        return this.links.find(link => {
            const uNode = this.nodes.find(n => n.id === link.u);
            const vNode = this.nodes.find(n => n.id === link.v);
            if (!uNode || !vNode) return false;

            const dist = this.distToSegment({ x, y }, { x: uNode.renderX, y: uNode.renderY }, { x: vNode.renderX, y: vNode.renderY });
            return dist <= threshold;
        });
    }

    distToSegment(p, v, w) {
        const l2 = (v.x - w.x) * (v.x - w.x) + (v.y - w.y) * (v.y - w.y);
        if (l2 === 0) return Math.hypot(p.x - v.x, p.y - v.y);
        let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(p.x - (v.x + t * (w.x - v.x)), p.y - (v.y + t * (w.y - v.y)));
    }

    isLinkInPath(u, v) {
        if (!this.highlightedPath || this.highlightedPath.length < 2) return false;
        for (let i = 0; i < this.highlightedPath.length - 1; i++) {
            const pU = this.highlightedPath[i];
            const pV = this.highlightedPath[i + 1];
            if ((pU === u && pV === v) || (pU === v && pV === u)) return true;
        }
        return false;
    }

    draw() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw background grid lines
        this.drawGrid();

        // 1. Draw Links
        this.links.forEach(link => {
            const uNode = this.nodes.find(n => n.id === link.u);
            const vNode = this.nodes.find(n => n.id === link.v);
            if (!uNode || !vNode) return;

            const inPath = this.isLinkInPath(link.u, link.v);
            const isHovered = (this.hoveredLink && this.hoveredLink.u === link.u && this.hoveredLink.v === link.v);

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(uNode.renderX, uNode.renderY);
            ctx.lineTo(vNode.renderX, vNode.renderY);

            if (!link.is_active) {
                // Failed / Cut link
                ctx.strokeStyle = "rgba(239, 68, 68, 0.75)";
                ctx.lineWidth = 2.5;
                ctx.setLineDash([6, 6]);
                ctx.stroke();

                // Draw red 'X' in the middle of failed link
                const midX = (uNode.renderX + vNode.renderX) / 2;
                const midY = (uNode.renderY + vNode.renderY) / 2;
                ctx.fillStyle = "#ef4444";
                ctx.font = "bold 14px 'JetBrains Mono'";
                ctx.textAlign = "center";
                ctx.fillText("✖ LINK DOWN", midX, midY - 6);
            } else if (inPath) {
                // Active route path
                ctx.strokeStyle = "#00f2fe";
                ctx.lineWidth = 4.5;
                ctx.shadowColor = "#00f2fe";
                ctx.shadowBlur = 16;
                ctx.stroke();
            } else if (link.is_congested) {
                // Congested link
                ctx.strokeStyle = "#f59e0b";
                ctx.lineWidth = 3;
                ctx.shadowColor = "#f59e0b";
                ctx.shadowBlur = 8;
                ctx.stroke();
            } else {
                // Normal link
                ctx.strokeStyle = isHovered ? "#93c5fd" : "rgba(100, 116, 139, 0.45)";
                ctx.lineWidth = isHovered ? 2.5 : 1.5;
                ctx.stroke();
            }
            ctx.restore();

            // Link metrics badge (cost & delay)
            const midX = (uNode.renderX + vNode.renderX) / 2;
            const midY = (uNode.renderY + vNode.renderY) / 2;
            if (link.is_active) {
                this.drawLinkBadge(midX, midY, `${link.cost}c | ${link.delay_ms}ms`, inPath);
            }
        });

        // 2. Draw Packet Particles along highlighted route
        this.drawParticles();

        // 3. Draw Nodes
        this.nodes.forEach(node => {
            const isSource = (node.id === this.sourceNode);
            const isTarget = (node.id === this.targetNode);
            const inPath = this.highlightedPath.includes(node.id);
            const isHovered = (this.hoveredNode && this.hoveredNode.id === node.id);

            ctx.save();

            // Glowing halo for active path, source, or target
            if (isSource || isTarget || inPath) {
                ctx.beginPath();
                ctx.arc(node.renderX, node.renderY, node.radius + 8, 0, Math.PI * 2);
                ctx.fillStyle = isSource ? "rgba(16, 185, 129, 0.25)" : (isTarget ? "rgba(239, 68, 68, 0.25)" : "rgba(0, 242, 254, 0.18)");
                ctx.fill();
            }

            // Main node circle
            ctx.beginPath();
            ctx.arc(node.renderX, node.renderY, node.radius, 0, Math.PI * 2);
            ctx.fillStyle = this.colors[node.type] || "#3b82f6";
            ctx.fill();

            ctx.lineWidth = isHovered ? 3.5 : 2;
            ctx.strokeStyle = isHovered ? "#ffffff" : "rgba(255, 255, 255, 0.6)";
            ctx.stroke();

            // Node ID
            ctx.fillStyle = "#ffffff";
            ctx.font = `bold ${node.radius > 20 ? 11 : 9}px 'Outfit'`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(node.id, node.renderX, node.renderY);

            // Node descriptive label below
            ctx.font = "10px 'Inter'";
            ctx.fillStyle = inPath ? "#00f2fe" : "#94a3b8";
            ctx.fillText(node.name.split(' ')[0], node.renderX, node.renderY + node.radius + 14);

            // Indicator badges for Source / Destination
            if (isSource) {
                this.drawRoleBadge(node.renderX, node.renderY - node.radius - 10, "SOURCE", "#10b981");
            } else if (isTarget) {
                this.drawRoleBadge(node.renderX, node.renderY - node.radius - 10, "DEST (ECC)", "#ef4444");
            }

            ctx.restore();
        });
    }

    drawGrid() {
        const ctx = this.ctx;
        ctx.save();
        ctx.strokeStyle = "rgba(255, 255, 255, 0.02)";
        ctx.lineWidth = 1;
        const step = 40;
        for (let x = 0; x < this.canvas.width; x += step) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.canvas.height); ctx.stroke();
        }
        for (let y = 0; y < this.canvas.height; y += step) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.canvas.width, y); ctx.stroke();
        }
        ctx.restore();
    }

    drawLinkBadge(x, y, text, inPath) {
        const ctx = this.ctx;
        ctx.save();
        ctx.font = "9px 'JetBrains Mono'";
        const textWidth = ctx.measureText(text).width;
        const padX = 5;
        const padY = 2;

        ctx.fillStyle = inPath ? "rgba(0, 242, 254, 0.15)" : "rgba(10, 16, 30, 0.85)";
        ctx.strokeStyle = inPath ? "rgba(0, 242, 254, 0.6)" : "rgba(255, 255, 255, 0.1)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(x - textWidth / 2 - padX, y - 7 - padY, textWidth + padX * 2, 14 + padY, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = inPath ? "#00f2fe" : "#94a3b8";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, x, y);
        ctx.restore();
    }

    drawRoleBadge(x, y, text, color) {
        const ctx = this.ctx;
        ctx.save();
        ctx.font = "bold 9px 'Outfit'";
        const textWidth = ctx.measureText(text).width;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.roundRect(x - textWidth / 2 - 5, y - 8, textWidth + 10, 14, 4);
        ctx.fill();

        ctx.fillStyle = "#050811";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(text, x, y);
        ctx.restore();
    }

    drawParticles() {
        if (!this.highlightedPath || this.highlightedPath.length < 2) return;

        const ctx = this.ctx;
        this.particles.forEach(p => {
            p.progress += p.speed;
            if (p.progress >= 1.0) {
                p.progress = 0;
                p.segmentIndex = (p.segmentIndex + 1) % (this.highlightedPath.length - 1);
            }

            const uId = this.highlightedPath[p.segmentIndex];
            const vId = this.highlightedPath[p.segmentIndex + 1];
            const u = this.nodes.find(n => n.id === uId);
            const v = this.nodes.find(n => n.id === vId);
            if (!u || !v) return;

            const px = u.renderX + (v.renderX - u.renderX) * p.progress;
            const py = u.renderY + (v.renderY - u.renderY) * p.progress;

            ctx.save();
            ctx.beginPath();
            ctx.arc(px, py, 4.5, 0, Math.PI * 2);
            ctx.fillStyle = "#ffffff";
            ctx.shadowColor = "#00f2fe";
            ctx.shadowBlur = 12;
            ctx.fill();
            ctx.restore();
        });
    }

    startAnimationLoop() {
        const animate = () => {
            this.draw();
            requestAnimationFrame(animate);
        };
        requestAnimationFrame(animate);
    }
}

window.NetworkVisualizer = NetworkVisualizer;
