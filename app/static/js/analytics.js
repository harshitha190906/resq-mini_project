/**
 * ResQNet – app/static/js/analytics.js
 * ======================================
 * Network Performance Analytics controller.
 * Fetches data from /api/analytics/overview and /api/analytics/performance,
 * populates 8 KPI cards, renders 6 Chart.js charts, and fills the comparison table.
 */

'use strict';

/* ------------------------------------------------------------------ */
/* Globals                                                              */
/* ------------------------------------------------------------------ */
const _analyticsCharts = {};

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function _destroyChart(id) {
    if (_analyticsCharts[id]) {
        _analyticsCharts[id].destroy();
        delete _analyticsCharts[id];
    }
}

function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function _chartDefaults() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600 },
        plugins: {
            legend: {
                labels: { color: '#94a3b8', font: { size: 10, family: "'JetBrains Mono', monospace" } }
            },
            tooltip: {
                backgroundColor: '#0f172a',
                borderColor: '#405d94',
                borderWidth: 1,
                titleColor: '#00f2fe',
                bodyColor: '#cbd5e1'
            }
        },
        scales: {
            x: {
                ticks: { color: '#94a3b8', font: { size: 9 } },
                grid: { color: 'rgba(64,93,148,0.2)' }
            },
            y: {
                ticks: { color: '#94a3b8', font: { size: 9 } },
                grid: { color: 'rgba(64,93,148,0.2)' },
                beginAtZero: true
            }
        }
    };
}

function _makeLineDataset(label, data, color, dashed) {
    return {
        label,
        data,
        borderColor: color,
        backgroundColor: color + '20',
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        tension: 0.35,
        fill: false,
        borderDash: dashed ? [5, 3] : []
    };
}

/* ------------------------------------------------------------------ */
/* KPI Cards                                                            */
/* ------------------------------------------------------------------ */
function _populateKPICards(overview) {
    _setText('kpi-sent',       overview.total_sent   ?? 0);
    _setText('kpi-delivered',  overview.delivered    ?? 0);
    _setText('kpi-lost',       overview.lost         ?? 0);
    _setText('kpi-del-ratio',  (overview.delivery_ratio_pct  ?? 0).toFixed(1) + '%');
    _setText('kpi-loss-ratio', (overview.loss_ratio_pct      ?? 0).toFixed(1) + '%');
    _setText('kpi-delay',      (overview.avg_delay_ms        ?? 0).toFixed(1));
    _setText('kpi-throughput', (overview.throughput_kbps     ?? 0).toFixed(1));
    _setText('kpi-efficiency', (overview.network_efficiency_pct ?? 0).toFixed(1) + '%');
}

/* ------------------------------------------------------------------ */
/* Chart 1 – Packet Delivery vs Simulation Time                        */
/* ------------------------------------------------------------------ */
function _renderChartDeliveryTime(timeSeries) {
    const ctx = document.getElementById('chartDeliveryTime');
    if (!ctx) return;
    _destroyChart('chartDeliveryTime');

    const delivery = timeSeries?.delivery_cumulative;
    const noData = !delivery || delivery.length === 0;

    const labels = noData ? ['No data'] : delivery.map((_, i) => `t${i + 1}`);
    const values = noData ? [0] : delivery;

    const config = _chartDefaults();
    config.plugins.title = {
        display: noData,
        text: 'Run a simulation to generate performance data',
        color: '#94a3b8',
        font: { size: 11 }
    };

    _analyticsCharts['chartDeliveryTime'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [_makeLineDataset('Delivered Packets (cumulative)', values, '#34d399', false)]
        },
        options: config
    });
}

/* ------------------------------------------------------------------ */
/* Chart 2 – Packet Loss vs Simulation Time                            */
/* ------------------------------------------------------------------ */
function _renderChartLossTime(timeSeries) {
    const ctx = document.getElementById('chartLossTime');
    if (!ctx) return;
    _destroyChart('chartLossTime');

    const loss = timeSeries?.loss_cumulative;
    const noData = !loss || loss.length === 0;

    const labels = noData ? ['No data'] : loss.map((_, i) => `t${i + 1}`);
    const values = noData ? [0] : loss;

    const config = _chartDefaults();
    config.plugins.title = {
        display: noData,
        text: 'Run a simulation to generate performance data',
        color: '#94a3b8',
        font: { size: 11 }
    };

    _analyticsCharts['chartLossTime'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [_makeLineDataset('Lost Packets (cumulative)', values, '#f87171', false)]
        },
        options: config
    });
}

