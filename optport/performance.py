"""Performance: a snapshot of the portfolio after each US close, the P&L over time against SPY,
and statistics on closed positions.

Total P&L on a day = realized P&L of all legs closed up to that day (after commissions)
                   + unrealized P&L of the open legs that day (from the snapshot) - their opening commissions.
Realized P&L is recalculated from the legs, so a close entered later still lands on its own date;
unrealized P&L can only come from the snapshot taken that day. Days without a snapshot (the app was
not running) are simply missing from the chart.
Return % = P&L / starting capital (Settings). SPY = change of its daily close over the same days.
"""

from datetime import date, datetime, timedelta

from . import calc, db, ibkr, portfolio, refresh, settings

BENCH = "SPY"
PERIODS = ("1m", "3m", "ytd", "1y", "all")


# ---- snapshots --------------------------------------------------------------------------------------

def due_date(now: datetime | None = None) -> str | None:
    """The trading day whose close the next snapshot is for, or None while the market is open.
    After 16:15 New York on a weekday: today; before 9:30, or in the weekend: the last weekday."""
    now = (now or datetime.now(refresh.NEW_YORK)).astimezone(refresh.NEW_YORK)
    if refresh.market_open(now):
        return None
    d = now.date()
    after_close = now.hour * 60 + now.minute > 16 * 60 + 15
    if not (d.weekday() < 5 and after_close):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.isoformat()


def take(conn, day: str, today: date | None = None) -> dict:
    """Save (or overwrite) the snapshot for `day` from the prices the app has now."""
    data = portfolio.build(conn, show="all", today=today or date.fromisoformat(day))
    t = data["totals"]
    row = {"date": day, "positions": t["positions"], "pos_risk": t["pos_risk"], "pos_size": t["pos_size"],
           "unrealized": t["pnl"], "open_commission": t["open_commission"], "realized": t["realized"],
           "delta_dollars": t["delta_dollars"], "missing": t["missing"], "taken_at": db.now_iso()}
    conn.execute(f"INSERT OR REPLACE INTO snapshots ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                 list(row.values()))
    conn.commit()
    return row


def store_bench(conn, ticker: str, closes: list[dict]) -> None:
    conn.executemany("INSERT INTO bench_closes (ticker, date, close) VALUES (?, ?, ?) "
                     "ON CONFLICT(ticker, date) DO UPDATE SET close = excluded.close",
                     [(ticker, c["date"], c["close"]) for c in closes])
    conn.commit()


def has_snapshot(conn, day: str) -> bool:
    return conn.execute("SELECT 1 FROM snapshots WHERE date = ?", (day,)).fetchone() is not None


def snapshot_if_due(now: datetime | None = None) -> str:
    """Called by the scheduler: after the close, refresh the prices and save the day's snapshot.
    Returns what happened (for the log and tests)."""
    day = due_date(now)
    if day is None:
        return "market open"
    with db.closing(db.connect()) as conn:
        if has_snapshot(conn, day):
            return "already saved"
        has_open = bool(refresh.open_tickers(conn))
    client = ibkr.client()
    if client.status()["connected"]:
        with db.closing(db.connect()) as conn:
            try:
                closes = client.daily_closes(BENCH, "1 M")
                store_bench(conn, BENCH, closes)
                if closes and day not in {c["date"] for c in closes}:
                    return "holiday"   # IBKR has no daily bar for a day the market was closed
            except Exception:  # noqa: BLE001 - the benchmark is not essential for the snapshot
                pass
    if has_open:
        try:
            job_id = refresh.start(wait=True)
        except refresh.Busy:
            return "refresh busy"
        with db.closing(db.connect()) as conn:
            job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job["status"] != "done":
            return "no prices"   # try again later rather than saving stale prices
    with db.closing(db.connect()) as conn:
        take(conn, day)
    return "saved"


# ---- the screen -------------------------------------------------------------------------------------

def period_start(period: str, today: date) -> str | None:
    if period == "all":
        return None
    if period == "ytd":
        return date(today.year, 1, 1).isoformat()
    months = {"1m": 1, "3m": 3, "1y": 12}[period]
    y, m = today.year, today.month - months
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, min(today.day, 28)).isoformat()


