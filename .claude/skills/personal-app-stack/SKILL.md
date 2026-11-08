---
name: personal-app-stack
description: House architecture for the owner's personal apps — a GitHub repo with a Python (FastAPI) backend, a SQLite database and a vanilla-JS web UI without a build step, started with ./start.sh on the owner's Linux computer or run as a systemd service on a headless server reached through an SSH tunnel. Use this skill whenever the user wants to start, plan, scaffold or extend one of their own applications or tools ("I want an app for…", "new application", "build me a tool to manage/track…", "add a tab/screen/setting to my app", "run it on my server"), even if they don't mention the stack, so every app shares the same design, conventions and deployment as the Trade Idea Management System.
---

# Personal app stack

The owner builds personal, single-user tools (the first one is the *Trade Idea Management System*,
in the repo this skill came from). They want every new app to look and work the same way, so what
they learn in one carries over to the next. This skill is that shared design: the stack, the
project layout, the conventions, and the way of working that has suited the owner.

## How to work with the owner

These come from how the first app was built; they matter more than any code choice.

- **Ask before generating.** The owner has their own system for each domain and was unhappy when a
  generic app was produced from a one-line request. Start with an outline (screens, main objects,
  what is out of scope), then ask numbered questions; the owner answers by number ("1 yes, 2 daily,
  rest is fine, go"). Build one screen or tab at a time (a list with its detail page counts as one),
  and ask again before the next. "Okay" or "go" means: build it with the defaults you proposed; don't
  confirm the outline again.
- **Propose, don't survey.** Each question gets a recommended default, so "okay" is a valid answer.
- **Plain language.** The owner is an expert in their domain, not necessarily in software. Explain
  technical choices in a sentence, in the README as well as in chat.
- **Keep the owner in charge of state changes.** Statuses, links between records and other
  judgement calls are set by hand; the app proposes and asks for confirmation instead of deciding.
- **External accounts are read-only** unless the owner explicitly asks otherwise (the trading app
  reads from the broker but never places orders). Secrets stay on the server; the owner never pastes
  them into chat.
- **Git:** work on the branch you were given, commit and push after each finished step, and don't
  open a pull request unless asked. Update the README in the same commit as the feature.

## The stack (and why)

| Part | Choice | Why |
|---|---|---|
| Backend | Python 3.10+, FastAPI, uvicorn | Readable, good libraries for data, finance and AI; FastAPI validates input and documents the API itself. |
| Database | SQLite, one file in `data/`, WAL mode, plain SQL (`sqlite3`) | No server to install or secure; backup is copying a folder; fast enough for one user. No ORM: the schema stays visible in one place. |
| UI | One HTML page, plain JS and CSS, served by FastAPI | No Node, no build step, nothing to break on update. Opens as its own window via Chrome `--app`. |
| Libraries in the browser | Vendored files with the version in the name | Works offline; never changes unexpectedly. |
| Start | `./start.sh` | Creates `.venv`, installs packages when `requirements.txt` changes, checks the port, logs to `data/<pkg>.log`, opens the window. |
| Server | systemd unit in `deploy/`, bound to 127.0.0.1, SSH tunnel | The apps have no login; the tunnel is the access control. |
| Tests | pytest + FastAPI TestClient, a fresh database file per test, fakes for external services | Fast, and runnable without accounts or network. |

Don't swap parts of the stack on your own initiative. If an app seems to need something else
(several users, a heavy front-end, MySQL), say why and let the owner decide.

## Starting a new app

1. Agree the outline and answer the first round of questions (see above).
   "Same setup as my other app" means this stack and these conventions. Whether the new app also
   needs an account or service the other app uses (e.g. the broker connection) is a question to ask.
2. Create the repo: the owner makes an empty GitHub repository (or you do, if you have access) and
   you work in its clone. Without a repo yet, `git init` in the target folder and push once it exists.
3. Pick a **package name** (short, lower case, e.g. `budget`), a **title** for the UI and a **port**
   no other app of the owner's uses. Port register (add each new app here, in this skill, so the
   next one avoids it):

   | Port | App |
   |---|---|
   | 8765 | Trade Idea Management System |
   | 8771 | Option Portfolio |

   New apps start at 8770.
