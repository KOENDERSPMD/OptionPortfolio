'use strict';
// Option Portfolio — browser UI (vanilla JS, no build step). Hash routes: #/, #/position/<id>, #/settings.
// portfolio.js (loaded first) holds the portfolio table and the position page.

const main = document.getElementById('main');
const state = { show: 'open', tws: { connected: false } };

// ---- helpers ---------------------------------------------------------------

/** Call the JSON API. Throws an Error with the server's message (FastAPI's `detail`). */
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data?.detail ?? `Request failed (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map((d) => `${d.loc?.slice(-1)[0] ?? ''}: ${d.msg}`).join('; ');
    throw new Error(msg);
  }
  return data;
}

// Everything that goes into innerHTML passes through esc().
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const dash = '—';
const pad = (n) => String(n).padStart(2, '0');

/** dd-mm-yyyy. Server timestamps are UTC (…Z) and shown in local time. */
function fmtDate(s) {
  if (!s) return dash;
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s.slice(8, 10)}-${s.slice(5, 7)}-${s.slice(0, 4)}`;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()}`;
}
function fmtDateTime(s) {
  if (!s) return dash;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : `${fmtDate(s)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtTime(s) {
  if (!s) return dash;
  const d = new Date(s);
  const today = new Date().toDateString() === d.toDateString();
  return today ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : fmtDateTime(s);
}
function fmtNum(v, dp = 2) {
  if (v == null || !Number.isFinite(v)) return dash;
  v = Number(v.toFixed(dp)) || 0;   // no "-0" for tiny negative amounts
  return v.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
/** Whole dollars with thousands separators, e.g. -1,110. */
const fmtUsd = (v) => fmtNum(v, 0);
/** +12.3% with an explicit sign; colour it with signClass(). */
function fmtPct(v) {
  if (v == null || !Number.isFinite(v)) return dash;
  const p = v * 100;
  return `${p > 0 ? '+' : ''}${p.toFixed(Math.abs(p) >= 100 ? 0 : 1)}%`;
}
const signClass = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '');
const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), msg.length > 80 ? 6000 : 2600);
}
function formError(form, msg) {
  const err = form.querySelector('.form-error');
  err.textContent = msg ?? '';
  err.hidden = !msg;
}

