'use strict';
// Portfolio table (#/) and position page (#/position/<id>). Uses the helpers in app.js.

const LS = (d) => (d === 'long' ? '<span class="long">LONG</span>' : '<span class="short">SHORT</span>');
const PC = (r) => (r === 'C' ? '<span class="call">CALL</span>' : '<span class="put">PUT</span>');
const qtyText = (q) => (q > 0 ? String(q) : `−${Math.abs(q)}`);
const PRICE_SOURCE = { live: 'TWS quote', delayed: 'TWS, delayed', close: 'last daily close', option: 'from the option quotes' };
let refreshTimer = null;
let lastJobSeen = null;

// ---- portfolio ------------------------------------------------------------------

async function renderPortfolio() {
  let data;
  try { data = await api('GET', `/api/portfolio?show=${state.show}`); } catch (e) {
    main.innerHTML = `<div class="page"><p class="loss">${esc(e.message)}</p></div>`;
    return;
  }
  if (!location.hash.match(/^#\/?$/) && location.hash !== '') return;  // navigated away meanwhile
  lastJobSeen = data.refresh?.finished_at ?? data.refresh?.id ?? null;
  const t = data.totals;
  const pnlPct = t.pos_risk ? t.pnl / Math.abs(t.pos_risk) : null;
  main.innerHTML = `<div class="page page-wide">
    <header class="page-head">
      <h1>Portfolio</h1>
      <select id="show" aria-label="Show">
        ${[['open', 'Open'], ['closed', 'Closed'], ['all', 'All']].map(([v, l]) => `<option value="${v}" ${v === state.show ? 'selected' : ''}>${l}</option>`).join('')}
      </select>
      <span id="refresh-info" class="muted small">${refreshInfo(data.refresh)}</span>
      <button class="btn" id="refresh">↻ Refresh</button>
      <button class="btn primary" id="new-position">+ New position</button>
    </header>
    <div class="stats">
      ${stat('Open positions', t.positions)}
      ${stat('Position risk', fmtUsd(t.pos_risk), 'Total paid for the open legs (received amounts subtracted)')}
      ${stat('Position size', fmtUsd(t.pos_size), 'What the open legs are worth now')}
      ${stat('Unrealized P&L', `<span class="${signClass(t.pnl)}">${fmtUsd(t.pnl)}</span> <span class="small ${signClass(t.pnl)}">${fmtPct(pnlPct)}</span>`,
        t.missing ? `${t.missing} position(s) without a price yet are left out` : 'Position size − position risk')}
      ${stat('Delta dollars', fmtUsd(t.delta_dollars), 'Net stock exposure: contracts × 100 × delta × stock price')}
      ${stat('Realized P&L', `<span class="${signClass(t.realized)}">${fmtUsd(t.realized)}</span>`, 'Closed legs of the positions shown')}
    </div>
    ${data.positions.length ? portfolioTable(data) : emptyPortfolio()}
    ${data.positions.length ? legend(data) : ''}
  </div>`;
  document.getElementById('show').addEventListener('change', (e) => {
    state.show = e.target.value;
    try { localStorage.setItem('optport.show', state.show); } catch { /* storage unavailable */ }
    renderPortfolio();
  });
  document.getElementById('new-position').addEventListener('click', () => openPositionDialog());
  document.getElementById('refresh').addEventListener('click', startRefresh);
  main.querySelectorAll('tr[data-pos]').forEach((tr) => tr.addEventListener('click', (ev) => {
    if (ev.target.closest('a, button')) return;
    location.hash = `#/position/${tr.dataset.pos}`;
  }));
  if (data.refresh?.status === 'running') watchRefresh();
}
try { state.show = localStorage.getItem('optport.show') || 'open'; } catch { /* storage unavailable */ }

const stat = (label, value, title = '') => `<div class="stat" title="${esc(title)}"><div class="stat-label">${label}</div><div class="stat-value num">${value}</div></div>`;

function emptyPortfolio() {
  const msg = state.show === 'open' ? 'No open positions yet. Click <b>+ New position</b> to add your first one.' : 'Nothing here.';
  return `<section class="card empty-card"><p class="muted">${msg}</p></section>`;
}

function refreshInfo(job) {
  if (!job) return 'No prices fetched yet';
  if (job.status === 'running') return 'Refreshing prices…';
  const when = `Prices ${fmtTime(job.finished_at)}`;
  const problems = job.message && job.message.includes('problem') ? ' · <span class="warn-text" title="' + esc(job.message) + '">⚠ problems (hover)</span>' : '';
  return job.status === 'error' ? `<span class="loss" title="${esc(job.message)}">⚠ ${esc(job.message)}</span>` : when + problems;
}

async function startRefresh() {
  try { await api('POST', '/api/refresh'); } catch (e) { toast(e.message); }
  document.getElementById('refresh-info').innerHTML = 'Refreshing prices…';
  watchRefresh();
}

function watchRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    const { job } = await api('GET', '/api/refresh').catch(() => ({ job: null }));
    if (job?.status === 'running') { watchRefresh(); return; }
    if (location.hash.match(/^#\/?$/) || location.hash === '') renderPortfolio();
    if (job?.status === 'error') toast(job.message);
  }, 1500);
}

// Pick up the scheduled refreshes (every few minutes during market hours) without a manual reload.
setInterval(async () => {
  if (!(location.hash.match(/^#\/?$/) || location.hash === '') || document.querySelector('dialog[open]')) return;
  const { job } = await api('GET', '/api/refresh').catch(() => ({ job: null }));
  const seen = job?.finished_at ?? job?.id ?? null;
  if (job && job.status !== 'running' && seen !== lastJobSeen) renderPortfolio();
}, 30000);

function portfolioTable(data) {
  const warnDays = data.cfg.expiry_warn_days;
  const rows = data.positions.map((p, i) => positionRows(p, i, warnDays, state.show !== 'open')).join('');
  return `<div class="table-wrap sheet-wrap"><table class="sheet">
    <thead>
      <tr class="groups">
        <th colspan="4" class="g-pos">Position</th>
        <th colspan="9" class="g-buy">Initial purchase</th>
        <th colspan="2" class="g-risk">Initial risk</th>
        <th colspan="8" class="g-now">Current position</th>
      </tr>
      <tr>
        <th>Ticker</th><th>L/S</th><th class="num">Price</th><th>Earnings</th>
        <th class="num">#</th><th>P/C</th><th class="num">Strike</th><th>Expiry</th><th class="num">Av. price</th>
        <th class="num" title="Stock price at entry">Und. entry</th><th>Entry</th>
        <th class="num" title="Intrinsic value per share at entry">IV</th><th class="num" title="Time value per share at entry">TV</th>
        <th class="num">Stop</th><th class="num" title="Contracts × av. price × 100">Pos risk</th>
        <th class="num">Target</th><th class="num">DTE</th><th class="num" title="Current option price (mid)">Price*</th>
        <th class="num" title="Contracts × current price × 100">Pos size</th><th class="num">P&amp;L</th>
        <th class="num" title="Intrinsic value per share now">IV*</th><th class="num" title="Time value per share now">TV*</th>
        <th class="num" title="Contracts × 100 × delta × stock price">Δ $</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function positionRows(p, idx, warnDays, withClosed) {
  const legs = withClosed ? p.legs : p.legs.filter((l) => l.close_price == null);
  const m = p.m;
  const span = Math.max(legs.length, 1);
  const band = idx % 2 ? 'band' : '';
  const priceTitle = p.und.error ? `Last refresh failed: ${p.und.error}` : p.und.source ? `${PRICE_SOURCE[p.und.source] ?? p.und.source}, ${fmtTime(p.und.fetched_at)}` : 'No price yet';
  const earnTitle = p.earnings.error ? p.earnings.error : m.earnings_before_expiry ? 'Earnings before the last expiry' : (p.earnings.fetched_at ? `Yahoo Finance, ${fmtTime(p.earnings.fetched_at)}` : '');
  const stopCls = m.stop_state === 'hit' ? 'cell-alert' : m.stop_state === 'near' ? 'cell-warn' : '';
  const stopTitle = m.stop_state === 'hit' ? 'The price is through the stop' : m.to_stop != null ? `${fmtPct(m.to_stop)} from the price` : '';
  const posCells = `
    <td rowspan="${span}" class="tk"><a href="#/position/${p.id}">${esc(p.ticker)}</a><div class="muted tiny">${p.number}</div></td>
    <td rowspan="${span}">${LS(p.direction)}</td>
    <td rowspan="${span}" class="num cell-price ${p.und.error ? 'stale' : ''}" title="${esc(priceTitle)}">${fmtNum(p.und.price)}</td>
    <td rowspan="${span}" class="${m.earnings_before_expiry ? 'cell-warn' : ''}" title="${esc(earnTitle)}">${p.earnings.date ? fmtDate(p.earnings.date) : (p.earnings.error ? '⚠' : dash)}</td>`;
  const stopCell = `<td rowspan="${span}" class="num ${stopCls}" title="${esc(stopTitle)}">${fmtNum(p.stop)}</td>`;
  const targetCell = `<td rowspan="${span}" class="num cell-target" title="${m.to_target != null ? fmtPct(m.to_target) + ' from the price' : ''}">${fmtNum(p.target)}</td>`;
  if (!legs.length) {
    return `<tr class="${band}" data-pos="${p.id}">${posCells}<td colspan="9" class="muted">No legs yet</td>${stopCell}<td></td>${targetCell}<td colspan="7"></td></tr>`;
  }
  const out = legs.map((l, i) => {
    const lm = l.m;
    const closed = l.close_price != null;
    const expCls = closed ? '' : lm.dte < 0 ? 'cell-alert' : lm.dte <= warnDays ? 'cell-alert-soft' : '';
    const q = l.quote;
    const qTitle = closed ? `Closed ${fmtDate(l.close_date)} at ${fmtNum(l.close_price)}`
      : q?.error ? `No quote: ${q.error}` : q ? `bid ${fmtNum(q.bid)} · ask ${fmtNum(q.ask)} · last ${fmtNum(q.last)}${q.delayed ? ' (delayed)' : ''} · ${fmtTime(q.fetched_at)}` : 'No quote yet';
    const pnl = closed ? lm.realized : lm.pnl;
    const mismatch = l.broker_mismatch ? `<span class="badge-warn" title="TWS holds ${l.broker_qty} of this option (all positions here together: different)">TWS ${l.broker_qty}</span>` : '';
    return `<tr class="${band} ${closed ? 'closed' : ''} ${i === legs.length - 1 && legs.length > 1 ? '' : ''}" data-pos="${p.id}">
      ${i === 0 ? posCells : ''}
      <td class="num">${qtyText(l.qty)}${mismatch}</td><td>${PC(l.right)}</td><td class="num">${fmtNum(l.strike)}</td>
      <td class="${expCls}" title="${lm.dte < 0 ? 'Expired' : ''}">${fmtDate(l.expiry)}${l.trading_class ? ` <span class="muted tiny">${esc(l.trading_class)}</span>` : ''}</td>
      <td class="num">${fmtNum(l.avg_price)}</td><td class="num">${fmtNum(l.und_entry)}</td><td>${fmtDate(l.entry_date)}</td>
      <td class="num">${fmtNum(lm.iv_entry)}</td><td class="num">${fmtNum(lm.tv_entry)}</td>
      ${i === 0 ? stopCell : ''}
      <td class="num">${fmtUsd(lm.pos_risk)}</td>
      ${i === 0 ? targetCell : ''}
      <td class="num">${closed ? dash : lm.dte}</td>
      <td class="num ${q?.error && !closed ? 'stale' : ''}" title="${esc(qTitle)}">${fmtNum(lm.price_now)}${closed ? '<span class="tiny muted"> closed</span>' : ''}</td>
      <td class="num">${fmtUsd(lm.pos_size)}</td>
      <td class="num ${pnl == null ? '' : pnl >= 0 ? 'cell-gain' : 'cell-loss'}" title="${closed ? 'Realized' : 'Unrealized'}">${fmtUsd(pnl)}</td>
      <td class="num">${fmtNum(lm.iv_now)}</td><td class="num">${fmtNum(lm.tv_now)}</td>
      <td class="num" title="${lm.delta != null ? `delta ${fmtNum(lm.delta, 2)}${lm.delta_calc ? ' (calculated)' : ' (TWS)'}` : ''}">${fmtUsd(lm.delta_dollars)}${lm.delta_calc ? '*' : ''}</td>
    </tr>`;
  });
  if (legs.length > 1) {
    out.push(`<tr class="${band} subtotal" data-pos="${p.id}"><td colspan="14" class="sub-label">${p.number} total</td>
      <td class="num">${fmtUsd(m.pos_risk)}</td><td colspan="3"></td><td class="num">${fmtUsd(m.pos_size)}</td>
      <td class="num ${signClass(m.pnl)}">${fmtUsd(m.pnl)}</td><td colspan="2"></td><td class="num">${fmtUsd(m.delta_dollars)}</td></tr>`);
  }
  return out.join('');
}

function legend(data) {
  return `<p class="legend muted small">
    <span class="sw cell-warn"></span> earnings before the last expiry, or price within ${data.cfg.stop_warn_pct}% of the stop ·
    <span class="sw cell-alert"></span> price through the stop, or expired ·
    <span class="sw cell-alert-soft"></span> expires within ${data.cfg.expiry_warn_days} days ·
    * delta calculated (TWS sent none) · <span class="badge-warn">TWS n</span> TWS holds a different quantity
    ${data.broker_checked_at ? `(checked ${fmtTime(data.broker_checked_at)})` : ''} · hover a price for its bid/ask and time</p>`;
}

// ---- position page -------------------------------------------------------------------

async function renderPosition(id) {
  let p;
  try { p = await api('GET', `/api/positions/${id}`); } catch (e) {
    main.innerHTML = `<div class="page"><p class="muted">${esc(e.message)}</p><p><a href="#/">← Portfolio</a></p></div>`;
    return;
  }
  const m = p.m;
  const openLegs = p.legs.filter((l) => l.close_price == null);
  const closedLegs = p.legs.filter((l) => l.close_price != null);
  main.innerHTML = `<div class="page page-wide">
    <p class="crumb"><a href="#/">← Portfolio</a></p>
    <header class="page-head">
      <h1><span class="muted">${p.number}</span> ${esc(p.ticker)} ${LS(p.direction)}</h1>
      <span class="num">${fmtNum(p.und.price)} <span class="muted small">${p.und.source ? esc(PRICE_SOURCE[p.und.source] ?? p.und.source) + ', ' + fmtTime(p.und.fetched_at) : 'no price yet'}</span></span>
      <span class="pill ${m.open ? 'pill-open' : 'pill-closed'}">${m.open ? 'Open' : 'Closed'}</span>
      <button class="btn" id="edit-pos">Edit</button>
      <button class="btn danger" id="delete-pos">Delete</button>
    </header>
    <div class="stats">
      ${stat('Stop', `<span class="${m.stop_state === 'hit' ? 'loss' : ''}">${fmtNum(p.stop)}</span> <span class="small muted">${fmtPct(m.to_stop)}</span>`)}
      ${stat('Target', `${fmtNum(p.target)} <span class="small muted">${fmtPct(m.to_target)}</span>`)}
      ${stat('Earnings', p.earnings.date ? `<span class="${m.earnings_before_expiry ? 'warn-text' : ''}">${fmtDate(p.earnings.date)}</span>` : (p.earnings.error ? '<span class="small loss">not available</span>' : dash), p.earnings.error ?? '')}
      ${stat('Position risk', fmtUsd(m.pos_risk))}
      ${stat('Unrealized P&L', `<span class="${signClass(m.pnl)}">${fmtUsd(m.pnl)}</span>`)}
      ${stat('Realized P&L', `<span class="${signClass(m.realized)}">${fmtUsd(m.realized)}</span>`)}
      ${stat('Delta dollars', fmtUsd(m.delta_dollars))}
    </div>
    <section class="card">
      <div class="card-head"><h2>Open legs</h2><button class="btn sm" id="add-leg">+ Add leg</button></div>
      ${openLegs.length ? legTable(openLegs, true) : '<p class="muted">No open legs.</p>'}
    </section>
    ${closedLegs.length ? `<section class="card"><h2>Closed legs</h2>${legTable(closedLegs, false)}</section>` : ''}
    <section class="card">
      <h2>Notes</h2>
      <textarea id="notes" rows="5" placeholder="Plan, reasons, what to watch">${esc(p.notes)}</textarea>
      <div class="card-foot"><span class="muted small">Last change ${fmtDateTime(p.updated_at)}</span>
        <button class="btn primary" id="save-notes">Save</button></div>
    </section>
  </div>`;
  document.getElementById('edit-pos').addEventListener('click', () => openPositionDialog(p));
  document.getElementById('add-leg').addEventListener('click', () => openPositionDialog(p, 'add'));
  document.getElementById('delete-pos').addEventListener('click', async () => {
    if (!confirm(`Delete ${p.number} ${p.ticker} with all its legs? This cannot be undone.\n\nTo record that you closed it, close its legs instead.`)) return;
    try { await api('DELETE', `/api/positions/${p.id}`); location.hash = '#/'; } catch (e) { toast(e.message); }
  });
  document.getElementById('save-notes').addEventListener('click', async () => {
    try { await api('PATCH', `/api/positions/${p.id}`, { notes: document.getElementById('notes').value }); toast('Saved'); } catch (e) { toast(e.message); }
  });
  main.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => legAction(p, b.dataset.act, Number(b.dataset.leg))));
}

function legTable(legs, open) {
  return `<div class="table-wrap"><table class="legs">
    <thead><tr><th>Leg</th><th class="num">#</th><th>P/C</th><th class="num">Strike</th><th>Expiry</th>
      <th class="num">Av. price</th><th class="num">Und. entry</th><th>Entry</th>
      ${open ? '<th class="num">DTE</th><th class="num">Bid</th><th class="num">Ask</th><th class="num">Price*</th><th class="num">P&amp;L</th><th class="num">Delta</th><th class="num">TWS qty</th>'
    : '<th class="num">Close price</th><th>Closed</th><th class="num">Realized</th>'}
      <th></th></tr></thead>
    <tbody>${legs.map((l) => {
    const lm = l.m;
    const cells = open
      ? `<td class="num">${lm.dte}</td><td class="num">${fmtNum(l.quote?.bid)}</td><td class="num">${fmtNum(l.quote?.ask)}</td>
         <td class="num" title="${esc(l.quote?.error ?? lm.price_source ?? '')}">${fmtNum(lm.price_now)}</td>
         <td class="num ${signClass(lm.pnl)}">${fmtUsd(lm.pnl)}</td>
         <td class="num">${fmtNum(lm.delta)}${lm.delta_calc ? '*' : ''}</td>
         <td class="num ${l.broker_mismatch ? 'warn-text' : ''}">${l.broker_qty ?? dash}</td>`
      : `<td class="num">${fmtNum(l.close_price)}</td><td>${fmtDate(l.close_date)}</td><td class="num ${signClass(lm.realized)}">${fmtUsd(lm.realized)}</td>`;
    const acts = open
      ? `<button class="btn sm" data-act="close" data-leg="${l.id}">Close</button> <button class="btn sm" data-act="edit" data-leg="${l.id}">Edit</button> <button class="btn sm danger" data-act="delete" data-leg="${l.id}" title="Delete (for a leg entered by mistake)">✕</button>`
      : `<button class="btn sm" data-act="reopen" data-leg="${l.id}">Reopen</button>`;
    return `<tr><td class="muted">${l.number}</td><td class="num">${qtyText(l.qty)}</td><td>${PC(l.right)}</td><td class="num">${fmtNum(l.strike)}</td>
      <td>${fmtDate(l.expiry)}${l.trading_class ? ` <span class="muted tiny">${esc(l.trading_class)}</span>` : ''}</td>
      <td class="num">${fmtNum(l.avg_price)}</td><td class="num">${fmtNum(l.und_entry)}</td><td>${fmtDate(l.entry_date)}</td>${cells}
      <td class="acts">${acts}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

async function legAction(p, act, legId) {
  const leg = p.legs.find((l) => l.id === legId);
  try {
    if (act === 'edit') { openPositionDialog(p, 'edit', leg); return; }
    if (act === 'close') { openCloseDialog(p, leg); return; }
    if (act === 'delete') {
      if (!confirm(`Delete leg ${leg.number}? Use this for a leg entered by mistake; to record a sale, use Close.`)) return;
      await api('DELETE', `/api/legs/${legId}`);
    }
    if (act === 'reopen') {
      if (!confirm(`Reopen leg ${leg.number}? Its close price and date are removed.`)) return;
      await api('POST', `/api/legs/${legId}/reopen`);
    }
    renderPosition(p.id);
  } catch (e) { toast(e.message); }
}

// ---- dialogs ---------------------------------------------------------------------------

const dlgPos = document.getElementById('dlg-position');
const formPos = document.getElementById('form-position');
const legRows = document.getElementById('leg-rows');
let posMode = null;   // {mode: 'new'|'edit-pos'|'add'|'edit', pos, leg}

function legRowHtml(l = {}) {
  const v = (x) => (x == null ? '' : esc(x));
  return `<tr>
    <td><input name="qty" type="number" step="1" required value="${v(l.qty ?? 1)}" class="w-qty"></td>
    <td><select name="right"><option value="C" ${l.right === 'P' ? '' : 'selected'}>CALL</option><option value="P" ${l.right === 'P' ? 'selected' : ''}>PUT</option></select></td>
    <td><input name="strike" type="number" step="0.01" min="0" required value="${v(l.strike)}" class="w-num"></td>
    <td><input name="expiry" type="date" required value="${v(l.expiry)}"></td>
    <td><input name="avg_price" type="number" step="0.01" min="0" required value="${v(l.avg_price)}" class="w-num"></td>
    <td><input name="und_entry" type="number" step="0.01" min="0" value="${v(l.und_entry)}" class="w-num"></td>
    <td><input name="entry_date" type="date" required value="${v(l.entry_date ?? todayIso())}"></td>
    <td><input name="trading_class" value="${v(l.trading_class)}" class="w-cls" autocomplete="off"></td>
    <td><button type="button" class="btn sm" data-remove title="Remove this leg">✕</button></td>
  </tr>`;
}

function addLegRow(l) {
  legRows.insertAdjacentHTML('beforeend', legRowHtml(l));
  legRows.lastElementChild.querySelector('[data-remove]').addEventListener('click', (ev) => ev.target.closest('tr').remove());
}

/** New position; edit position fields; add a leg; or edit one leg. */
function openPositionDialog(pos = null, mode = pos ? 'edit-pos' : 'new', leg = null) {
  posMode = { mode, pos, leg };
  formPos.reset();
  formError(formPos);
  legRows.innerHTML = '';
  const showPos = mode === 'new' || mode === 'edit-pos';
  const showLegs = mode !== 'edit-pos';
  document.getElementById('pos-fields').hidden = !showPos;
  formPos.querySelectorAll('#pos-fields input, #pos-fields select').forEach((el) => { el.disabled = !showPos; });
  for (const el of [document.getElementById('legs-title'), formPos.querySelector('.hint'), formPos.querySelector('.leg-editor').parentElement]) el.hidden = !showLegs;
  document.getElementById('add-leg-row').hidden = mode !== 'new';
  document.getElementById('pos-title').textContent = {
    new: 'New position', 'edit-pos': `Edit ${pos?.number} ${pos?.ticker}`,
    add: `Add a leg to ${pos?.number} ${pos?.ticker}`, edit: `Edit leg ${leg?.number}`,
  }[mode];
  if (pos) {
    formPos.ticker.value = pos.ticker; formPos.direction.value = pos.direction;
    formPos.stop.value = pos.stop ?? ''; formPos.target.value = pos.target ?? '';
  }
  if (mode === 'new') addLegRow();
  if (mode === 'add') addLegRow({ und_entry: pos.und.price != null ? Number(pos.und.price.toFixed(2)) : null });
  if (mode === 'edit') addLegRow(leg);
  legRows.querySelectorAll('[data-remove]').forEach((b) => { b.hidden = mode !== 'new'; });
  dlgPos.showModal();
}
document.getElementById('add-leg-row').addEventListener('click', () => {
  const last = legRows.lastElementChild;
  // a new leg usually shares the expiry, stock price and date of the previous one
  addLegRow(last ? { qty: -1, right: last.querySelector('[name=right]').value, expiry: last.querySelector('[name=expiry]').value,
    und_entry: last.querySelector('[name=und_entry]').value || null, entry_date: last.querySelector('[name=entry_date]').value } : {});
});

const numOrNull = (v) => (v === '' || v == null ? null : Number(v));

function readLeg(tr) {
  const get = (n) => tr.querySelector(`[name=${n}]`).value;
  return {
    qty: Number(get('qty')), right: get('right'), strike: Number(get('strike')), expiry: get('expiry'),
    avg_price: Number(get('avg_price')), und_entry: numOrNull(get('und_entry')), entry_date: get('entry_date'),
    trading_class: get('trading_class').trim() || null,
  };
}

formPos.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const { mode, pos, leg } = posMode;
  const posFields = { ticker: formPos.ticker.value, direction: formPos.direction.value,
    stop: numOrNull(formPos.stop.value), target: numOrNull(formPos.target.value) };
  const legs = [...legRows.querySelectorAll('tr')].map(readLeg);
  if (legs.some((l) => l.qty === 0)) { formError(formPos, 'The number of contracts cannot be 0; use a negative number for a sold leg.'); return; }
  try {
    let result;
    if (mode === 'new') result = await api('POST', '/api/positions', { ...posFields, legs });
    else if (mode === 'edit-pos') result = await api('PATCH', `/api/positions/${pos.id}`, posFields);
    else if (mode === 'add') result = await api('POST', `/api/positions/${pos.id}/legs`, legs[0]);
    else result = await api('PATCH', `/api/legs/${leg.id}`, legs[0]);
    dlgPos.close();
    toast(mode === 'new' ? `${result.number} ${result.ticker} added — click Refresh for prices` : 'Saved');
    if (mode === 'new') location.hash = '#/';
    route();
  } catch (e) { formError(formPos, e.message); }
});

const dlgClose = document.getElementById('dlg-close');
const formClose = document.getElementById('form-close');
let closing = null;

function openCloseDialog(p, leg) {
  closing = { p, leg };
  formClose.reset();
  formError(formClose);
  document.getElementById('close-what').textContent = `${leg.number} · ${qtyText(leg.qty)} ${leg.right === 'C' ? 'CALL' : 'PUT'} ${fmtNum(leg.strike)} ${fmtDate(leg.expiry)}`;
  formClose.qty.value = Math.abs(leg.qty);
  formClose.qty.max = Math.abs(leg.qty);
  formClose.price.value = leg.m.price_now != null ? leg.m.price_now.toFixed(2) : '';
  formClose.date.value = todayIso();
  document.getElementById('close-hint').textContent = `${leg.qty > 0 ? 'Sold' : 'Bought back'} at this price per share. Fewer contracts than ${Math.abs(leg.qty)} closes part of the leg. For an option that expired worthless, use price 0 and the expiry date.`;
  dlgClose.showModal();
}

formClose.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const { p, leg } = closing;
  try {
    await api('POST', `/api/legs/${leg.id}/close`, { qty: Number(formClose.qty.value), price: Number(formClose.price.value), date: formClose.date.value });
    dlgClose.close();
    toast('Leg closed');
    renderPosition(p.id);
  } catch (e) { formError(formClose, e.message); }
});
