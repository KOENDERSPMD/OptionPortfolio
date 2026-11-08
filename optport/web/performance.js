'use strict';
// Performance screen (#/performance): P&L over time against SPY, and statistics on closed positions.

const PERIODS = [['1m', '1M'], ['3m', '3M'], ['ytd', 'YTD'], ['1y', '1Y'], ['all', 'All']];
const perfState = { period: 'all', chart: null };
try { perfState.period = localStorage.getItem('optport.period') || 'all'; } catch { /* storage unavailable */ }
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmtRatio = (v) => (v == null ? dash : v.toFixed(2));

async function renderPerformance() {
  let d;
  try { d = await api('GET', `/api/performance?period=${perfState.period}`); } catch (e) {
    main.innerHTML = `<div class="page"><p class="loss">${esc(e.message)}</p></div>`;
    return;
  }
  if (!location.hash.startsWith('#/performance')) return;
  const s = d.summary;
  const st = d.stats;
  const pctTile = d.capital
    ? `<span class="${signClass(s.pct)}">${fmtPct(s.pct)}</span>`
    : '<a href="#/settings" class="small">set capital</a>';
  main.innerHTML = `<div class="page page-wide">
    <header class="page-head">
      <h1>Performance</h1>
      <div class="seg" role="group" aria-label="Period">
        ${PERIODS.map(([v, l]) => `<button class="seg-btn ${v === perfState.period ? 'active' : ''}" data-period="${v}">${l}</button>`).join('')}
      </div>
    </header>
    <div class="stats">
      ${stat('P&L in period', `<span class="${signClass(s.pnl)}">${fmtUsd(s.pnl)}</span>`, 'Realized + unrealized, after commissions')}
      ${stat('Return', pctTile, d.capital ? `P&L ÷ starting capital (${fmtUsd(d.capital)})` : 'Set the starting capital in Settings')}
      ${stat('SPY', `<span class="${signClass(s.bench_pct)}">${fmtPct(s.bench_pct)}</span>`, 'SPY over the same days')}
      ${stat('Realized in period', `<span class="${signClass(s.realized)}">${fmtUsd(s.realized)}</span>`, 'Legs closed in the period, after commissions')}
      ${stat('Unrealized now', `<span class="${signClass(s.unrealized)}">${fmtUsd(s.unrealized)}</span>`, 'Open legs at the latest prices, after opening commissions')}
      ${stat('Win rate', st.win_rate == null ? dash : `${Math.round(st.win_rate * 100)}% <span class="small muted">${st.wins}/${st.count}</span>`, 'Closed positions with a profit')}
      ${stat('Profit factor', fmtRatio(st.profit_factor), 'Total of the wins ÷ total of the losses')}
    </div>
    <section class="card">
      <div class="card-head"><h2>${d.capital ? 'Return' : 'P&amp;L'} over time</h2>
        <span class="muted small">${snapshotNote(s)}</span></div>
      <div id="perf-chart" class="perf-chart"></div>
      <div id="perf-legend" class="chart-legend small"></div>
    </section>
    <div class="cols-2">
      <section class="card"><h2>Closed positions</h2>${statsTable(st)}</section>
      <section class="card"><h2>Long / short</h2>${groupTable(d.by_direction, (k) => LS(k))}</section>
    </div>
    <div class="cols-2">
      <section class="card"><h2>By month</h2>${groupTable(d.by_month, (k) => `${monthName(k)}`)}</section>
      <section class="card"><h2>By ticker</h2>${groupTable(d.by_ticker, (k) => `<b>${esc(k)}</b>`)}</section>
    </div>
    <section class="card"><h2>Closed positions in the period</h2>${closedTable(d.closed)}</section>
  </div>`;
  main.querySelectorAll('[data-period]').forEach((b) => b.addEventListener('click', () => {
    perfState.period = b.dataset.period;
    try { localStorage.setItem('optport.period', perfState.period); } catch { /* ignore */ }
    renderPerformance();
  }));
  drawPerfChart(d);
}

function snapshotNote(s) {
  if (!s.snapshots) return 'The first daily snapshot is saved after the next US close (16:15 New York) while the app runs.';
  return `${s.snapshots} daily snapshot(s) since ${fmtDate(s.first_snapshot)} · the last point is today, at the latest prices`;
}

