"""SQLite database: schema, migrations and connections. One file in data/, WAL mode."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Every table is created with IF NOT EXISTS, so init() is safe on every start. Columns added in a
# later version also go in migrate(), because CREATE TABLE IF NOT EXISTS does not change old tables.
SCHEMA = """
-- A position: one ticker, one direction, a stop and a target on the stock (or index) price.
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    direction   TEXT NOT NULL,             -- long / short
    stop        REAL,                      -- stock price
    target      REAL,                      -- stock price
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS positions_ticker ON positions(ticker);

-- An option leg of a position. qty is signed: +3 bought, -2 sold. A leg is closed when it has a
-- close price; closing part of a leg splits off a closed leg with that quantity.
CREATE TABLE IF NOT EXISTS legs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id   INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    qty           INTEGER NOT NULL,
    right         TEXT NOT NULL,           -- C / P
    strike        REAL NOT NULL,
    expiry        TEXT NOT NULL,           -- YYYY-MM-DD
    avg_price     REAL NOT NULL,           -- per share: paid (bought leg) or received (sold leg)
    und_entry     REAL,                    -- stock price at entry
    entry_date    TEXT NOT NULL,           -- YYYY-MM-DD
    multiplier    INTEGER NOT NULL DEFAULT 100,
    trading_class TEXT,                    -- e.g. SPXW; empty = let IBKR choose
    close_price   REAL,
    close_date    TEXT,
    created_at    TEXT NOT NULL,
    commission    REAL,                    -- added in v2 (also in migrate): $ paid when opening
    close_commission REAL                  -- added in v2 (also in migrate): $ paid when closing
);
CREATE INDEX IF NOT EXISTS legs_position ON legs(position_id);

-- Latest price of each stock or index, from IBKR.
CREATE TABLE IF NOT EXISTS und_quotes (
    ticker      TEXT PRIMARY KEY,
    price       REAL,
    source      TEXT,                      -- live / delayed / close / option
    fetched_at  TEXT,
    error       TEXT
);

-- Latest quote of each option contract, from IBKR.
CREATE TABLE IF NOT EXISTS opt_quotes (
    ticker      TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    right       TEXT NOT NULL,
    strike      REAL NOT NULL,
    bid         REAL,
    ask         REAL,
    last        REAL,
    close       REAL,
    delta       REAL,
    impl_vol    REAL,
    und_price   REAL,
    delayed     INTEGER NOT NULL DEFAULT 0,
    fetched_at  TEXT,
    error       TEXT,
    PRIMARY KEY (ticker, expiry, right, strike)
);

-- Next earnings date per ticker, from Yahoo Finance.
CREATE TABLE IF NOT EXISTS earnings (
    ticker      TEXT PRIMARY KEY,
    date        TEXT,                      -- YYYY-MM-DD, NULL = none announced
    fetched_at  TEXT,
    error       TEXT
);

-- Option positions as TWS reports them, to compare with the legs entered here.
CREATE TABLE IF NOT EXISTS broker_positions (
    ticker      TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    right       TEXT NOT NULL,
    strike      REAL NOT NULL,
    qty         REAL NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, expiry, right, strike)
);

-- The portfolio after each US close, for the Performance screen. Amounts in dollars.
CREATE TABLE IF NOT EXISTS snapshots (
    date             TEXT PRIMARY KEY,     -- the trading day, YYYY-MM-DD
    positions        INTEGER NOT NULL,     -- open positions
    pos_risk         REAL NOT NULL,        -- what the open legs cost
    pos_size         REAL NOT NULL,        -- what the open legs were worth
    unrealized       REAL NOT NULL,        -- pos_size - pos_risk
    open_commission  REAL NOT NULL,        -- commissions paid on the open legs
    realized         REAL NOT NULL,        -- all closed legs so far, after commissions
    delta_dollars    REAL,
    missing          INTEGER NOT NULL DEFAULT 0,   -- open positions without a price
    taken_at         TEXT NOT NULL
);

-- Daily closes of the benchmark (SPY), from IBKR.
CREATE TABLE IF NOT EXISTS bench_closes (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    close   REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- App settings: key -> JSON value. Defaults live in settings.py, so only changed values are stored.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Long-running jobs (price refreshes). The UI polls them; init() marks leftovers as interrupted.
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,            -- running / done / error
    message      TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);
"""

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "optport.db"


def db_path() -> str:
    return os.environ.get("OPTPORT_DB", str(DEFAULT_DB))


def now_iso() -> str:
    """UTC timestamp, second precision, e.g. 2026-10-10T12:32:05Z. The browser shows it in local time."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer (web requests + jobs)
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init(path: str | None = None) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        # Jobs still marked running belong to a previous server process that stopped.
        conn.execute("UPDATE jobs SET status='error', message='Interrupted (app was restarted)', "
                     "finished_at=? WHERE status='running'", (now_iso(),))
        conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    """Bring databases created by earlier versions up to date. Only ever add; never lose data.
    A column added later goes in its CREATE TABLE above and here."""
    add_columns(conn, "legs", [("commission", "REAL"), ("close_commission", "REAL")])  # v2


def add_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for col, decl in columns:
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


@contextmanager
def closing(conn: sqlite3.Connection):
    try:
        yield conn
    finally:
        conn.close()
