"""Next earnings date per ticker, from Yahoo Finance (through the yfinance library).

Fetched for each ticker once a day (and with Refresh); indexes have none. When Yahoo gives a range
(e.g. "4 Nov – 10 Nov" before the company confirms), the first date is used.
"""

from datetime import date, datetime, timedelta, timezone

from . import db, ibkr

STALE_AFTER = timedelta(hours=20)


class EarningsError(Exception):
    pass


def _yahoo_dates(ticker: str) -> list[date]:
    import yfinance as yf

    try:
        cal = yf.Ticker(ticker.replace(".", "-")).calendar
    except Exception as e:  # noqa: BLE001 - network, Yahoo changes, unknown ticker
        raise EarningsError(f"Yahoo Finance gave no earnings date for {ticker}: {e or type(e).__name__}") from e
    if cal is None:
        return []
    if hasattr(cal, "to_dict"):  # older yfinance versions return a DataFrame
        cal = {k: list(v.values()) for k, v in cal.to_dict().items()}
    found = cal.get("Earnings Date") or []
    if not isinstance(found, (list, tuple)):
        found = [found]
    out = []
    for d in found:
        if isinstance(d, datetime):
            out.append(d.date())
        elif isinstance(d, date):
            out.append(d)
        elif d:
            try:
                out.append(date.fromisoformat(str(d)[:10]))
            except ValueError:
                pass
    return out


fetch_dates = _yahoo_dates  # replaced by a fake in tests


def next_date(ticker: str, today: date | None = None) -> str | None:
    """The first earnings date from today on, as YYYY-MM-DD, or None."""
    today = today or date.today()
    upcoming = sorted(d for d in fetch_dates(ticker) if d >= today)
    return upcoming[0].isoformat() if upcoming else None


def is_stale(conn, ticker: str) -> bool:
    row = conn.execute("SELECT fetched_at FROM earnings WHERE ticker = ?", (ticker,)).fetchone()
    if not row or not row["fetched_at"]:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
    return age > STALE_AFTER


def refresh(conn, ticker: str) -> str | None:
    """Fetch and store; raises EarningsError (and keeps the last known date) when Yahoo fails."""
    ticker = ticker.upper()
    if ibkr.is_index(ticker):
        return None
    try:
        found = next_date(ticker)
    except EarningsError as e:
        conn.execute("INSERT INTO earnings (ticker, error) VALUES (?, ?) "
                     "ON CONFLICT(ticker) DO UPDATE SET error = excluded.error", (ticker, str(e)))
        conn.commit()
        raise
    conn.execute("INSERT INTO earnings (ticker, date, fetched_at, error) VALUES (?, ?, ?, NULL) "
                 "ON CONFLICT(ticker) DO UPDATE SET date = excluded.date, fetched_at = excluded.fetched_at, "
                 "error = NULL", (ticker, found, db.now_iso()))
    conn.commit()
    return found
