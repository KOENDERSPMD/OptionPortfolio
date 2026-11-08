"""Portfolio arithmetic (pure functions, no I/O), matching the columns of the portfolio sheet.

Per leg (qty is signed: +3 bought, -2 sold; amounts are per share unless they say "pos"):
  IV  (intrinsic value)  calls: max(stock - strike, 0); puts: max(strike - stock, 0)
  TV  (time value)       option price - IV
  pos risk               qty x average price x multiplier: what the leg cost (negative = received)
  pos size               qty x current price x multiplier: what the leg is worth now
  P&L (unrealized)       pos size - pos risk
  delta dollars          qty x multiplier x delta x stock price: the stock exposure in dollars
  realized (closed leg)  qty x (close price - average price) x multiplier - commissions (open + close)
Commissions are optional; the sheet columns (pos risk, P&L) are before commissions, as in the sheet.
The current option price is the mid of bid and ask; without both, the last trade, then the close.
Delta comes from TWS; without it, it is calculated with Black-Scholes from the option price
(marked * in the screen).
"""

import math
from datetime import date

SQRT2 = math.sqrt(2.0)


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def intrinsic(S: float, K: float, right: str) -> float:
    return max(S - K, 0.0) if right == "C" else max(K - S, 0.0)


def years_to(expiry: str, today: date) -> float:
    """Expiry as YYYY-MM-DD. Expiring today still has a sliver of time left."""
    return max((date.fromisoformat(expiry) - today).days, 0) / 365.0 + 0.5 / 365.0


def bs_price(S, K, T, r, sigma, right):
    if T <= 0 or sigma <= 0:
        return intrinsic(S, K, right)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    if right == "C":
        return S * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return K * math.exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)


def bs_delta(S, K, T, r, sigma, right):
    if T <= 0 or sigma <= 0:
        itm = S > K if right == "C" else S < K
        return (1.0 if itm else 0.0) * (1 if right == "C" else -1)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return ncdf(d1) if right == "C" else ncdf(d1) - 1.0


def implied_vol(price, S, K, T, r, right):
    """Bisection; None when the price is impossible (e.g. below intrinsic value)."""
    if price is None or price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None
    lo, hi = 1e-4, 5.0
    if price < bs_price(S, K, T, r, lo, right) - 1e-9 or price > bs_price(S, K, T, r, hi, right):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, right) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def option_price(quote: dict | None) -> tuple[float | None, str | None]:
    """(price, source): mid, else last, else close."""
    if not quote:
        return None, None
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2, "mid"
    for key in ("last", "close"):
        if quote.get(key) is not None and quote[key] >= 0:
            return quote[key], key
    return None, None


def _r2(v):
    return None if v is None else round(v, 2)


def leg_metrics(leg: dict, und: float | None, quote: dict | None, rate: float, today: date) -> dict:
    """The sheet's columns for one leg. `und` is the current stock price, `quote` the option quote."""
    qty, mult, right, K = leg["qty"], leg["multiplier"], leg["right"], leg["strike"]
    out = {
        "iv_entry": None, "tv_entry": None,
        "pos_risk": qty * leg["avg_price"] * mult,
        "dte": (date.fromisoformat(leg["expiry"]) - today).days,
        "price_now": None, "price_source": None, "pos_size": None, "pnl": None, "realized": None,
        "iv_now": None, "tv_now": None, "delta": None, "delta_calc": False, "delta_dollars": None,
        "commission": (leg.get("commission") or 0.0) + (leg.get("close_commission") or 0.0),
    }
    if leg.get("und_entry"):
        out["iv_entry"] = intrinsic(leg["und_entry"], K, right)
        out["tv_entry"] = leg["avg_price"] - out["iv_entry"]

    if leg.get("close_price") is not None:  # closed: only the realized result matters
        out["price_now"], out["price_source"] = leg["close_price"], "closed"
        out["realized"] = qty * (leg["close_price"] - leg["avg_price"]) * mult - out["commission"]
        return out

    price, source = option_price(quote)
    if price is None and out["dte"] < 0 and und is not None:
        price, source = intrinsic(und, K, right), "expired"  # expired: worth its intrinsic value
    out["price_now"], out["price_source"] = price, source
    if price is not None:
        out["pos_size"] = qty * price * mult
        out["pnl"] = out["pos_size"] - out["pos_risk"]
    if und is not None:
        out["iv_now"] = intrinsic(und, K, right)
        if price is not None:
            out["tv_now"] = price - out["iv_now"]

    delta = quote.get("delta") if quote else None
    if delta is None and und and price is not None:
        T = years_to(leg["expiry"], today)
        sigma = implied_vol(price, und, K, T, rate, right)
        if sigma is not None:
            delta, out["delta_calc"] = bs_delta(und, K, T, rate, sigma, right), True
        elif out["dte"] < 0 or (price <= intrinsic(und, K, right) + 1e-9):
            delta, out["delta_calc"] = bs_delta(und, K, 0, rate, 0, right), True  # no time value left
    if delta is not None:
        out["delta"] = delta
        if und is not None:
            out["delta_dollars"] = qty * mult * delta * und
    return out


