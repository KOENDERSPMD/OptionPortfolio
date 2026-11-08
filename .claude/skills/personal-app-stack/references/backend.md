# Backend

Contents: API design · Database · Migrations · Settings and secrets · Background work ·
External services · Using the Claude API · File imports · Quit

## API design

- Everything the UI needs is JSON under `/api/...`; the UI is served from `/` and `/static`.
- Use pydantic models for request bodies, with `Field` limits (`min_length`, `ge`, `le`) and
  `Literal[...]` for fixed choices, so bad input gets a 422 without extra code.
- For partial updates use `PATCH` with optional fields and `model_dump(exclude_unset=True)`, so a
  field that was not sent is left alone and an explicit `null` clears a nullable field (the
  template's `priority`). Reject `null` for required fields with a 400. (The trading app uses
  `conviction: 0` for "clear"; new apps use `null`.)
- Raise `HTTPException(status, "Sentence for the owner.")`. 400 for a rule broken, 404 for a missing
  record (name it: "Idea #0012 not found"), 409 when something is already running, 503 when an
  external service is unreachable. The UI shows `detail` verbatim, so write it for the owner.
- Return the full updated object from create/update calls, so the UI can re-render without a
  second request. Add derived fields (like `number: "#0012"`) in one `*_dict()` helper.
- One connection per request through the `get_conn` dependency. Background threads open their own
  connection with `db.closing(db.connect())`.

## Database

- SQLite in WAL mode with `foreign_keys = ON` and `synchronous = NORMAL` (see template `db.py`).
  WAL lets web requests read while a background job writes. `timeout=30` covers short write waits.
- The whole schema is one `SCHEMA` string of `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
  EXISTS` statements in `db.py`, run on every start by `init()`.
- Plain SQL with `?` parameters, never string formatting of values. `row_factory = sqlite3.Row`
  so rows convert with `dict(row)`.
- Timestamps: `now_iso()` (UTC, `...Z`). Plain dates as `YYYY-MM-DD` text.
- Money: store amounts as REAL rounded to cents (or INTEGER cents where sums must be exact), and
  round with `Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)`; Python's `round()` uses
  banker's rounding and float artefacts (`round(2.675, 2) == 2.67`).
- Structured data that is always read and written as a whole (a list of option legs, a review
  form) can be a `*_json` TEXT column. Data you filter or join on gets real columns.
- Keep history instead of overwriting when the owner may want to look back (every Claude answer is
  kept as a row, with a diff view between runs; price bars and imports are kept with timestamps).
- Imports must be idempotent: unique keys plus `INSERT ... ON CONFLICT DO NOTHING/UPDATE`, so
  re-importing an overlapping file creates no duplicates.
- Index the columns used in `WHERE` for lists that grow (ticker, foreign keys).

## Migrations

The owner's database holds months of work, and they update with `git pull` and a restart. So:

- New tables: just add them to `SCHEMA`.
- New columns in an existing table: add them to the `CREATE TABLE` (for new databases) **and** to
  `migrate()` with `ALTER TABLE ... ADD COLUMN` after checking `PRAGMA table_info` (for existing
  ones). The template's `items.priority` is an example of both.
- Never drop or rename a column that holds data. If a value was stored wrongly, add the corrected
  column and fill it on the next import, and say so in a comment.
- In `init()`, mark jobs left `running` by a previous process as interrupted.
- Write a test that builds an old-style table, runs `db.init()`, and checks the data survived.

## Settings and secrets

- `settings.py` holds `DEFAULTS`; only changed values are stored (key -> JSON) in `settings`.
  `load()` merges, `update()` validates (raise `SettingsError` with a sentence), `public()` returns
  what the browser may see.
- Secrets (API keys, passwords) are stored in the database and **never returned** to the browser:
  `public()` replaces them with `<key>_set` and a hint of the last 4 characters. An environment
  variable can supply the same secret on a server (`<ENV>_API_KEY`, or the library's own, such as
  `ANTHROPIC_API_KEY`).
- The settings page groups related settings in separate cards (e.g. "Option valuation" apart from
  the broker connection), each with its own Save button and a one-line explanation.

## Background work

- **One-off jobs** (an import, refreshing many records): insert a `jobs` row with status
  `running`, start a `threading.Thread(daemon=True, name=...)` that opens its own connection and
  updates the row with progress and the result; return 202 with the row. The UI polls the job. Use
  a 409 when the same kind of job is already running.
- **Parallel calls** (several AI prompts): a module-level `ThreadPoolExecutor(max_workers=3)`.
- **Schedules** (a check after the market close, every N minutes): one scheduler object with a
  `start()` that runs a loop thread and a `tick(now=None)` that does one round. The loop only calls
  `tick()`, catches and logs every exception so the thread survives, and waits with
  `threading.Event().wait(seconds)`. Store "last done" markers in the database so a missed run
  happens as soon as possible after a restart, and nothing runs twice. Tests call `tick()` directly
  with a fixed `now`.
- Start threads and clients in the FastAPI `lifespan`, skipped when `<ENV>_NO_BACKGROUND=1`, and
  stop or disconnect them after the `yield`.
- `busy()` lists running work so Quit can warn.

## External services (brokers, data feeds)

Pattern from the IBKR client in the trading app:

- One client object per service in its own module, created once (`client()`), replaceable in tests
  (`set_client(fake)`).
- If the library is asyncio-based, run it in its own thread with its own event loop and call into
  it with `asyncio.run_coroutine_threadsafe(...).result(timeout)` from a `call()` helper. Web
  requests stay synchronous and simple.
- The client reconnects quietly every 30 seconds while the service is down and exposes `status()`
  (`connected`, `host`, `port`, `error`, `last_attempt`). The UI shows it as a green/red dot in the
  sidebar, linked to its settings card, polled every 15 seconds.
- Raise one exception type (`TWSError`) with sentences that explain the likely cause and fix; the
  route turns it into a 503.
- Connect read-only where the service supports it, and say so in Settings and the README.
- Cache what you fetch in the database (with an `updated_at`) and refresh when older than a day or
  when the owner clicks Refresh, so the app stays usable when the service is down.

## Using the Claude API

- Runs happen **only when the owner clicks**, never automatically, because each costs money.
- Model and effort are chosen in Settings from a list with plain labels ("recommended", "cheaper");
  the default is the current most capable general model. Check the `claude-api` skill for current
  model IDs, prices and tool versions rather than relying on memory.
- Prompts the owner edits live in Settings, with `{placeholders}` filled per record and a list of
  the available placeholders shown next to the editor.
- Store every run: prompt sent, answer (Markdown), sources, model, tokens, cost, start and end time,
  status and error. Show the time of the last run and its cost, allow opening earlier runs, and
  offer a word-level diff against the previous one.
- Render Markdown on the server with `markdown-it-py` with raw HTML disabled.
- Web research uses the server-side web search tool; the system prompt says to rely on what it
  finds and to say when something can't be found.

## File imports

- Upload with `UploadFile`, check the extension, copy to a temp file, start a job thread, delete
  the temp file in `finally`.
- Stream large spreadsheets (`openpyxl` `read_only=True`), commit in batches, and update the job's
  progress message.
- Report what was skipped and why (duplicates, junk rows) in the job result.

## Quit

`POST /api/shutdown` only from 127.0.0.1/::1 (an SSH tunnel arrives as local), then
`threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGINT))`, so the response gets out and
uvicorn shuts down cleanly (exit code 0, so systemd does not restart it). The lifespan's code after
`yield` disconnects external services.
