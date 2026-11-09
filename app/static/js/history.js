/**
 * ResQNet – app/static/js/history.js
 * =====================================
 * Simulation History controller.
 * Fetches /api/history with filters, renders table, detail modal,
 * delete/clear actions, and CSV export.
 */

'use strict';

/* ------------------------------------------------------------------ */
/* State                                                                */
/* ------------------------------------------------------------------ */
let _historyFilters = {
    query:     '',
    algorithm: '',
    status:    '',
    sort:      'newest'
};

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = (value !== undefined && value !== null) ? value : '–';
}

function _statusBadge(status) {
    const map = {
        'SUCCESS':              { bg: 'rgba(52,211,153,0.15)', color: '#34d399', icon: 'fa-check-circle' },
        'COMPLETED_WITH_LOSS':  { bg: 'rgba(251,191,36,0.15)',  color: '#fbbf24', icon: 'fa-exclamation-circle' },
        'FAILED':               { bg: 'rgba(248,113,113,0.15)', color: '#f87171', icon: 'fa-times-circle' }
    };
    const s = map[status] || { bg: 'rgba(148,163,184,0.15)', color: '#94a3b8', icon: 'fa-question-circle' };
    const label = status === 'COMPLETED_WITH_LOSS' ? 'PARTIAL LOSS' : (status || 'UNKNOWN');
    return `<span style="background:${s.bg};color:${s.color};border:1px solid ${s.color}40;border-radius:12px;padding:0.2rem 0.6rem;font-size:0.7rem;white-space:nowrap;display:inline-flex;align-items:center;gap:0.3rem;">
        <i class="fas ${s.icon}" style="font-size:0.65rem;"></i>${label}
    </span>`;
}

function _fmt(val, decimals) {
    if (val === undefined || val === null) return '–';
    const n = parseFloat(val);
    if (isNaN(n)) return String(val);
    return decimals !== undefined ? n.toFixed(decimals) : String(n);
}

/* ------------------------------------------------------------------ */
/* Summary KPI Cards                                                    */
/* ------------------------------------------------------------------ */
function _populateSummary(summary) {
    if (!summary) return;
    _setText('hist-total',      summary.total_simulations      ?? '–');
    _setText('hist-success',    summary.successful_simulations ?? '–');
    _setText('hist-failed',     summary.failed_simulations     ?? '–');
    _setText('hist-total-pkts', summary.total_packets          ?? '–');
    _setText('hist-avg-pdr',    _fmt(summary.avg_delivery_ratio,   1));
    _setText('hist-avg-tput',   _fmt(summary.avg_throughput_kbps,  1));
}

/* ------------------------------------------------------------------ */
/* Table Rendering                                                      */
/* ------------------------------------------------------------------ */
function _renderTable(simulations) {
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;

    const count = document.getElementById('hist-record-count');
    if (count) {
        count.textContent = `${simulations.length} record${simulations.length !== 1 ? 's' : ''}`;
    }

    if (!simulations || simulations.length === 0) {
        tbody.innerHTML = `<tr>
            <td colspan="11" style="text-align:center;padding:2.5rem;color:#94a3b8;">
                <i class="fas fa-inbox" style="font-size:1.5rem;display:block;margin-bottom:0.5rem;opacity:0.4;"></i>
                No simulation history found. Run a simulation to generate records.
            </td>
        </tr>`;
        return;
    }

    const rowStyle = 'border-bottom:1px solid rgba(64,93,148,0.15);transition:background 0.15s;';

    tbody.innerHTML = simulations.map(sim => {
        const ts = sim.timestamp ? sim.timestamp.replace('T', ' ').substring(0, 19) : '–';
        const pdr = _fmt(sim.delivery_ratio, 1);
        const delay = _fmt(sim.avg_delay_ms, 1);
        const tput = _fmt(sim.throughput_kbps, 1);

        return `<tr style="${rowStyle}" onmouseover="this.style.background='rgba(64,93,148,0.08)'" onmouseout="this.style.background=''">
            <td style="padding:0.5rem 0.75rem;color:#00f2fe;white-space:nowrap;" title="${sim.id}">${sim.id.length > 24 ? sim.id.substring(0, 24) + '…' : sim.id}</td>
            <td style="padding:0.5rem 0.75rem;white-space:nowrap;color:#94a3b8;">${ts}</td>
            <td style="padding:0.5rem 0.75rem;">${sim.algorithm || '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;">${sim.packets_sent ?? '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;color:#34d399;">${sim.packets_delivered ?? '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;color:#f87171;">${sim.packets_lost ?? '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;">${pdr !== '–' ? pdr + '%' : '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;">${delay !== '–' ? delay + ' ms' : '–'}</td>
            <td style="padding:0.5rem 0.75rem;text-align:right;color:#38bdf8;">${tput !== '–' ? tput + ' kbps' : '–'}</td>
            <td style="padding:0.5rem 0.75rem;">${_statusBadge(sim.status)}</td>
            <td style="padding:0.5rem 0.75rem;text-align:center;white-space:nowrap;">
                <button class="btn btn-secondary" data-action="view" data-id="${encodeURIComponent(sim.id)}"
                    style="font-size:0.72rem;padding:0.25rem 0.55rem;margin-right:0.3rem;" title="View Details">
                    <i class="fas fa-eye"></i>
                </button>
                <button class="btn" data-action="delete" data-id="${encodeURIComponent(sim.id)}"
                    style="font-size:0.72rem;padding:0.25rem 0.55rem;background:rgba(248,113,113,0.12);color:#f87171;border:1px solid rgba(248,113,113,0.3);" title="Delete">
                    <i class="fas fa-trash-alt"></i>
                </button>
            </td>
        </tr>`;
    }).join('');

    // Wire row action buttons
    tbody.querySelectorAll('button[data-action="view"]').forEach(btn => {
        btn.addEventListener('click', () => _openDetailModal(decodeURIComponent(btn.dataset.id)));
    });
    tbody.querySelectorAll('button[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', () => _deleteRecord(decodeURIComponent(btn.dataset.id)));
    });
}

