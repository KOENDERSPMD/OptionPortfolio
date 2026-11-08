"""Refreshing prices: stock/index prices and option quotes from IBKR, earnings dates from Yahoo.

One refresh at a time runs in a background thread with a row in the jobs table, which the UI polls.
The scheduler starts one at app start and then every `refresh_minutes` during US market hours.
"""

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, earnings, ibkr, settings

NEW_YORK = ZoneInfo("America/New_York")
_lock = threading.Lock()


class Busy(Exception):
    pass


def open_contracts(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT p.ticker, l.expiry, l.right, l.strike, l.trading_class FROM legs l "
        "JOIN positions p ON p.id = l.position_id WHERE l.close_price IS NULL ORDER BY p.ticker, l.expiry, l.strike")
    return [dict(r) for r in rows]


def open_tickers(conn) -> list[str]:
    return [r["ticker"] for r in conn.execute(
        "SELECT DISTINCT p.ticker FROM positions p JOIN legs l ON l.position_id = p.id "
        "WHERE l.close_price IS NULL ORDER BY p.ticker")]


def store_und(conn, ticker, price, source, error=None):
    if price is None:  # keep the last known price, only note the error
        conn.execute("INSERT INTO und_quotes (ticker, error) VALUES (?, ?) "
                     "ON CONFLICT(ticker) DO UPDATE SET error = excluded.error", (ticker, error))
    else:
        conn.execute("INSERT INTO und_quotes (ticker, price, source, fetched_at, error) VALUES (?, ?, ?, ?, NULL) "
                     "ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, source = excluded.source, "
                     "fetched_at = excluded.fetched_at, error = NULL", (ticker, price, source, db.now_iso()))


def store_option(conn, q: dict):
    key = (q["ticker"], q["expiry"], q["right"], q["strike"])
    if q.get("error"):
        conn.execute("INSERT INTO opt_quotes (ticker, expiry, right, strike, error) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT(ticker, expiry, right, strike) DO UPDATE SET error = excluded.error", (*key, q["error"]))
        return
    conn.execute(
        "INSERT INTO opt_quotes (ticker, expiry, right, strike, bid, ask, last, close, delta, impl_vol, und_price, "
        "delayed, fetched_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL) "
        "ON CONFLICT(ticker, expiry, right, strike) DO UPDATE SET bid = excluded.bid, ask = excluded.ask, "
        "last = excluded.last, close = excluded.close, delta = excluded.delta, impl_vol = excluded.impl_vol, "
        "und_price = excluded.und_price, delayed = excluded.delayed, fetched_at = excluded.fetched_at, error = NULL",
        (*key, q.get("bid"), q.get("ask"), q.get("last"), q.get("close"), q.get("delta"), q.get("impl_vol"),
         q.get("und_price"), int(bool(q.get("delayed"))), db.now_iso()))


def run(conn, force_earnings: bool = False) -> dict:
    """Refresh everything for the open legs. Returns a summary; errors are collected, not raised."""
    tickers, contracts = open_tickers(conn), open_contracts(conn)
    summary = {"tickers": len(tickers), "quotes": 0, "errors": []}
    client = ibkr.client()
    if tickers and client.status()["connected"]:
        und_found = set()
        for t in tickers:
            try:
                r = client.underlying_price(t)
                store_und(conn, t, r["price"], r["source"])
                und_found.add(t)
            except Exception as e:  # noqa: BLE001 - one ticker must not stop the rest
                store_und(conn, t, None, None, str(e) or type(e).__name__)
                summary["errors"].append(f"{t}: {e}")
        try:
            quotes = client.option_quotes(contracts)
        except Exception as e:  # noqa: BLE001
            quotes = []
            summary["errors"].append(f"Option quotes: {e}")
        for q in quotes:
            store_option(conn, q)
            if q.get("error"):
                summary["errors"].append(q["error"])
                continue
            summary["quotes"] += 1
            if q["ticker"] not in und_found and q.get("und_price"):  # no stock quote: the one TWS used for the option
                store_und(conn, q["ticker"], q["und_price"], "option")
                und_found.add(q["ticker"])
        try:
            store_broker_positions(conn, client.positions())
        except Exception as e:  # noqa: BLE001
            summary["errors"].append(f"Positions from TWS: {e}")
        conn.commit()
    elif tickers:
        summary["errors"].append("Not connected to TWS, so no new prices. " + (client.status().get("error") or ""))
    for t in tickers:
        if ibkr.is_index(t) or not (force_earnings or earnings.is_stale(conn, t)):
            continue
        try:
            earnings.refresh(conn, t)
        except earnings.EarningsError as e:
            summary["errors"].append(str(e))
    return summary


def store_broker_positions(conn, rows: list[dict]):
    now = db.now_iso()
    conn.execute("DELETE FROM broker_positions")
    conn.executemany(
        "INSERT INTO broker_positions (ticker, expiry, right, strike, qty, fetched_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ticker, expiry, right, strike) DO UPDATE SET qty = qty + excluded.qty",
        [(r["ticker"].upper(), r["expiry"], r["right"], r["strike"], r["qty"], now) for r in rows])
    conn.commit()


def _message(s: dict) -> str:
    msg = f"{s['quotes']} option quote(s) for {s['tickers']} ticker(s)"
    if s["errors"]:
        msg += f"; {len(s['errors'])} problem(s): " + " · ".join(s["errors"][:5])
    return msg


def start(force_earnings: bool = False, wait: bool = False) -> int:
    """Start a refresh in the background; returns the job id. Raises Busy when one is running."""
    if not _lock.acquire(blocking=False):
        raise Busy("Prices are already being refreshed.")
    with db.closing(db.connect()) as conn:
        cur = conn.execute("INSERT INTO jobs (kind, status, started_at) VALUES ('refresh', 'running', ?)", (db.now_iso(),))
        conn.commit()
        job_id = cur.lastrowid

    def work():
        conn = db.connect()
        try:
            s = run(conn, force_earnings)
            status = "error" if s["errors"] and not s["quotes"] and s["tickers"] else "done"
            conn.execute("UPDATE jobs SET status = ?, message = ?, finished_at = ? WHERE id = ?",
                         (status, _message(s), db.now_iso(), job_id))
        except Exception as e:  # noqa: BLE001 - shown in the UI
            conn.execute("UPDATE jobs SET status = 'error', message = ?, finished_at = ? WHERE id = ?",
                         (f"The refresh failed: {e}", db.now_iso(), job_id))
        finally:
            conn.commit()
            conn.close()
            _lock.release()

    if wait:
        work()
    else:
        threading.Thread(target=work, name="refresh", daemon=True).start()
    return job_id


def last_job(conn) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE kind = 'refresh' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def market_open(now: datetime | None = None) -> bool:
    """US regular hours, Monday to Friday 9:30-16:15 New York (holidays not excluded)."""
    now = (now or datetime.now(NEW_YORK)).astimezone(NEW_YORK)
    minutes = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 30 <= minutes <= 16 * 60 + 15


class Scheduler:
    """Refresh once shortly after start (when TWS has had time to connect), then on the interval
    during market hours. Earnings dates refresh with it when they are older than a day."""

    def __init__(self):
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
            self.thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        self._stop.wait(8)
        last = None
        while not self._stop.is_set():
            with db.closing(db.connect()) as conn:
                minutes = settings.load(conn)["refresh_minutes"]
            due = last is None or (minutes and market_open() and datetime.now() - last >= timedelta(minutes=minutes))
            if due:
                try:
                    start()
                    last = datetime.now()
                except Busy:
                    pass
            self._stop.wait(30)


scheduler = Scheduler()
