# Frontend

Contents: Page structure · Routing and rendering · Talking to the API · Look and feel ·
Formatting · Charts · Interaction details · Narrow screens

## Page structure

- `index.html` is a fixed shell: a **sidebar** (app name, `+ New`, search and filter, the list of
  records, connection dots, ⚙ Settings and ⏻ Quit at the bottom) and a `<main id="main">` that the
  router fills. Dialogs (`<dialog>`) for New, Dismiss etc. live in the shell.
- A record's page has a header (number, name, the main fields such as status, a pull-down like
  conviction, created date, the final action on the right) and **tabs** when there is more than one
  area (the trading app: Trade Idea · Timing · Structure · Management). Tabs are buttons that switch
  `state.tab` and re-render; the chosen tab stays selected when the owner switches to another record.
- Each larger tab gets its own JS file (`timing.js`, …) exposing a `render<Tab>(record)` function;
  load them before `app.js`. No modules, no bundler: plain `<script>` tags in a fixed order and
  `'use strict'` at the top of each file.
- Layout for content: cards (`.card`) in a grid; tables in a `.table-wrap` that scrolls
  horizontally rather than squeezing. Keep wide tables from taking the whole width when other
  blocks need room (the owner asked for at least half the screen for the AI answer blocks).

## Routing and rendering

- Hash routes: `#/`, `#/item/12`, `#/settings`, `#/alerts`. A `route()` function reads
  `location.hash`, renders, and re-renders the sidebar to highlight the active record. Links are
  plain `<a href="#/...">`, so back/forward and bookmarks work.
- Render by building an HTML string with template literals and assigning `innerHTML`, then attach
  listeners. **Every** value from the server goes through `esc()`. Server-rendered Markdown is the
  only exception, and it is rendered with raw HTML disabled.
- After an async load, check the element is still in the page before writing to it (the owner may
  have navigated away): `if (!document.body.contains(el)) return;`.
- Small UI preferences (the list filter, a collapsed panel) go in `localStorage`, wrapped in
  try/catch. Data never goes in `localStorage`.

## Talking to the API

- One `api(method, path, body)` helper that sends JSON, returns parsed JSON (or `null` for 204) and
  throws an `Error` with the server's `detail`. Show errors with a toast or inline next to the form.
- Polling (running jobs, status dots): `setTimeout` chains, not `setInterval`, and stop them when
  the page changes (`stopPolling()` in the router). Job polls every 2–4 s; status every 15 s.
- After a successful change, show a short toast ("Saved") and re-render the affected part.

## Look and feel

- Colours are CSS custom properties on `:root`; components only use `var(--…)`. Dark mode is one
  `@media (prefers-color-scheme: dark)` block overriding the same tokens, and `color-scheme` is set
  so form controls follow. Check both modes on every screen.
- Tokens used across apps: `--bg --surface --surface-2 --surface-3 --border --text --muted --accent
  --accent-soft --on-accent --gain --loss`, status colours `--st-<status>`, connection colours
  `--conn-on` (green) / `--conn-off` (red), `--est-bg` for estimates. They are all in the template's
  `styles.css`, together with tabs, tables (`.table-wrap`, `td.num`, `tr.est`), `.gain`/`.loss` and
  the connection dot; the trading app's `tims/web/styles.css` has more components (chips, payoff
  charts, diff colours) to copy when needed.
- System font stack, 14px base, `font-variant-numeric: tabular-nums` for numbers in tables.
- Status dots: 9px circles coloured by `--st-<status>`; the label is in the `title` and in the
  pull-down, so colour is never the only signal.
- Estimates, forecasts or provisional values get a tinted background and an *est.* label.

## Formatting

These helpers are at the top of the template's `app.js`; use them everywhere:

- `fmtDate` → **dd-mm-yyyy**; `fmtDateTime` → dd-mm-yyyy HH:MM in local time.
- `fmtNum(v, 2)` → 2 decimals with thousands separators (prices, amounts, EPS, strikes); ratios
  may use 1; per-unit amounts below a cent (dividend per share) up to 4. Missing or non-finite
  values → `—`.
- Date **inputs** use `<input type="date">`: its value is always `YYYY-MM-DD`, which the API
  expects, and the browser shows it in the computer's regional format (dd-mm-yyyy on the owner's
  system). Don't build custom date pickers.
- `fmtPct(v)` → `+12.3%` with an explicit sign; colour gains/losses with `.gain` / `.loss`.
- Record numbers `#0012` come from the server.

## Charts

- Price/time-series charts: TradingView **Lightweight Charts**, vendored
  (`vendor/lightweight-charts-4.2.3.js`). Set `localization: { locale: 'en-GB' }` (some Linux locales
  such as `en-US@posix` make it throw) and clear the container before re-creating a chart. Leave
  ~10% empty space on the right by default (`setVisibleLogicalRange` past the last bar). Volume goes
  in its own pane under the price, not on a second y-axis.
- Small charts (a handful of points): inline SVG built in JS, sized with `viewBox` and
  `width: 100%`. Use the `dataviz` skill for colours, marks and labels: 2px lines, ≥8px markers,
  a legend for two or more series, values as text in the text colour, a `<title>` on each point
  for hover, and colour tokens for light and dark validated with its script.
- One measure per axis. Two measures with different scales get two small charts side by side.

## Interaction details

- Final actions (Dismiss, Delete) use a dialog or `confirm()` that says it is final; a dismiss
  asks for a reason from an editable list plus an optional note.
- Clicking on a chart can add something (a support/resistance level at the clicked price); always
  offer a typed alternative too.
- Lists of up to a few items the owner picks from (expiries, structures) are chips or check boxes,
  limited to the agreed maximum, with the reason shown when the limit is reached.
- Quit: ask `/api/busy` first and include what is still running in the confirmation, then post
  `/api/shutdown` and replace the page with "<App> is closed".

## Narrow screens

At ≤760px the sidebar stacks above the content and the list gets a max height; tables scroll
horizontally inside their wrapper. The owner mainly uses a desktop, but check a 390px-wide
screenshot so nothing overlaps.