/* ------------------------------------------------------------------ */
/* Load History Data                                                    */
/* ------------------------------------------------------------------ */
async function loadHistoryData() {
    // Build query params from current filters
    const params = {};
    if (_historyFilters.query)     params.query     = _historyFilters.query;
    if (_historyFilters.algorithm) params.algorithm = _historyFilters.algorithm;
    if (_historyFilters.status)    params.status    = _historyFilters.status;
    if (_historyFilters.sort)      params.sort      = _historyFilters.sort;

    try {
        const response = await ResQNetAPI.getHistory(params);
        _populateSummary(response.summary);
        _renderTable(response.simulations || []);
    } catch (err) {
        console.error('[History] Load error:', err);
        const tbody = document.getElementById('history-table-body');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:2rem;color:#f87171;">
                <i class="fas fa-exclamation-triangle"></i> Failed to load history: ${err.message || 'Network error'}
            </td></tr>`;
        }
        if (typeof showToast === 'function') {
            showToast('Failed to load history: ' + (err.message || 'Network error'), 'error');
        }
    }
}

/* ------------------------------------------------------------------ */
/* Detail Modal                                                         */
/* ------------------------------------------------------------------ */
async function _openDetailModal(id) {
    const modal = document.getElementById('hist-detail-modal');
    const body  = document.getElementById('hist-detail-body');
    if (!modal || !body) return;

    body.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:1rem;"><i class="fas fa-spinner fa-spin"></i> Loading…</p>';
    modal.style.display = 'block';

    try {
        const sim = await ResQNetAPI.getHistoryDetail(id);
        const ts = sim.timestamp ? sim.timestamp.replace('T', ' ').substring(0, 19) : '–';

        const _row = (label, value, color) =>
            `<div style="display:flex;justify-content:space-between;padding:0.35rem 0;border-bottom:1px solid rgba(64,93,148,0.15);">
                <span style="color:#94a3b8;font-size:0.8rem;">${label}</span>
                <span style="color:${color || '#e2e8f0'};font-family:'JetBrains Mono',monospace;font-size:0.82rem;">${value ?? '–'}</span>
            </div>`;

        const params = sim.parameters ? JSON.stringify(sim.parameters, null, 2) : '(none)';
        const details = sim.details   ? JSON.stringify(sim.details,    null, 2) : '(none)';

        body.innerHTML = `
            <div style="margin-bottom:1rem;">
                <div style="font-size:0.72rem;text-transform:uppercase;color:#94a3b8;margin-bottom:0.5rem;letter-spacing:0.05em;">Simulation Info</div>
                ${_row('Simulation ID',   sim.id,         '#00f2fe')}
                ${_row('Algorithm',       sim.algorithm,  '#ffffff')}
                ${_row('Date &amp; Time', ts,             '#94a3b8')}
                ${_row('Status',          sim.status,     sim.status === 'SUCCESS' ? '#34d399' : sim.status === 'FAILED' ? '#f87171' : '#fbbf24')}
            </div>
            <div style="margin-bottom:1rem;">
                <div style="font-size:0.72rem;text-transform:uppercase;color:#94a3b8;margin-bottom:0.5rem;letter-spacing:0.05em;">Packet Statistics</div>
                ${_row('Packets Sent',       sim.packets_sent,          '#ffffff')}
                ${_row('Packets Delivered',  sim.packets_delivered,     '#34d399')}
                ${_row('Packets Lost',       sim.packets_lost,          '#f87171')}
                ${_row('Delivery Ratio',     _fmt(sim.delivery_ratio, 1) + '%', '#34d399')}
                ${_row('Avg Delay',          _fmt(sim.avg_delay_ms, 1) + ' ms', '#fbbf24')}
                ${_row('Throughput',         _fmt(sim.throughput_kbps, 1) + ' kbps', '#38bdf8')}
            </div>
            <div style="margin-bottom:1rem;">
                <div style="font-size:0.72rem;text-transform:uppercase;color:#94a3b8;margin-bottom:0.4rem;letter-spacing:0.05em;">Parameters</div>
                <pre style="background:#060913;border:1px solid rgba(64,93,148,0.3);border-radius:6px;padding:0.75rem;color:#94a3b8;font-size:0.72rem;overflow-x:auto;white-space:pre-wrap;max-height:160px;overflow-y:auto;">${params}</pre>
            </div>
            <div>
                <div style="font-size:0.72rem;text-transform:uppercase;color:#94a3b8;margin-bottom:0.4rem;letter-spacing:0.05em;">Details / Diagnostics</div>
                <pre style="background:#060913;border:1px solid rgba(64,93,148,0.3);border-radius:6px;padding:0.75rem;color:#94a3b8;font-size:0.72rem;overflow-x:auto;white-space:pre-wrap;max-height:200px;overflow-y:auto;">${details}</pre>
            </div>`;
    } catch (err) {
        body.innerHTML = `<p style="color:#f87171;text-align:center;padding:1rem;">
            <i class="fas fa-exclamation-triangle"></i> Failed to load detail: ${err.message}
        </p>`;
    }
}

function _closeDetailModal() {
    const modal = document.getElementById('hist-detail-modal');
    if (modal) modal.style.display = 'none';
}

/* ------------------------------------------------------------------ */
/* Delete / Clear Actions                                               */
/* ------------------------------------------------------------------ */
async function _deleteRecord(id) {
    if (!confirm(`Delete simulation record "${id}"? This action cannot be undone.`)) return;
    try {
        await ResQNetAPI.deleteHistory(id);
        if (typeof showToast === 'function') showToast('Record deleted.', 'success');
        loadHistoryData();
    } catch (err) {
        if (typeof showToast === 'function') showToast('Delete failed: ' + err.message, 'error');
    }
}

async function _clearAllHistory() {
    if (!confirm('Clear ALL simulation history? This permanently deletes every record. This action cannot be undone.')) return;
    try {
        await ResQNetAPI.clearHistory();
        if (typeof showToast === 'function') showToast('All history cleared.', 'success');
        loadHistoryData();
    } catch (err) {
        if (typeof showToast === 'function') showToast('Clear failed: ' + err.message, 'error');
    }
}

/* ------------------------------------------------------------------ */
/* Bootstrap                                                            */
/* ------------------------------------------------------------------ */
document.addEventListener('DOMContentLoaded', () => {
    // Initial load
    loadHistoryData();

    // Refresh button
    const btnRefresh = document.getElementById('btn-refresh-history');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            btnRefresh.disabled = true;
            btnRefresh.innerHTML = '<i class="fas fa-sync-alt fa-spin"></i> Refreshing…';
            loadHistoryData().finally(() => {
                btnRefresh.disabled = false;
                btnRefresh.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh';
            });
        });
    }

    // Search button
    const btnSearch = document.getElementById('btn-search-history');
    if (btnSearch) {
        btnSearch.addEventListener('click', () => {
            _historyFilters.query     = document.getElementById('hist-search-input')?.value.trim() || '';
            _historyFilters.algorithm = document.getElementById('hist-filter-algo')?.value  || '';
            _historyFilters.status    = document.getElementById('hist-filter-status')?.value || '';
            _historyFilters.sort      = document.getElementById('hist-sort')?.value          || 'newest';
            loadHistoryData();
        });
    }

    // Allow Enter key in search field
    const searchInput = document.getElementById('hist-search-input');
    if (searchInput) {
        searchInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') btnSearch?.click();
        });
    }

    // Filter change → auto-search
    ['hist-filter-algo', 'hist-filter-status', 'hist-sort'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', () => btnSearch?.click());
    });

    // Clear All button
    const btnClear = document.getElementById('btn-clear-history');
    if (btnClear) btnClear.addEventListener('click', _clearAllHistory);

    // Modal close button
    const btnClose = document.getElementById('hist-modal-close');
    if (btnClose) btnClose.addEventListener('click', _closeDetailModal);

    // Close modal when clicking backdrop
    const modal = document.getElementById('hist-detail-modal');
    if (modal) {
        modal.addEventListener('click', e => {
            if (e.target === modal) _closeDetailModal();
        });
    }
});