function monthName(k) {
  const [y, m] = k.split('-');
  return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(m) - 1]} ${y}`;
}

function drawPerfChart(d) {
  const el = document.getElementById('perf-chart');
  const legend = document.getElementById('perf-legend');
  if (perfState.chart) { perfState.chart.remove(); perfState.chart = null; }
  el.innerHTML = '';
  if (!d.series.length) { el.innerHTML = '<div class="chart-empty muted">No data yet.</div>'; return; }
  const pct = !!d.capital;
  const toVal = (p) => (pct ? p.pct * 100 : p.pnl);
  const accent = cssVar('--accent'), bench = cssVar('--muted'), border = cssVar('--border');
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: cssVar('--surface') }, textColor: cssVar('--muted'), fontSize: 11 },
    grid: { vertLines: { color: border }, horzLines: { color: border } },
    rightPriceScale: { borderColor: border },
    timeScale: { borderColor: border },
    // Fixed locale: day-month dates, and no dependence on odd system locales such as en-US@posix.
    localization: { locale: 'en-GB', dateFormat: 'dd MMM \'yy',
      priceFormatter: (v) => (pct ? `${v.toFixed(1)}%` : fmtUsd(v)) },
  });
  perfState.chart = chart;
  const main_ = chart.addAreaSeries({ lineColor: accent, lineWidth: 2, topColor: `${accent}33`, bottomColor: `${accent}05`,
    priceLineVisible: false, title: '' });
  main_.setData(d.series.map((p) => ({ time: p.date, value: toVal(p) })));
  main_.createPriceLine({ price: 0, color: border, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: false });
  const hasBench = pct && d.series.some((p) => p.bench_pct != null);
  if (hasBench) {
    const b = chart.addLineSeries({ color: bench, lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false });
    b.setData(d.series.filter((p) => p.bench_pct != null).map((p) => ({ time: p.date, value: p.bench_pct * 100 })));
  }
  if (d.series.length === 1) chart.timeScale().applyOptions({ barSpacing: 40 });
  chart.timeScale().fitContent();
  const last = d.series[d.series.length - 1];
  legend.innerHTML = `<span><span class="key" style="background:${accent}"></span> Portfolio ${pct ? fmtPct(last.pct) : fmtUsd(last.pnl)}</span>
    ${hasBench ? `<span><span class="key dashed" style="border-color:${bench}"></span> SPY ${fmtPct(last.bench_pct)}</span>` : ''}
    ${pct ? '' : '<span class="muted">Set the starting capital in Settings to see % and compare with SPY.</span>'}`;
}

function statsTable(st) {
  if (!st.count) return '<p class="muted">No closed positions in this period. A position counts as closed when all its legs are closed.</p>';
  const row = (l, v, cls = '') => `<tr><th>${l}</th><td class="num ${cls}">${v}</td></tr>`;
  return `<div class="table-wrap"><table class="kv"><tbody>
    ${row('Positions closed', st.count)}
    ${row('Won / lost', `${st.wins} / ${st.losses}`)}
    ${row('Win rate', st.win_rate == null ? dash : `${Math.round(st.win_rate * 100)}%`)}
    ${row('Average win', fmtUsd(st.avg_win), 'gain')}
    ${row('Average loss', fmtUsd(st.avg_loss), 'loss')}
    ${row('Profit factor', fmtRatio(st.profit_factor))}
    ${row('Best / worst', `${fmtUsd(st.best)} / ${fmtUsd(st.worst)}`)}
    ${row('Average days held', st.avg_days == null ? dash : Math.round(st.avg_days))}
    ${row('Realized total', fmtUsd(st.total), signClass(st.total))}
  </tbody></table></div>`;
}

function groupTable(groups, label) {
  if (!groups.length) return '<p class="muted">Nothing yet.</p>';
  return `<div class="table-wrap"><table><thead><tr><th></th><th class="num">Closed</th><th class="num">Win rate</th>
    <th class="num">Avg win</th><th class="num">Avg loss</th><th class="num">Realized</th></tr></thead><tbody>
    ${groups.map((g) => `<tr><td>${label(g.key)}</td><td class="num">${g.count}</td>
      <td class="num">${g.win_rate == null ? dash : Math.round(g.win_rate * 100) + '%'}</td>
      <td class="num">${fmtUsd(g.avg_win)}</td><td class="num">${fmtUsd(g.avg_loss)}</td>
      <td class="num ${signClass(g.total)}">${fmtUsd(g.total)}</td></tr>`).join('')}
  </tbody></table></div>`;
}

function closedTable(rows) {
  if (!rows.length) return '<p class="muted">None.</p>';
  return `<div class="table-wrap"><table><thead><tr><th>Position</th><th>L/S</th><th class="num">Legs</th><th>Opened</th><th>Closed</th>
    <th class="num">Days</th><th class="num" title="Contracts × av. price × 100, all legs">Cost</th><th class="num">Commissions</th>
    <th class="num">Realized</th><th class="num" title="Realized ÷ cost">Return</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td><a href="#/position/${r.id}"><b>${esc(r.ticker)}</b> <span class="muted">${r.number}</span></a></td>
      <td>${LS(r.direction)}</td><td class="num">${r.legs}</td><td>${fmtDate(r.opened)}</td><td>${fmtDate(r.closed)}</td>
      <td class="num">${r.days}</td><td class="num">${fmtUsd(r.cost)}</td><td class="num">${r.commission ? fmtNum(r.commission) : dash}</td>
      <td class="num ${signClass(r.realized)}">${fmtUsd(r.realized)}</td><td class="num ${signClass(r.return)}">${fmtPct(r.return)}</td></tr>`).join('')}
  </tbody></table></div>`;
}

// Redraw the chart in the right colours when the system switches between light and dark.
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (location.hash.startsWith('#/performance')) renderPerformance();
});
