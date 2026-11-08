"""Positions and legs: storing them and putting together the portfolio table."""

from datetime import date

from . import calc, db, settings


class NotFound(Exception):
    pass


class RuleError(Exception):
    pass


LEG_FIELDS = ("qty", "right", "strike", "expiry", "avg_price", "und_entry", "entry_date", "multiplier", "trading_class")


def position_row(conn, pos_id: int) -> dict:
    row = conn.execute("SELECT * FROM positions WHERE id = ?", (pos_id,)).fetchone()
    if not row:
        raise NotFound(f"Position #{pos_id:04d} not found.")
    return dict(row)


def leg_row(conn, leg_id: int) -> dict:
    row = conn.execute("SELECT * FROM legs WHERE id = ?", (leg_id,)).fetchone()
    if not row:
        raise NotFound(f"Leg {leg_id} not found.")
    return dict(row)


def _check_leg(leg: dict):
    if leg.get("qty") == 0:
        raise RuleError("The number of contracts cannot be 0. Use a negative number for a sold leg (e.g. -2).")


def create_position(conn, data: dict) -> int:
    now = db.now_iso()
    legs = data.pop("legs", [])
    for lg in legs:
        _check_leg(lg)
    cur = conn.execute(
        "INSERT INTO positions (ticker, direction, stop, target, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data["ticker"].strip().upper(), data["direction"], data.get("stop"), data.get("target"),
         data.get("notes") or "", now, now))
    pos_id = cur.lastrowid
    for lg in legs:
        _insert_leg(conn, pos_id, lg)
    conn.commit()
    return pos_id


def update_position(conn, pos_id: int, fields: dict) -> None:
    position_row(conn, pos_id)
    if "ticker" in fields:
        fields["ticker"] = fields["ticker"].strip().upper()
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE positions SET {sets}, updated_at = ? WHERE id = ?", [*fields.values(), db.now_iso(), pos_id])
        conn.commit()


def delete_position(conn, pos_id: int) -> None:
    position_row(conn, pos_id)
    conn.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
    conn.commit()


def _insert_leg(conn, pos_id: int, lg: dict) -> int:
    cols = [f for f in LEG_FIELDS if lg.get(f) is not None] + ["close_price", "close_date"]
    vals = [lg[f] for f in cols[:-2]] + [lg.get("close_price"), lg.get("close_date")]
    if lg.get("trading_class") is not None:
        vals[cols.index("trading_class")] = lg["trading_class"].strip().upper() or None
    cur = conn.execute(f"INSERT INTO legs (position_id, {', '.join(cols)}, created_at) "
                       f"VALUES (?, {', '.join('?' * len(cols))}, ?)", [pos_id, *vals, db.now_iso()])
    return cur.lastrowid


def add_leg(conn, pos_id: int, lg: dict) -> int:
    position_row(conn, pos_id)
    _check_leg(lg)
    leg_id = _insert_leg(conn, pos_id, lg)
    conn.execute("UPDATE positions SET updated_at = ? WHERE id = ?", (db.now_iso(), pos_id))
    conn.commit()
    return leg_id


def update_leg(conn, leg_id: int, fields: dict) -> int:
    leg = leg_row(conn, leg_id)
    _check_leg(fields)
    if "trading_class" in fields and fields["trading_class"] is not None:
        fields["trading_class"] = fields["trading_class"].strip().upper() or None
    if fields:
        sets = ", ".join(f'"{k}" = ?' for k in fields)
        conn.execute(f"UPDATE legs SET {sets} WHERE id = ?", [*fields.values(), leg_id])
        conn.execute("UPDATE positions SET updated_at = ? WHERE id = ?", (db.now_iso(), leg["position_id"]))
        conn.commit()
    return leg["position_id"]


def delete_leg(conn, leg_id: int) -> int:
    leg = leg_row(conn, leg_id)
    conn.execute("DELETE FROM legs WHERE id = ?", (leg_id,))
    conn.commit()
    return leg["position_id"]


def close_leg(conn, leg_id: int, qty: int | None, price: float, close_date: str) -> int:
    """Close all of a leg, or `qty` contracts of it (always counted positive). A partial close
    splits off a closed leg with that quantity; the open leg keeps the rest."""
    leg = leg_row(conn, leg_id)
    if leg["close_price"] is not None:
        raise RuleError("This leg is already closed.")
    if close_date < leg["entry_date"]:
        raise RuleError("The close date is before the entry date.")
    total = abs(leg["qty"])
    n = total if qty is None else qty
    if not 1 <= n <= total:
        raise RuleError(f"Close between 1 and {total} contract(s).")
    sign = 1 if leg["qty"] > 0 else -1
    if n == total:
        conn.execute("UPDATE legs SET close_price = ?, close_date = ? WHERE id = ?", (price, close_date, leg_id))
    else:
        conn.execute("UPDATE legs SET qty = ? WHERE id = ?", (sign * (total - n), leg_id))
        _insert_leg(conn, leg["position_id"], {**leg, "qty": sign * n, "close_price": price, "close_date": close_date})
    conn.execute("UPDATE positions SET updated_at = ? WHERE id = ?", (db.now_iso(), leg["position_id"]))
    conn.commit()
    return leg["position_id"]


