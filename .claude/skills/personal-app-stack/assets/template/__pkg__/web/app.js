'use strict';
// __TITLE__ — browser UI (vanilla JS, no build step). Hash routes: #/, #/item/<id>, #/settings.

const main = document.getElementById('main');
const state = { itemId: null, tab: 'notes' };  // the tab stays selected when switching records
const TABS = [['notes', 'Notes'], ['details', 'Details']];

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
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join('; ');
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
function fmtNum(v, dp = 2) {
  if (v == null || !Number.isFinite(v)) return dash;
  return v.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/** +12.3% with an explicit sign; colour it with signClass(). */
function fmtPct(v) {
  if (v == null || !Number.isFinite(v)) return dash;
  const p = v * 100;
  return `${p > 0 ? '+' : ''}${p.toFixed(Math.abs(p) >= 100 ? 0 : 1)}%`;
}
const signClass = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '');

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 2600);
}

document.querySelectorAll('dialog [data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));

// ---- sidebar ---------------------------------------------------------------

const searchEl = document.getElementById('item-search');
const showEl = document.getElementById('item-show');
try { showEl.value = localStorage.getItem('__pkg__.show') || 'open'; } catch { /* storage unavailable */ }

async function renderSidebar() {
  const list = document.getElementById('item-list');
  let items;
  try {
    items = await api('GET', `/api/items?${new URLSearchParams({ show: showEl.value, q: searchEl.value.trim() })}`);
  } catch (e) {
    list.innerHTML = `<div class="list-empty">Could not load items: ${esc(e.message)}</div>`;
    return;
  }
  list.innerHTML = items.length ? items.map((i) => `
    <a class="item ${i.id === state.itemId ? 'active' : ''}" href="#/item/${i.id}">
      <span class="dot ${i.status}"></span><span class="num-id">${i.number}</span><span class="name">${esc(i.name)}</span>
    </a>`).join('') : '<div class="list-empty">Nothing here yet.</div>';
}
searchEl.addEventListener('input', () => { clearTimeout(searchEl.t); searchEl.t = setTimeout(renderSidebar, 200); });
showEl.addEventListener('change', () => {
  try { localStorage.setItem('__pkg__.show', showEl.value); } catch { /* ignore */ }
  renderSidebar();
});

// ---- new item ----------------------------------------------------------------

const dlgNew = document.getElementById('dlg-new');
const formNew = document.getElementById('form-new');
document.getElementById('new-item').addEventListener('click', () => {
  formNew.reset();
  formNew.querySelector('.form-error').hidden = true;
  dlgNew.showModal();
});
formNew.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  try {
    const item = await api('POST', '/api/items', { name: formNew.name.value });
    dlgNew.close();
    location.hash = `#/item/${item.id}`;
  } catch (e) {
    const err = formNew.querySelector('.form-error');
    err.textContent = e.message;
    err.hidden = false;
  }
});

// ---- item view -----------------------------------------------------------------