/* ------------------------------------------------------------------ */
/* Chart 3 – Average Delay vs Traffic Load                             */
/* ------------------------------------------------------------------ */
function _renderChartDelayLoad(perf) {
    const ctx = document.getElementById('chartDelayLoad');
    if (!ctx) return;
    _destroyChart('chartDelayLoad');

    const loads  = perf?.loads  || [10, 20, 40, 60, 80, 100];
    const curves = perf?.curves || {};
    const labels = loads.map(l => `${l} pkt/s`);

    _analyticsCharts['chartDelayLoad'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                _makeLineDataset('Uncontrolled Delay (ms)',    curves.unc_delay  || [], '#f87171', false),
                _makeLineDataset('Leaky Bucket Delay (ms)',    curves.ctrl_delay || [], '#34d399', true)
            ]
        },
        options: {
            ..._chartDefaults(),
            scales: {
                ..._chartDefaults().scales,
                y: { ..._chartDefaults().scales.y, title: { display: true, text: 'Delay (ms)', color: '#94a3b8' } },
                x: { ..._chartDefaults().scales.x, title: { display: true, text: 'Traffic Load', color: '#94a3b8' } }
            }
        }
    });
}

/* ------------------------------------------------------------------ */
/* Chart 4 – Throughput vs Traffic Load                                */
/* ------------------------------------------------------------------ */
function _renderChartThroughputLoad(perf) {
    const ctx = document.getElementById('chartThroughputLoad');
    if (!ctx) return;
    _destroyChart('chartThroughputLoad');

    const loads  = perf?.loads  || [10, 20, 40, 60, 80, 100];
    const curves = perf?.curves || {};
    const labels = loads.map(l => `${l} pkt/s`);

    _analyticsCharts['chartThroughputLoad'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                _makeLineDataset('Uncontrolled Throughput (kbps)',    curves.unc_throughput  || [], '#00f2fe', false),
                _makeLineDataset('Leaky Bucket Throughput (kbps)',    curves.ctrl_throughput || [], '#38bdf8', true)
            ]
        },
        options: {
            ..._chartDefaults(),
            scales: {
                ..._chartDefaults().scales,
                y: { ..._chartDefaults().scales.y, title: { display: true, text: 'Throughput (kbps)', color: '#94a3b8' } },
                x: { ..._chartDefaults().scales.x, title: { display: true, text: 'Traffic Load', color: '#94a3b8' } }
            }
        }
    });
}

/* ------------------------------------------------------------------ */
/* Chart 5 – Raw Traffic vs Shaped Traffic (Loss Ratio)               */
/* ------------------------------------------------------------------ */
function _renderChartShapedTraffic(perf) {
    const ctx = document.getElementById('chartShapedTraffic');
    if (!ctx) return;
    _destroyChart('chartShapedTraffic');

    const loads  = perf?.loads  || [10, 20, 40, 60, 80, 100];
    const curves = perf?.curves || {};
    const labels = loads.map(l => `${l} pkt/s`);

    _analyticsCharts['chartShapedTraffic'] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Uncontrolled Loss (%)',
                    data: curves.unc_loss || [],
                    backgroundColor: 'rgba(248,113,113,0.6)',
                    borderColor: '#f87171',
                    borderWidth: 1
                },
                {
                    label: 'Leaky Bucket Loss (%)',
                    data: curves.ctrl_loss || [],
                    backgroundColor: 'rgba(52,211,153,0.6)',
                    borderColor: '#34d399',
                    borderWidth: 1
                }
            ]
        },
        options: {
            ..._chartDefaults(),
            scales: {
                ..._chartDefaults().scales,
                y: { ..._chartDefaults().scales.y, title: { display: true, text: 'Loss (%)', color: '#94a3b8' } },
                x: { ..._chartDefaults().scales.x, title: { display: true, text: 'Traffic Load', color: '#94a3b8' } }
            }
        }
    });
}

