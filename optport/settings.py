"""App settings stored in the database (key -> JSON value), edited on the Settings page."""

import json

DEFAULTS = {
    "ib_host": "127.0.0.1",
    "ib_port": 7496,             # TWS live 7496, paper 7497; IB Gateway 4001 / 4002
    "ib_client_id": 18,          # the Trade Idea app uses 17, so both can be connected at once
    "interest_rate": 0.04,       # for the calculated delta when TWS sends none
    "refresh_minutes": 5,        # automatic price refresh during US market hours; 0 = off
    "stop_warn_pct": 3.0,        # stop cell orange when the price is this close to the stop (%)
    "expiry_warn_days": 7,       # expiry cell red from this many days before expiry
}
SECRETS: set[str] = set()       # none yet; the IBKR connection needs no password


class SettingsError(Exception):
    pass


def load(conn) -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings")}
    return {k: stored.get(k, v) for k, v in DEFAULTS.items()}


def public(conn) -> dict:
    """Settings for the browser. Secrets would be replaced by 'is it set' and the last 4 characters."""
    cfg = load(conn)
    for key in SECRETS:
        value = cfg.pop(key)
        cfg[f"{key}_set"] = bool(value)
        cfg[f"{key}_hint"] = f"…{value[-4:]}" if len(value) >= 8 else ""
    return cfg


def _number(changes, key, lo, hi, label, whole=False):
    if key not in changes:
        return
    v = changes[key]
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
    if whole:
        ok = ok and float(v).is_integer()
    if not ok:
        kind = "a whole number" if whole else "a number"
        raise SettingsError(f"{label} must be {kind} from {lo:g} to {hi:g}.")
    changes[key] = int(v) if whole else float(v)


def update(conn, changes: dict) -> None:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    if "ib_host" in changes:
        changes["ib_host"] = str(changes["ib_host"]).strip()
        if not changes["ib_host"]:
            raise SettingsError("The TWS host cannot be empty; use 127.0.0.1 when TWS runs on this computer.")
    _number(changes, "ib_port", 1, 65535, "The TWS port", whole=True)
    _number(changes, "ib_client_id", 0, 999, "The client ID", whole=True)
    _number(changes, "interest_rate", 0, 0.25, "The interest rate (e.g. 0.04 for 4%)")
    _number(changes, "refresh_minutes", 0, 240, "The refresh interval", whole=True)
    _number(changes, "stop_warn_pct", 0, 50, "The stop warning distance")
    _number(changes, "expiry_warn_days", 0, 90, "The expiry warning", whole=True)
    for key, value in changes.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
    conn.commit()