async function renderItem(id) {
  let item;
  try { item = await api('GET', `/api/items/${id}`); } catch (e) {
    main.innerHTML = `<div class="page"><p class="muted">${esc(e.message)}</p></div>`;
    return;
  }
  main.innerHTML = `<div class="page">
    <header class="page-head">
      <h1><span class="muted">${item.number}</span> ${esc(item.name)}</h1>
      <select id="status" aria-label="Status">
        ${['open', 'done'].map((s) => `<option value="${s}" ${s === item.status ? 'selected' : ''}>${s === 'open' ? 'Open' : 'Done'}</option>`).join('')}
      </select>
      <span class="muted small">Created ${fmtDate(item.created_at)}</span>
      <button class="btn danger" id="delete">Delete</button>
    </header>
    <nav class="tabs">${TABS.map(([k, l]) => `<button class="tab ${k === state.tab ? 'active' : ''}" data-tab="${k}">${l}</button>`).join('')}</nav>
    <div id="tab-body"></div>
  </div>`;
  main.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => { state.tab = b.dataset.tab; renderItem(id); }));
  const body = document.getElementById('tab-body');
  if (state.tab === 'details') {
    // Larger tabs get their own file (details.js with renderDetails(item)), loaded before app.js.
    body.innerHTML = `<section class="card"><h2>Details</h2><div class="table-wrap"><table><tbody>
      <tr><th>Number</th><td>${item.number}</td></tr>
      <tr><th>Status</th><td><span class="dot ${item.status}" style="display:inline-block"></span> ${item.status === 'open' ? 'Open' : 'Done'}</td></tr>
      <tr><th>Priority</th><td>${item.priority ?? dash}</td></tr>
      <tr><th>Created</th><td>${fmtDateTime(item.created_at)}</td></tr>
      <tr><th>Last change</th><td>${fmtDateTime(item.updated_at)}</td></tr>
    </tbody></table></div></section>`;
  } else {
    body.innerHTML = `<section class="card">
      <h2>Notes</h2>
      <textarea id="notes" rows="8">${esc(item.notes)}</textarea>
      <div class="card-foot"><span class="muted small">Last change ${fmtDateTime(item.updated_at)}</span>
        <button class="btn primary" id="save-notes">Save</button></div>
    </section>`;
    document.getElementById('save-notes').addEventListener('click', () => patch({ notes: document.getElementById('notes').value }, 'Saved'));
  }
  const patch = async (body, msg) => {
    try { await api('PATCH', `/api/items/${id}`, body); toast(msg); renderSidebar(); } catch (e) { toast(e.message); }
  };
  document.getElementById('status').addEventListener('change', (e) => patch({ status: e.target.value }, 'Status changed'));
  document.getElementById('delete').addEventListener('click', async () => {
    if (!confirm(`Delete ${item.number}? This cannot be undone.`)) return;
    await api('DELETE', `/api/items/${id}`);
    location.hash = '#/';
  });
}

// ---- settings --------------------------------------------------------------------

async function renderSettings() {
  const s = await api('GET', '/api/settings');
  main.innerHTML = `<div class="page"><h1>Settings</h1>
    <section class="card">
      <h2>API key</h2>
      <label class="field">Key <input type="password" id="api-key" autocomplete="off"
        placeholder="${s.api_key_set ? `Set (${esc(s.api_key_hint)}); type to replace` : 'Not set'}"></label>
      <p class="hint">Stored only in this app's local database; it is never sent back to the browser.</p>
      <div class="card-foot"><span></span><button class="btn primary" id="save-key">Save</button></div>
    </section>
  </div>`;
  document.getElementById('save-key').addEventListener('click', async () => {
    const v = document.getElementById('api-key').value.trim();
    if (!v) return;
    try { await api('PUT', '/api/settings', { api_key: v }); toast('Key saved'); renderSettings(); } catch (e) { toast(e.message); }
  });
}

// ---- quit --------------------------------------------------------------------------

document.getElementById('quit').addEventListener('click', async () => {
  try {
    const { busy } = await api('GET', '/api/busy');
    const warn = busy.length ? `\n\nStill busy: ${busy.join(', ')}. Closing now stops that work.` : '';
    if (!confirm(`Close __TITLE__?${warn}`)) return;
    await api('POST', '/api/shutdown');
  } catch (e) { toast(e.message); return; }
  document.body.innerHTML = '<div class="closed-msg"><h1>__TITLE__ is closed</h1><p class="muted">You can close this window.</p></div>';
  setTimeout(() => window.close(), 300);
});

// ---- router ------------------------------------------------------------------------

function route() {
  const m = location.hash.match(/^#\/item\/(\d+)/);
  state.itemId = m ? Number(m[1]) : null;
  if (m) renderItem(state.itemId);
  else if (location.hash.startsWith('#/settings')) renderSettings();
  else main.innerHTML = '<div class="page empty"><p class="muted">Choose an item on the left, or click + New.</p></div>';
  renderSidebar();
}
window.addEventListener('hashchange', route);
route();