/* ------------------------------------------------------------------ */
/* Chart 6 – Retransmission & Overhead                                 */
/* ------------------------------------------------------------------ */
function _renderChartRetransmissions(perf) {
    const ctx = document.getElementById('chartRetransmissions');
    if (!ctx) return;
    _destroyChart('chartRetransmissions');

    const loads  = perf?.loads  || [10, 20, 40, 60, 80, 100];
    const table  = perf?.table  || [];
    const labels = loads.map(l => `${l} pkt/s`);

    // Build retransmission arrays from table rows
    const uncRetrans  = table.map(r => r.uncontrolled?.retransmissions ?? 0);
    const ctrlRetrans = table.map(r => r.controlled?.retransmissions   ?? 0);

    _analyticsCharts['chartRetransmissions'] = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                _makeLineDataset('Uncontrolled Retransmissions',    uncRetrans,  '#fb923c', false),
                _makeLineDataset('Leaky Bucket Retransmissions',    ctrlRetrans, '#fbbf24', true)
            ]
        },
        options: {
            ..._chartDefaults(),
            scales: {
                ..._chartDefaults().scales,
                y: { ..._chartDefaults().scales.y, title: { display: true, text: 'Retransmissions', color: '#94a3b8' } },
                x: { ..._chartDefaults().scales.x, title: { display: true, text: 'Traffic Load', color: '#94a3b8' } }
            }
        }
    });
}

/* ------------------------------------------------------------------ */
/* Comparison Table                                                     */
/* ------------------------------------------------------------------ */
function _populateComparisonTable(table) {
    const tbody = document.getElementById('comparison-table-tbody');
    if (!tbody) return;
    if (!table || table.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#94a3b8;padding:1rem;">No comparison data available.</td></tr>';
        return;
    }

    tbody.innerHTML = table.map(row => {
        const u = row.uncontrolled || {};
        const c = row.controlled   || {};
        const rowStyle = 'border-bottom: 1px solid rgba(64,93,148,0.2);';
        const unc = `color:#f87171`;
        const ctrl = `color:#34d399`;

        return `<tr style="${rowStyle}">
            <td style="padding:0.5rem 0.75rem;font-weight:600;color:#00f2fe;">${row.load_pps}</td>
            <td style="padding:0.5rem 0.75rem;${unc}">${(u.delivery_ratio_pct ?? 0).toFixed(1)}%</td>
            <td style="padding:0.5rem 0.75rem;${unc}">${(u.loss_ratio_pct ?? 0).toFixed(1)}%</td>
            <td style="padding:0.5rem 0.75rem;">${(u.avg_delay_ms ?? 0).toFixed(1)} ms</td>
            <td style="padding:0.5rem 0.75rem;">${(u.throughput_kbps ?? 0).toFixed(1)} kbps</td>
            <td style="padding:0.5rem 0.75rem;${ctrl}">${(c.delivery_ratio_pct ?? 0).toFixed(1)}%</td>
            <td style="padding:0.5rem 0.75rem;${ctrl}">${(c.loss_ratio_pct ?? 0).toFixed(1)}%</td>
            <td style="padding:0.5rem 0.75rem;">${(c.avg_delay_ms ?? 0).toFixed(1)} ms</td>
            <td style="padding:0.5rem 0.75rem;color:#00f2fe;">${(c.throughput_kbps ?? 0).toFixed(1)} kbps</td>
        </tr>`;
    }).join('');
}

/* ------------------------------------------------------------------ */
/* Main Load Function                                                   */
/* ------------------------------------------------------------------ */
async function loadAnalyticsData() {
    try {
        // Fetch both endpoints in parallel
        const [overview, perf] = await Promise.all([
            fetchJson('/api/analytics/overview'),
            fetchJson('/api/analytics/performance')
        ]);

        // Populate KPI cards
        _populateKPICards(overview);

        // Render charts 1 & 2 from time-series data
        const ts = overview?.time_series || {};
        _renderChartDeliveryTime(ts);
        _renderChartLossTime(ts);

        // Render charts 3-6 from load comparison data
        _renderChartDelayLoad(perf);
        _renderChartThroughputLoad(perf);
        _renderChartShapedTraffic(perf);
        _renderChartRetransmissions(perf);

        // Populate comparison table
        _populateComparisonTable(perf?.table || []);

        if (typeof showToast === 'function') {
            showToast('Analytics data refreshed', 'success');
        }
    } catch (err) {
        console.error('[Analytics] Failed to load analytics data:', err);
        if (typeof showToast === 'function') {
            showToast('Failed to load analytics: ' + (err.message || 'Network error'), 'error');
        }
    }
}

/* ------------------------------------------------------------------ */
/* Bootstrap                                                            */
/* ------------------------------------------------------------------ */
document.addEventListener('DOMContentLoaded', () => {
    // Load data on page open
    loadAnalyticsData();

    // Refresh button
    const btn = document.getElementById('btn-refresh-analytics');
    if (btn) {
        btn.addEventListener('click', () => {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Refreshing...';
            loadAnalyticsData().finally(() => {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Telemetry';
            });
        });
    }
});