def reopen_leg(conn, leg_id: int) -> int:
    leg = leg_row(conn, leg_id)
    conn.execute("UPDATE legs SET close_price = NULL, close_date = NULL WHERE id = ?", (leg_id,))
    conn.commit()
    return leg["position_id"]


# ---- the table ------------------------------------------------------------------------------------

def _round(d: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def build(conn, pos_ids: list[int] | None = None, show: str = "open", today: date | None = None) -> dict:
    """Positions with their legs, the calculated columns and the totals."""
    today = today or date.today()
    cfg = settings.load(conn)
    sql, args = "SELECT * FROM positions", []
    if pos_ids is not None:
        sql += f" WHERE id IN ({', '.join('?' * len(pos_ids))})"
        args = pos_ids
    positions = [dict(r) for r in conn.execute(sql + " ORDER BY ticker, id", args)]
    if not positions:
        return {"positions": [], "totals": calc.portfolio_totals([]), "as_of": today.isoformat()}
    ids = [p["id"] for p in positions]
    marks = ", ".join("?" * len(ids))
    legs_by_pos: dict[int, list] = {}
    for r in conn.execute(f"SELECT * FROM legs WHERE position_id IN ({marks}) "
                          "ORDER BY close_price IS NOT NULL, id", ids):
        legs_by_pos.setdefault(r["position_id"], []).append(dict(r))
    tickers = sorted({p["ticker"] for p in positions})
    tmarks = ", ".join("?" * len(tickers))
    und = {r["ticker"]: dict(r) for r in conn.execute(f"SELECT * FROM und_quotes WHERE ticker IN ({tmarks})", tickers)}
    earn = {r["ticker"]: dict(r) for r in conn.execute(f"SELECT * FROM earnings WHERE ticker IN ({tmarks})", tickers)}
    quotes = {(r["ticker"], r["expiry"], r["right"], r["strike"]): dict(r)
              for r in conn.execute(f"SELECT * FROM opt_quotes WHERE ticker IN ({tmarks})", tickers)}
    broker = {(r["ticker"], r["expiry"], r["right"], r["strike"]): r["qty"]
              for r in conn.execute("SELECT * FROM broker_positions")}
    have_broker = conn.execute("SELECT MAX(fetched_at) FROM broker_positions").fetchone()[0]

    out = []
    for p in positions:
        t = p["ticker"]
        uq = und.get(t) or {}
        price = uq.get("price")
        legs = legs_by_pos.get(p["id"], [])
        # legs are numbered in the order they were entered: #0012-01, -02, ...
        order = {lg["id"]: i for i, lg in enumerate(sorted(legs, key=lambda x: x["id"]), start=1)}
        open_qty: dict[tuple, int] = {}
        for lg in legs:
            key = (t, lg["expiry"], lg["right"], lg["strike"])
            q = quotes.get(key)
            lg["number"] = f"#{p['id']:04d}-{order[lg['id']]:02d}"
            lg["m"] = _round(calc.leg_metrics(lg, price, q, cfg["interest_rate"], today))
            lg["quote"] = {k: q[k] for k in ("bid", "ask", "last", "close", "delayed", "fetched_at", "error")} if q else None
            if lg["close_price"] is None:
                open_qty[key] = open_qty.get(key, 0) + lg["qty"]
        for lg in legs:
            key = (t, lg["expiry"], lg["right"], lg["strike"])
            lg["broker_qty"] = broker.get(key, 0) if have_broker and lg["close_price"] is None else None
            lg["broker_mismatch"] = lg["broker_qty"] is not None and lg["broker_qty"] != open_qty.get(key)
        e = earn.get(t) or {}
        m = calc.position_metrics(p, legs, price, e.get("date"), cfg, today)
        p.update(number=f"#{p['id']:04d}", legs=legs, m=_round(m),
                 und={"price": price, "source": uq.get("source"), "fetched_at": uq.get("fetched_at"),
                      "error": uq.get("error")},
                 earnings={"date": e.get("date"), "fetched_at": e.get("fetched_at"), "error": e.get("error")})
        out.append(p)
    if show != "all":
        out = [p for p in out if p["m"]["open"] == (show == "open") or (show == "open" and not p["legs"])]
    return {"positions": out, "totals": calc.portfolio_totals(out), "as_of": today.isoformat(),
            "broker_checked_at": have_broker, "cfg": {k: cfg[k] for k in ("stop_warn_pct", "expiry_warn_days")}}
