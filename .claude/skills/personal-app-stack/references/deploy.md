# Running and deploying

Contents: GitHub · Local start · Logs and troubleshooting · Ports · Headless server ·
External desktop programs on a server · Updates and backups

## GitHub

- One repository per app. The owner clones with SSH:
  `git clone git@github.com:<owner>/<repo>.git <folder>`. When work lives on a branch, tell them to
  clone or check out that branch (`git clone -b <branch> ...` or `git fetch && git checkout <branch>`);
  the default branch may not have it yet. This tripped the owner up once.
- `.gitignore` keeps `data/`, `.venv/`, `*.db*`, caches out of git. Sample input files the owner
  provides may be committed if small; large ones (GitHub's 100 MB limit) are imported locally
  through the app instead.
- Never commit secrets, the database, or logs.

## Local start (`start.sh`)

The template's `start.sh` does, in order:

1. Creates `.venv` on the first run (and tells the owner to `sudo apt install python3-venv` if that fails).
2. Re-installs packages only when the hash of `requirements.txt` changed.
3. If the app already answers on its port (`/api/health` returns this app's name), just opens it.
4. If some *other* program holds the port, stops with a message naming the fix
   (`<ENV>_PORT=<n> ./start.sh`), instead of failing obscurely.
5. Starts the server in the background, appends its output to `data/<pkg>.log`, waits for
   `/api/health` (max 15 s), and shows the last log lines if start-up fails.
6. Opens Chrome/Chromium with `--app=<url>` (its own window), else `xdg-open`, unless
   `<ENV>_NO_BROWSER=1`.
7. Keeps the terminal open on errors, so a start from the applications menu doesn't vanish.

A `.desktop` file in `~/.local/share/applications/` with `Terminal=true` puts the app in the menu
(the README template has it).

## Logs and troubleshooting

- Everything goes to `data/<pkg>.log`; the README has a "When it doesn't start" section listing
  the messages the owner may see and what to do.
- When the owner reports "it doesn't start", ask for the last lines of that log first.
- When killing a stray server in your own shell, don't `pkill -f` a pattern that also matches your
  shell's command line; loop over `pgrep` results and skip `$$`.

## Ports

Each app has its own default port, documented in its README and in the port register in SKILL.md
(add new apps there). New apps
start at 8770 and go up. Default host is always 127.0.0.1.

## Headless server

The app is a web server, so it runs without a screen:

1. Clone on the server, run `./start.sh` once to build `.venv` (with `<ENV>_NO_BROWSER=1`), stop it,
   and copy the `data/` folder over if there is an existing database.
2. Install `deploy/<pkg>.service` (user and paths filled in): `Environment=<ENV>_HOST=127.0.0.1`,
   `ExecStart=<repo>/.venv/bin/python -u -m <pkg>.main`, `Restart=on-failure` (Quit exits cleanly,
   so it stays stopped). Logs: `journalctl -u <pkg> -f`.
3. Reach it with an SSH tunnel from the owner's computer:
   `ssh -N -L <port>:127.0.0.1:<port> user@server`, then open `http://127.0.0.1:<port>/`.
4. **The apps have no login.** Never bind to `0.0.0.0` on a machine reachable from the internet.
   A VPN (e.g. Tailscale) plus a firewall rule is the alternative to the tunnel. If the owner wants
   access without a tunnel, that is a new requirement (authentication); raise it, don't improvise it.
5. Desktop notifications and "open in its own window" happen in the owner's browser, so they keep
   working through the tunnel.

## External desktop programs on a server

Some services are desktop programs even without a screen (IBKR's TWS / IB Gateway). On a server
they need a virtual display (`Xvfb`) and an automation wrapper (IBC), or a Docker image that
bundles them; logins with two-factor confirmation and forced daily restarts still need the owner.
The app must cope: show the service as disconnected and reconnect by itself.

## Updates and backups

- Update: `git pull`, then restart (Quit + `./start.sh`, or `sudo systemctl restart <pkg>`).
  `migrate()` brings the database up to date on start, so the owner never runs a migration by hand.
- Backup: copy `data/` while the app is stopped (or use `sqlite3 data/<pkg>.db ".backup x.db"`
  while it runs).
