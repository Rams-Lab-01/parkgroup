odoo.define('sgc_crm_dashboard.big_screen', function (require) {
    'use strict';

    const COLORS = ['#594E90','#BC4C96','#1EC198','#FFA600','#FF5F66','#0dcaf0','#28a745','#7D7EAF'];
    let teamChart = null;
    let dailyChart = null;

    function fmtNum(n) {
        return n != null ? Number(n).toLocaleString('en-US') : '—';
    }
    function fmtMoney(n) {
        return n != null ? Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
    }

    function updateClock() {
        var el = document.getElementById('bs-clock');
        if (el) {
            el.textContent = new Date().toLocaleString('en-US', {weekday:'short', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit'});
        }
    }

    function renderRanking(containerId, items, valueLabel) {
        var el = document.getElementById(containerId);
        if (!el) return;
        if (!items || !items.length) { el.innerHTML = '<div style="opacity:0.4;font-size:0.8rem;">No data</div>'; return; }
        var maxVal = Math.max.apply(null, items.map(function(i){ return i.count || 0; }));
        var html = '';
        items.forEach(function(item, idx) {
            var pct = maxVal > 0 ? ((item.count / maxVal) * 100) : 0;
            var color = COLORS[idx % COLORS.length];
            html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">' +
                '<div style="width:24px;text-align:right;font-size:0.8rem;font-weight:700;opacity:0.5;">' + (idx+1) + '</div>' +
                '<div style="flex:1;">' +
                    '<div style="display:flex;justify-content:space-between;margin-bottom:3px;">' +
                        '<span style="font-size:0.82rem;font-weight:600;">' + (item.name || 'Unknown') + '</span>' +
                        '<span style="font-size:0.82rem;font-weight:700;color:' + color + ';">' + (item.count || 0) + ' ' + valueLabel + '</span>' +
                    '</div>' +
                    '<div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;">' +
                        '<div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:3px;transition:width 0.6s ease;"></div>' +
                    '</div>' +
                '</div>' +
            '</div>';
        });
        el.innerHTML = html;
    }

    function renderTeamChart(data) {
        var ctx = document.getElementById('bs-team-chart');
        if (!ctx || !data || !data.length) return;
        var labels = data.map(function(d){ return d.name; });
        var wonData = data.map(function(d){ return d.won || 0; });
        var lostData = data.map(function(d){ return d.lost || 0; });
        if (teamChart) teamChart.destroy();
        teamChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    { label: 'Won', data: wonData, backgroundColor: '#BC4C96', borderRadius: 4 },
                    { label: 'Lost', data: lostData, backgroundColor: '#FF5F66', borderRadius: 4 },
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#e8eaf0', font: { size: 11 } } } },
                scales: {
                    x: { ticks: { color: '#e8eaf0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.06)' } },
                    y: { ticks: { color: '#e8eaf0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.06)' } }
                }
            }
        });
    }

    function renderDailyChart(data) {
        var ctx = document.getElementById('bs-daily-chart');
        if (!ctx || !data) return;
        if (dailyChart) dailyChart.destroy();
        var datasets = (data.datasets || []).map(function(ds, idx) {
            return {
                label: ds.label,
                data: ds.data,
                borderColor: ds.borderColor || COLORS[idx % COLORS.length],
                backgroundColor: ds.backgroundColor || (COLORS[idx % COLORS.length] + '20'),
                tension: 0.3,
                fill: false,
                pointRadius: 2,
            };
        });
        dailyChart = new Chart(ctx, {
            type: 'line',
            data: { labels: data.labels || [], datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#e8eaf0', font: { size: 10 } } } },
                scales: {
                    x: { ticks: { color: '#e8eaf0', font: { size: 9 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.06)' } },
                    y: { ticks: { color: '#e8eaf0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.06)' } }
                }
            }
        });
    }

    function loadData() {
        fetch('/dashboard/big-screen/data')
            .then(function(resp) { return resp.json(); })
            .then(function(d) {
                var kpi = d.kpi || {};
                var el;
                el = document.getElementById('bs-kpi-leads'); if (el) el.textContent = fmtNum(kpi.total_leads);
                el = document.getElementById('bs-kpi-followup'); if (el) el.textContent = fmtNum(kpi.follow_up);
                el = document.getElementById('bs-kpi-research'); if (el) el.textContent = fmtNum(kpi.research_done);
                el = document.getElementById('bs-kpi-outreach'); if (el) el.textContent = fmtNum(kpi.outreach_email);
                el = document.getElementById('bs-kpi-booked'); if (el) el.textContent = fmtNum(kpi.booked);
                el = document.getElementById('bs-kpi-won'); if (el) el.textContent = fmtNum(kpi.won);
                el = document.getElementById('bs-kpi-revenue'); if (el) el.textContent = fmtMoney(kpi.est_revenue);

                renderRanking('bs-rank-leads-list', d.rank_leads, 'leads');
                renderRanking('bs-rank-research-list', d.rank_research, 'researched');
                renderRanking('bs-rank-outreach-list', d.rank_outreach, 'outreached');
                renderRanking('bs-rank-booking-list', d.rank_booking, 'booked');
                renderRanking('bs-rank-won-list', d.rank_won, 'won');
                renderRanking('bs-rank-activity-list', d.rank_activity, 'activities');

                renderTeamChart(d.teams);
                renderDailyChart(d.daily_chart);
            })
            .catch(function(err) { console.error('Big screen data load failed:', err); });
    }

    function init() {
        updateClock();
        setInterval(updateClock, 1000);
        loadData();
        setInterval(loadData, 60000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
});