document.querySelectorAll('dialog [data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));

// ---- TWS status (sidebar) -----------------------------------------------------

async function pollTws() {
  try { state.tws = await api('GET', '/api/tws'); } catch { state.tws = { connected: false, error: 'The app does not answer.' }; }
  const el = document.getElementById('tws-status');
  el.querySelector('.conn-dot').classList.toggle('on', !!state.tws.connected);
  el.querySelector('.label').textContent = state.tws.connected ? 'TWS connected' : 'TWS not connected';
  el.title = state.tws.connected ? `Connected to ${state.tws.host}:${state.tws.port}` : (state.tws.error || 'Not connected');
}
setInterval(pollTws, 15000);

// ---- settings --------------------------------------------------------------------

async function renderSettings() {
  const s = await api('GET', '/api/settings');
  const tws = await api('GET', '/api/tws');
  const twsLine = (t) => (t.connected
    ? `<span class="conn-dot on"></span> Connected to ${esc(t.host)}:${t.port} since ${fmtTime(t.connected_since)}`
    : `<span class="conn-dot"></span> <span class="loss">${esc(t.error ?? 'Not connected yet.')}</span>`);
  main.innerHTML = `<div class="page"><h1>Settings</h1>
    <section class="card">
      <h2>Interactive Brokers (TWS or IB Gateway)</h2>
      <p class="hint">Read-only: the app reads prices, option quotes and your positions, and never places orders.</p>
      <div class="grid-3">
        <label class="field">Host <input id="ib-host" value="${esc(s.ib_host)}"></label>
        <label class="field">Port <input id="ib-port" type="number" value="${s.ib_port}"></label>
        <label class="field">Client ID <input id="ib-client" type="number" value="${s.ib_client_id}"></label>
      </div>
      <p class="hint">TWS 7496 (paper 7497), IB Gateway 4001 (paper 4002). The Trade Idea app uses client ID 17; keep this one different so both can be connected.</p>
      <p id="tws-line" class="tws-line">${twsLine(tws)}</p>
      <div class="card-foot"><button class="btn" id="tws-test">Test connection</button>
        <button class="btn primary" id="save-ib">Save</button></div>
    </section>
    <section class="card">
      <h2>Prices and warnings</h2>
      <div class="grid-3">
        <label class="field">Refresh every (minutes, market hours; 0 = off) <input id="refresh-min" type="number" min="0" value="${s.refresh_minutes}"></label>
        <label class="field">Stop warning: within (%) <input id="stop-warn" type="number" min="0" step="0.5" value="${s.stop_warn_pct}"></label>
        <label class="field">Expiry warning: from (days before) <input id="exp-warn" type="number" min="0" value="${s.expiry_warn_days}"></label>
        <label class="field">Interest rate (for calculated delta) <input id="rate" type="number" min="0" step="0.0025" value="${s.interest_rate}"></label>
      </div>
      <p class="hint">Market hours: Monday–Friday 9:30–16:15 New York. Earnings dates come from Yahoo Finance and are refreshed once a day and with every Refresh.</p>
      <div class="card-foot"><span></span><button class="btn primary" id="save-prices">Save</button></div>
    </section>
  </div>`;
  const save = async (body) => {
    try { await api('PUT', '/api/settings', body); toast('Saved'); pollTws(); } catch (e) { toast(e.message); }
  };
  document.getElementById('save-ib').addEventListener('click', () => save({
    ib_host: document.getElementById('ib-host').value, ib_port: Number(document.getElementById('ib-port').value),
    ib_client_id: Number(document.getElementById('ib-client').value),
  }));
  document.getElementById('save-prices').addEventListener('click', () => save({
    refresh_minutes: Number(document.getElementById('refresh-min').value),
    stop_warn_pct: Number(document.getElementById('stop-warn').value),
    expiry_warn_days: Number(document.getElementById('exp-warn').value),
    interest_rate: Number(document.getElementById('rate').value),
  }));
  document.getElementById('tws-test').addEventListener('click', async (ev) => {
    ev.target.disabled = true;
    try { document.getElementById('tws-line').innerHTML = twsLine(await api('POST', '/api/tws/test')); pollTws(); } finally { ev.target.disabled = false; }
  });
}

// ---- quit / update notice ------------------------------------------------------------

document.getElementById('quit').addEventListener('click', async () => {
  try {
    const { busy } = await api('GET', '/api/busy');
    const warn = busy.length ? `\n\nStill busy: ${busy.join(', ')}. Closing now stops that work.` : '';
    if (!confirm(`Close Option Portfolio?${warn}`)) return;
    await api('POST', '/api/shutdown');
  } catch (e) { toast(e.message); return; }
  document.body.innerHTML = '<div class="closed-msg"><h1>Option Portfolio is closed</h1><p class="muted">You can close this window.</p></div>';
  setTimeout(() => window.close(), 300);
});

async function checkVersion() {
  try {
    const v = await api('GET', '/api/version');
    if (v.outdated && !document.getElementById('restart-note')) {
      document.querySelector('.side-bottom').insertAdjacentHTML('beforebegin',
        '<p id="restart-note" class="restart-note">The app was updated. Click Quit and start it again to use the new version.</p>');
    }
  } catch { /* the app may be closing */ }
}
setInterval(checkVersion, 60000);

// ---- router ------------------------------------------------------------------------

function route() {
  const m = location.hash.match(/^#\/position\/(\d+)/);
  const nav = location.hash.startsWith('#/settings') ? 'settings' : 'portfolio';
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === nav));
  if (m) renderPosition(Number(m[1]));
  else if (nav === 'settings') renderSettings();
  else renderPortfolio();
}
window.addEventListener('hashchange', route);
pollTws();
checkVersion();
route();
