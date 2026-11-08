"""SQLite database: schema, migrations and connections. One file in data/, WAL mode."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Every table is created with IF NOT EXISTS, so init() is safe on every start. Columns added in a
# later version also go in migrate(), because CREATE TABLE IF NOT EXISTS does not change old tables.
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    notes       TEXT NOT NULL DEFAULT '',
    priority    INTEGER,                   -- added in a later version: also in migrate()
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- App settings: key -> JSON value. Defaults live in settings.py, so only changed values are stored.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Long-running jobs (imports, external calls). The UI polls them; init() marks leftovers as interrupted.
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,            -- running / done / error
    message      TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);
"""

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "__pkg__.db"


def db_path() -> str:
    return os.environ.get("__ENV___DB", str(DEFAULT_DB))


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
    """Bring databases created by earlier versions up to date. Only ever add; never lose data."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    for col, decl in [("priority", "INTEGER")]:  # example of a column added in a later version
        if col not in cols:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {decl}")


@contextmanager
def closing(conn: sqlite3.Connection):
    try:
        yield conn
    finally:
        conn.close()