def stop_state(direction: str, price: float | None, stop: float | None, warn_pct: float) -> str | None:
    """'hit' when the price is through the stop, 'near' within warn_pct %, else None."""
    if price is None or not stop:
        return None
    if (direction == "long" and price <= stop) or (direction == "short" and price >= stop):
        return "hit"
    if abs(price - stop) / price * 100 <= warn_pct:
        return "near"
    return None


def pct_to(price: float | None, level: float | None) -> float | None:
    """How far `level` is from the price, as a fraction (+0.05 = 5% above)."""
    if not price or not level:
        return None
    return level / price - 1


def position_metrics(pos: dict, legs: list[dict], und: float | None, earnings_date: str | None,
                     cfg: dict, today: date) -> dict:
    """Totals and warnings for a position whose legs already carry leg_metrics()."""
    open_legs = [lg for lg in legs if lg.get("close_price") is None]
    closed = [lg for lg in legs if lg.get("close_price") is not None]

    def total(key, rows):
        vals = [lg["m"][key] for lg in rows]
        return None if not rows or any(v is None for v in vals) else sum(vals)

    last_expiry = max((lg["expiry"] for lg in open_legs), default=None)
    earnings_flag = bool(earnings_date and last_expiry and today.isoformat() <= earnings_date <= last_expiry)
    return {
        "open": bool(open_legs),
        "pos_risk": total("pos_risk", open_legs),
        "pos_size": total("pos_size", open_legs),
        "pnl": total("pnl", open_legs),
        "delta_dollars": total("delta_dollars", open_legs),
        "realized": sum(lg["m"]["realized"] for lg in closed) if closed else 0.0,
        "open_commission": sum(lg["m"]["commission"] for lg in open_legs),
        "stop_state": stop_state(pos["direction"], und, pos.get("stop"), cfg["stop_warn_pct"]),
        "to_stop": pct_to(und, pos.get("stop")),
        "to_target": pct_to(und, pos.get("target")),
        "earnings_before_expiry": earnings_flag,
        "min_dte": min((lg["m"]["dte"] for lg in open_legs), default=None),
    }


def portfolio_totals(positions: list[dict]) -> dict:
    """Sums over open positions; a missing value (no quote yet) is left out and counted."""
    out = {"positions": 0, "pos_risk": 0.0, "pos_size": 0.0, "pnl": 0.0, "delta_dollars": 0.0,
           "realized": 0.0, "open_commission": 0.0, "missing": 0}
    for p in positions:
        out["realized"] += p["m"]["realized"]
        if not p["m"]["open"]:
            continue
        out["positions"] += 1
        out["open_commission"] += p["m"]["open_commission"]
        for key in ("pos_risk", "pos_size", "pnl", "delta_dollars"):
            if p["m"][key] is None:
                out["missing"] += key == "pnl"
            else:
                out[key] += p["m"][key]
    return {k: (_r2(v) if isinstance(v, float) else v) for k, v in out.items()}
