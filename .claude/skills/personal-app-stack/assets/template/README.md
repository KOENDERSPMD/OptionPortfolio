# __TITLE__

A personal web app with a Python backend. It runs on your own computer (it opens in its own
window) or on a headless server that you reach through an SSH tunnel.

## What it does

- (Describe each screen and feature here, in plain language, as it is built.)

## Setup (Linux)

Requires Python 3.10 or newer, and preferably Chrome or Chromium, so the app opens in its own window.

```bash
git clone git@github.com:<you>/<repo>.git __pkg__
cd __pkg__
./start.sh
```

The first run creates a Python environment in `.venv` and installs the dependencies. After that,
`./start.sh` starts the app and opens it. To close the app, click **⏻ Quit** at the bottom of the
sidebar (or press Ctrl+C in the terminal). Quit warns first when work is still running.

To start it from your applications menu, create `~/.local/share/applications/__pkg__.desktop`
(replace the path):

```ini
[Desktop Entry]
Type=Application
Name=__TITLE__
Exec=/home/YOU/__pkg__/start.sh
Terminal=true
```

### Configuration

| Environment variable   | Default            | Purpose                                                       |
|------------------------|--------------------|---------------------------------------------------------------|
| `__ENV___PORT`         | `__PORT__`         | Port of the server                                            |
| `__ENV___HOST`         | `127.0.0.1`        | Address the server listens on (only this computer by default) |
| `__ENV___DB`           | `data/__pkg__.db`  | Database file (SQLite)                                        |
| `__ENV___NO_BROWSER`   |                    | Set to `1` to start without opening a window                  |

**Backup:** copy the `data/` folder while the app is stopped.

### When it doesn't start

- Run `./start.sh` from a terminal. When start-up fails, it prints the error and keeps the window open.
- Everything the server prints is also written to **`data/__pkg__.log`**.
- *"Port … is already in use"*: another program uses the port. Start on another one:
  `__ENV___PORT=<other port> ./start.sh`.

## Running on a headless server

1. Clone and run `./start.sh` once on the server (creates `.venv`), then stop it.
2. Edit `deploy/__pkg__.service` (user and path) and follow the steps at the top of that file.
   Without systemd: `__ENV___NO_BROWSER=1 ./start.sh` inside `tmux`.
3. Keep it on 127.0.0.1 (the default) and connect from your own computer with an SSH tunnel:

   ```bash
   ssh -N -L __PORT__:127.0.0.1:__PORT__ you@your-server
   ```

   then open <http://127.0.0.1:__PORT__/>. The app has **no login**: never set
   `__ENV___HOST=0.0.0.0` on a machine reachable from the internet.
4. **⏻ Quit** stops the service (systemd does not restart it after a clean exit); start it again
   with `sudo systemctl start __pkg__`.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

- `__pkg__/main.py`: the API (FastAPI) and the start-up/shut-down of background work.
- `__pkg__/db.py`: the SQLite schema and migrations (columns are only ever added).
- `__pkg__/settings.py`: settings stored in the database; secrets never go to the browser.
- `__pkg__/web/`: the browser UI, plain JavaScript and CSS without a build step.
- `tests/`: pytest; each test gets its own database file.