4. Scaffold from the template (run from the skill folder; the target is the new repo's clone):

   ```bash
   python3 scripts/new_app.py ~/code/budget --package budget --title "Budget" --port 8770
   ```

   This copies `assets/template/` (a small working app: an item list with search and a status filter,
   a detail view, Settings with a secret key, Quit, tests) and fills in the names. The example "items"
   are there to show the patterns; rename or replace them with the real objects. The Settings card
   with a secret key shows how secrets are handled: keep the mechanism, drop the card if the app
   has no secret.
5. Create the environment and run the tests before changing anything, so you know the base works
   (the script prints the commands: `python3 -m venv .venv`, install `requirements-dev.txt`,
   `pytest`). Start it with `./start.sh`, or `<ENV>_NO_BROWSER=1 ./start.sh` where there is no screen.
6. Build the first screen the owner asked for, following the references below.

**Reusing code from another app** (a broker client, the Claude runner): copy the module into the
new app and adapt it. Each app stays self-contained and can be changed without breaking the others.
Only propose a shared package when the same module is copied into a third app.

When the owner wants a feature added to an existing app built this way, read that app's README and
`main.py` first; follow what is there, even where it differs slightly from this skill.

## Project layout

```
<repo>/
├── start.sh                 # start locally (creates .venv, logs, opens window)
├── requirements.txt         # runtime packages; requirements-dev.txt adds pytest + httpx
├── pytest.ini
├── README.md                # for the owner: what it does, setup, config, headless, troubleshooting
├── deploy/<pkg>.service     # systemd unit for a headless server
├── data/                    # git-ignored: <pkg>.db, <pkg>.log
├── <pkg>/
│   ├── main.py              # FastAPI app: lifespan, /api routes, static UI, run()
│   ├── db.py                # SCHEMA, migrate(), connect(), now_iso()
│   ├── settings.py          # DEFAULTS, load/update/public (secrets never to the browser)
│   ├── <domain>.py          # one module per area of logic, plain functions taking `conn`
│   └── web/
│       ├── index.html       # shell: sidebar, <main>, dialogs, script tags
│       ├── app.js           # helpers, sidebar, router, settings, quit
│       ├── <tab>.js         # one file per larger tab, loaded before app.js
│       ├── styles.css       # colour tokens, light + dark
│       └── vendor/          # third-party JS with version in the file name
└── tests/
    ├── conftest.py          # conn + client fixtures (temp DB, no background work)
    └── test_<area>.py
```

Keep logic out of `main.py`: routes validate input, call a domain module, and shape the response.
Domain modules take a `conn` and plain values, which makes them easy to test without HTTP.

## Conventions in short

- Environment variables share one prefix: `<ENV>_PORT`, `<ENV>_HOST` (default 127.0.0.1),
  `<ENV>_DB`, `<ENV>_NO_BROWSER`, plus `<ENV>_NO_BACKGROUND` for tests.
- Records get human numbers: `#0012`, and child records `#0012-01`.
- Timestamps are stored as UTC ISO strings ending in `Z`; the browser shows local time.
- Dates are shown as **dd-mm-yyyy**, times as 24-hour `HH:MM`, money and prices with 2 decimals
  (per-unit amounts such as a dividend per share may need up to 4), missing values as `—`.
- Every user-facing error is a full sentence that says what to do ("Nothing answers on port 7496.
  Is TWS running…?"), sent as FastAPI's `detail` and shown by the UI as is.
- Statuses have a coloured dot in the list; inactive records sit behind a filter, not deleted.
- Final or destructive actions ask for confirmation, and a reason where it matters later.
- Long work (imports, external calls, AI runs) runs in a background thread with a row in a jobs
  table that the UI polls; Quit warns when something is still running.

## Reference files

Read the one that matches what you are about to build:

- `references/backend.md` — API design, database and migrations, settings and secrets, background
  jobs and schedulers, clients for external services, using the Claude API, file imports.
- `references/frontend.md` — page structure, routing, rendering and escaping, polling, colour
  tokens and dark mode, formatting, charts, dialogs, narrow screens.
- `references/deploy.md` — GitHub, `start.sh`, desktop entry, logs, ports, headless server with
  systemd and an SSH tunnel, updates and backups.
- `references/testing.md` — fixtures, fakes for external services, what to test, and checking the
  UI in a real browser (light, dark, narrow) before reporting a screen as done.

Scripts: `scripts/new_app.py` (create an app from the template), `scripts/shoot.mjs` (screenshots
of a running app in light, dark and narrow, with browser errors).

## Before you call a step done

- Tests pass (`.venv/bin/python -m pytest -q`), including new tests for the new logic.
- You opened the changed screens in a browser (light and dark, and a narrow width), looked at the
  screenshots, and the console had no errors.
- The README describes the new feature in the owner's words, and any new setting or env variable.
- Old databases still open: a column added to an existing table is in both `CREATE TABLE` and
  `migrate()`, with a test that upgrades an old-style table. (A brand-new app has nothing to migrate
  yet; the template's test shows the pattern for later.)
- Committed and pushed to the agreed branch; your reply says what changed, what you could not test
  (e.g. needs the owner's account or market hours), and what the next question is.
