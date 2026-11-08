# Option Portfolio

A personal app for following a portfolio of stock and index options, built like the Trade Idea
Management System: a local web app with a Python backend. It runs on your own computer (it opens in
its own window) or on a headless server that you reach through an SSH tunnel.

**Current state:** the **Portfolio** and **Performance** screens, the position page and the
IBKR/Yahoo price feeds.

## What it does

- **Positions and legs.** A position is one ticker with a direction (LONG/SHORT), a **stop** and a
  **target** on the stock price, and one or more option legs. A leg has a number of contracts
  (positive = bought, negative = sold, e.g. +3 / −2), call or put, strike, expiry, average price,
  the stock price at entry and the entry date. Positions are numbered `#0012`, legs `#0012-01`.
- **Portfolio screen** (📋 in the sidebar): one row per leg, with the columns of the portfolio sheet:
  - *Position:* ticker, L/S, current stock price, next earnings date.
  - *Initial purchase:* #, P/C, strike, expiry, av. price, stock price at entry, entry date, and
    **IV** (intrinsic value) and **TV** (time value) per share at entry.
  - *Initial risk:* stop, and **pos risk** = contracts × av. price × 100 (what the leg cost;
    negative for a sold leg).
  - *Current position:* target, **DTE** (days to expiry), **price\*** (mid of bid and ask; without
    both the last trade, then the close), **pos size** = contracts × price × 100, **P&L** = pos size −
    pos risk, **IV\*** and **TV\*** now, and **Δ $** (delta dollars) = contracts × 100 × delta ×
    stock price, the stock exposure in dollars (negative for puts you hold).
  - A position with several legs gets a total row (net risk, size, P&L and delta dollars).
  - Tiles above the table: open positions, total risk, size, unrealized P&L (also as % of the risk),
    net delta dollars, and realized P&L of the closed legs.
  - **Colours:** orange earnings date = earnings before the position's last expiry; orange stop = the
    price is within 3% of the stop, red = through it; red expiry = expired, light red = expires
    within 7 days; P&L green/red. The 3% and 7 days can be changed in Settings.
  - **TWS check:** next to the number of contracts, an orange **TWS n** tag appears when TWS holds a
    different quantity of that option than your open legs here (e.g. after a fill you haven't entered).
  - Hover a price to see bid, ask, last and the time of the quote. A delta marked \* is calculated
    by the app (Black-Scholes from the option price) because TWS sent none.
  - **Open / Closed / All** filter. A position counts as closed when all its legs are closed.
  - On a smaller screen the table scrolls sideways; the ticker column stays in view.
- **Position page** (click a row): edit ticker, direction, stop and target; **add a leg**; **edit** or
  **delete** a leg (for one entered by mistake); **close** a leg at a price and date, wholly or partly
  (closing 1 of 3 contracts splits off a closed leg); **reopen** a closed leg; notes. Closed legs show
  their realized P&L. A roll is a close plus a new leg.
- **Commissions** (optional): per leg, what opening cost (in the leg form) and what closing cost (in
  the Close dialog), in dollars. The sheet columns (pos risk, P&L) stay before commissions, as in
  your sheet; realized P&L and everything on the Performance screen is after commissions. Closing
  part of a leg shares its opening commission in proportion. **Edit** on a closed leg corrects its
  close price, date and commission.
- **Performance screen** (📈 in the sidebar), with a period choice: 1M, 3M, YTD, 1Y, All.
  - **Daily snapshot:** after each US close (from 16:15 New York, or the next time the app runs
    before the next open) the app refreshes the prices and saves the portfolio: open positions, risk,
    size, unrealized P&L and delta dollars. It does not save when the prices could not be refreshed
    (e.g. TWS not connected) and tries again every 10 minutes; market holidays are skipped. Days on
    which the app did not run are missing from the history (they cannot be filled in afterwards).
  - **Total P&L** on a day = realized P&L of all legs closed up to that day + unrealized P&L of the
    open legs that day, both after commissions. Realized P&L is taken from the legs, so a close
    entered later still lands on its own date.
  - **Chart:** P&L over time, from the start of the period. With a **starting capital** in Settings
    it shows the return in % (P&L ÷ capital) with **SPY** over the same days as a dashed line;
    without it, P&L in dollars. The last point is today at the latest prices.
  - **Tiles:** P&L in the period, return %, SPY, realized in the period (also partial closes of
    positions still open), unrealized now, win rate and profit factor.
  - **Closed positions** (all legs closed, last close in the period): number, won/lost, win rate,
    average win and loss, profit factor (total wins ÷ total losses), best/worst, average days held;
    split by long/short, by month and by ticker; and a list with per position the cost (contracts ×
    av. price × 100 over all legs), commissions, realized P&L and return (realized ÷ cost).
- **Prices from Interactive Brokers** (TWS or IB Gateway, read-only, never places orders):
  - stock and index prices, option bid/ask/last/close and delta for every open leg, and your option
    positions in TWS (for the TWS check);
  - refreshed when the app starts, every 5 minutes during US market hours (Mon–Fri 9:30–16:15 New
    York), and with **↻ Refresh**;
  - without a stock quote the last daily close is used, or the stock price TWS used for the option;
  - **index options**: SPX, XSP, VIX, DJX (CBOE), NDX (Nasdaq) and RUT (Russell) are looked up as
    indexes, everything else as a stock or ETF. Where an expiry has several option classes (SPX and
    SPXW), enter the class on the leg; without it the standard class is used.
  - The sidebar shows the connection: green = connected, red = not connected (it retries every 30 s).
    The app uses client ID 18, so it can be connected at the same time as the Trade Idea app (17).
- **Earnings dates from Yahoo Finance**, fetched once a day per ticker and with every Refresh.
  Indexes have none.
- **Settings (⚙):** TWS host, port and client ID (with **Test connection**), the refresh interval, the
  stop and expiry warnings, the interest rate used for calculated deltas, and the starting capital.

## Setup (Linux)

Requires Python 3.10 or newer, and preferably Chrome or Chromium, so the app opens in its own window.

```bash
git clone git@github.com:KOENDERSPMD/OptionPortfolio.git optport
cd optport
./start.sh
```

The first run creates a Python environment in `.venv` and installs the dependencies. After that,
`./start.sh` starts the app and opens it. To close the app, click **⏻ Quit** at the bottom of the
sidebar (or press Ctrl+C in the terminal). Quit warns first when work is still running.

To start it from your applications menu, create `~/.local/share/applications/optport.desktop`
(replace the path):

```ini
[Desktop Entry]
Type=Application
Name=Option Portfolio
Exec=/home/YOU/optport/start.sh
Terminal=true
```

### Configuration

| Environment variable   | Default            | Purpose                                                       |
|------------------------|--------------------|---------------------------------------------------------------|
| `OPTPORT_PORT`         | `8771`             | Port of the server                                            |
| `OPTPORT_HOST`         | `127.0.0.1`        | Address the server listens on (only this computer by default) |
| `OPTPORT_DB`           | `data/optport.db`  | Database file (SQLite)                                        |
| `OPTPORT_NO_BROWSER`   |                    | Set to `1` to start without opening a window                  |
| `OPTPORT_NO_BACKGROUND`|                    | Set to `1` to start without TWS and the scheduled refresh (tests) |

### Connecting to TWS or IB Gateway

In TWS: *File → Global Configuration → API → Settings*: tick **Enable ActiveX and Socket Clients**,
note the **Socket port** (TWS 7496, paper 7497; IB Gateway 4001, paper 4002) and add `127.0.0.1` to
**Trusted IPs**. **Read-Only API** can stay ticked. Then enter the port in the app's Settings.
Without an options data subscription, IBKR sends free delayed quotes once you have clicked *Free
Delayed Data* on an option quote in TWS.

**Backup:** copy the `data/` folder while the app is stopped.

### When it doesn't start

- Run `./start.sh` from a terminal. When start-up fails, it prints the error and keeps the window open.
- Everything the server prints is also written to **`data/optport.log`**.
- *"Port … is already in use"*: another program uses the port. Start on another one:
  `OPTPORT_PORT=<other port> ./start.sh`.

## Running on a headless server

1. Clone and run `./start.sh` once on the server (creates `.venv`), then stop it.
2. Edit `deploy/optport.service` (user and path) and follow the steps at the top of that file.
   Without systemd: `OPTPORT_NO_BROWSER=1 ./start.sh` inside `tmux`.
3. Keep it on 127.0.0.1 (the default) and connect from your own computer with an SSH tunnel:

   ```bash
   ssh -N -L 8771:127.0.0.1:8771 you@your-server
   ```

   then open <http://127.0.0.1:8771/>. The app has **no login**: never set
   `OPTPORT_HOST=0.0.0.0` on a machine reachable from the internet.
4. **⏻ Quit** stops the service (systemd does not restart it after a clean exit); start it again
   with `sudo systemctl start optport`.

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

- `optport/main.py`: the API (FastAPI) and the start-up/shut-down of background work.
- `optport/db.py`: the SQLite schema and migrations (columns are only ever added).
- `optport/settings.py`: settings stored in the database; secrets never go to the browser.
- `optport/calc.py`: the portfolio arithmetic (intrinsic/time value, risk, P&L, delta dollars, warnings).
- `optport/portfolio.py`: positions and legs, closing legs, and putting the table together.
- `optport/ibkr.py`: the TWS client (adapted from the Trade Idea app), `optport/earnings.py`: Yahoo.
- `optport/refresh.py`: the price refresh job and the market-hours scheduler.
- `optport/performance.py`: daily snapshots, the P&L series against SPY and the closed-position statistics.
- `optport/web/vendor/`: Lightweight Charts 4.2.3 (TradingView, Apache 2.0) for the Performance chart.
- `optport/web/`: the browser UI, plain JavaScript and CSS without a build step.
- `tests/`: pytest; each test gets its own database file.