def _closed_legs(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM legs WHERE close_price IS NOT NULL ORDER BY close_date")
    out = []
    for r in rows:
        lg = dict(r)
        lg["realized"] = calc.leg_metrics(lg, None, None, 0.0, date.fromisoformat(lg["close_date"]))["realized"]
        out.append(lg)
    return out


def _realized_through(legs: list[dict], day: str) -> float:
    return sum(lg["realized"] for lg in legs if lg["close_date"] <= day)


def closed_positions(conn, start: str | None) -> list[dict]:
    """Positions whose legs are all closed, with the last close in the period."""
    pos = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM positions")}
    legs: dict[int, list] = {}
    for r in conn.execute("SELECT * FROM legs ORDER BY id"):
        legs.setdefault(r["position_id"], []).append(dict(r))
    out = []
    for pid, lgs in legs.items():
        if any(lg["close_price"] is None for lg in lgs):
            continue
        closed = max(lg["close_date"] for lg in lgs)
        if start and closed < start:
            continue
        opened = min(lg["entry_date"] for lg in lgs)
        realized = sum(calc.leg_metrics(lg, None, None, 0.0, date.today())["realized"] for lg in lgs)
        cost = sum(lg["qty"] * lg["avg_price"] * lg["multiplier"] for lg in lgs)
        p = pos[pid]
        out.append({"id": pid, "number": f"#{pid:04d}", "ticker": p["ticker"], "direction": p["direction"],
                    "opened": opened, "closed": closed, "days": (date.fromisoformat(closed) - date.fromisoformat(opened)).days,
                    "cost": round(cost, 2), "realized": round(realized, 2),
                    "commission": round(sum((lg["commission"] or 0) + (lg["close_commission"] or 0) for lg in lgs), 2),
                    "return": realized / abs(cost) if cost else None, "legs": len(lgs)})
    return sorted(out, key=lambda x: (x["closed"], x["id"]), reverse=True)


def stats(rows: list[dict]) -> dict:
    wins = [r["realized"] for r in rows if r["realized"] > 0]
    losses = [r["realized"] for r in rows if r["realized"] < 0]
    n = len(rows)
    return {
        "count": n, "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / n if n else None,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "total": round(sum(r["realized"] for r in rows), 2),
        "avg_days": sum(r["days"] for r in rows) / n if n else None,
        "best": max((r["realized"] for r in rows), default=None),
        "worst": min((r["realized"] for r in rows), default=None),
    }


def _group(rows: list[dict], key) -> list[dict]:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return [{"key": k, **stats(v)} for k, v in groups.items()]


def build(conn, period: str = "all", today: date | None = None) -> dict:
    today = today or date.today()
    cfg = settings.load(conn)
    capital = cfg["capital"] or None
    start = period_start(period, today)
    legs = _closed_legs(conn)
    snaps = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY date")]

    points = []
    for s in snaps:
        unreal = (s["unrealized"] or 0) - (s["open_commission"] or 0)
        points.append({"date": s["date"], "realized": round(_realized_through(legs, s["date"]), 2),
                       "unrealized": round(unreal, 2), "missing": s["missing"], "now": False})
    # Today, from the latest prices, unless today's snapshot is already there.
    live = portfolio.build(conn, show="all", today=today)["totals"]
    if not points or points[-1]["date"] < today.isoformat():
        points.append({"date": today.isoformat(), "realized": round(_realized_through(legs, today.isoformat()), 2),
                       "unrealized": round(live["pnl"] - live["open_commission"], 2), "missing": live["missing"],
                       "now": True})
    for p in points:
        p["total"] = round(p["realized"] + p["unrealized"], 2)

    # The period: P&L counted from the last point before it starts (zero at the very beginning).
    before = [p for p in points if start and p["date"] < start]
    base = before[-1]["total"] if before else 0.0
    shown = [p for p in points if not start or p["date"] >= start]
    bench = {r["date"]: r["close"] for r in conn.execute(
        "SELECT date, close FROM bench_closes WHERE ticker = ? ORDER BY date", (BENCH,))}
    bench_dates = sorted(bench)

    def bench_on(day):  # the last close on or before the day
        found = None
        for d in bench_dates:
            if d > day:
                break
            found = bench[d]
        return found

    bench_base_day = before[-1]["date"] if before else (shown[0]["date"] if shown else None)
    bench_base = bench_on(bench_base_day) if bench_base_day else None
    for p in shown:
        p["pnl"] = round(p["total"] - base, 2)
        p["pct"] = p["pnl"] / capital if capital else None
        b = bench_on(p["date"])
        p["bench_pct"] = (b / bench_base - 1) if b and bench_base else None

    closed = closed_positions(conn, start)
    realized_in_period = sum(lg["realized"] for lg in legs if not start or lg["close_date"] >= start)
    last = shown[-1] if shown else None
    return {
        "period": period, "start": start, "capital": capital,
        "series": shown,
        "summary": {
            "pnl": last["pnl"] if last else 0.0,
            "pct": last["pct"] if last else None,
            "bench_pct": last["bench_pct"] if last else None,
            "realized": round(realized_in_period, 2),
            "unrealized": round(live["pnl"] - live["open_commission"], 2),
            "snapshots": len(snaps), "first_snapshot": snaps[0]["date"] if snaps else None,
            "last_snapshot": snaps[-1]["date"] if snaps else None,
        },
        "stats": stats(closed),
        "by_month": sorted(_group(closed, lambda r: r["closed"][:7]), key=lambda g: g["key"], reverse=True),
        "by_direction": sorted(_group(closed, lambda r: r["direction"]), key=lambda g: g["key"]),
        "by_ticker": sorted(_group(closed, lambda r: r["ticker"]), key=lambda g: -g["total"]),
        "closed": closed,
    }
