# Testing

Contents: Setup · What to test · Fakes for external services · Checking the UI in a browser

## Setup

- `requirements-dev.txt` adds `pytest` and `httpx` (for `TestClient`); run with
  `.venv/bin/python -m pytest -q`.
- `pytest.ini` sets `testpaths = tests` and `pythonpath = .`.
- `tests/conftest.py` (in the template) gives two fixtures:
  - `conn`: a fresh database file under `tmp_path`, with `<ENV>_DB` pointing at it so the app's own
    connections use it, `<ENV>_NO_BACKGROUND=1` so no threads or clients start, and secrets removed
    from the environment.
  - `client`: a `TestClient(app)` used as a context manager, so the lifespan runs.
- Build test data in code (helpers in `conftest.py`), including spreadsheets for import tests
  (write a small `.xlsx` with `openpyxl` in the same layout as the owner's real file). Don't depend
  on the owner's large files.

## What to test

- Every calculation the owner relies on, with hand-checkable numbers and a comment showing the
  arithmetic (`# TTM = 1.5 + 1.65 + 1.8 + 1.95`). When a test and the code disagree, recompute by hand
  before deciding which one is wrong.
- API behaviour: create/update/list/filter, validation errors (422/400), 404s, final states that
  cannot be changed, secrets not appearing in any response.
- Migrations: an old-style table gets the new columns and keeps its rows.
- Schedulers: call `tick(now=...)` with fixed times (before/after the close, weekends) instead of
  waiting.
- Don't call `/api/shutdown` in tests; it would stop the test process.

## Fakes for external services

- Each external client is replaceable (`set_client(fake)`); reset it after the test.
- Fakes are small classes with the same methods and canned data: `status()`, `bars(...)`,
  `option_quotes(...)`, `executions()`… plus a `connected` flag to test the "service down" paths
  (503, retry later). Record calls on the fake (`self.requested.append(...)`) to assert what was asked.
- For the Claude API, fake the client object so no network call or cost happens; test prompt
  rendering, storing the run, cost calculation and the diff separately.

## Checking the UI in a browser

Tests don't show layout problems. Before reporting a screen as done:

1. Start the app against a scratch database with demo data (a small `demo_server.py` that sets a
   simulated external client and runs uvicorn is handy, so screens with live data can be shown
   without the owner's accounts).
2. Take screenshots with `node scripts/shoot.mjs http://127.0.0.1:<port> <out-dir> "#/" "#/item/1"`:
   each route at 1440×1000 in light and dark and at 390px wide, with browser errors listed (exit
   code 1 when there are any). It needs Playwright: in Claude Code cloud sessions it is installed
   globally with Chromium; locally run `npm i -g playwright && npx playwright install chromium`.
   For flows (fill a form, click a tab) write a short Playwright script along the same lines.
   Use a free port and a scratch database (`<ENV>_DB=...`), never the owner's data.
3. Look at every screenshot. Typical finds: labels clipped at the right edge of an SVG, overlapping
   end labels, inputs overflowing a grid cell (`min-width: 0`), charts without right-hand space.
4. Fix, re-shoot, and only then commit. Mention in the reply what could not be checked (real
   accounts, market hours).
