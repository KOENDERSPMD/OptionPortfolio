"""App settings stored in the database (key -> JSON value), edited on the Settings page."""

import json
import os

DEFAULTS = {
    "api_key": "",          # secret: stored here, never sent to the browser (see public())
    "page_size": 50,
}
SECRETS = {"api_key"}


class SettingsError(Exception):
    pass


def load(conn) -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings")}
    return {k: stored.get(k, v) for k, v in DEFAULTS.items()}


def api_key(conn) -> str:
    """The key from Settings, or an environment variable as a fallback (handy on a server)."""
    return load(conn)["api_key"] or os.environ.get("__ENV___API_KEY", "")


def public(conn) -> dict:
    """Settings for the browser. Secrets are replaced by 'is it set' and the last 4 characters."""
    cfg = load(conn)
    for key in SECRETS:
        value = cfg.pop(key)
        cfg[f"{key}_set"] = bool(value)
        cfg[f"{key}_hint"] = f"…{value[-4:]}" if len(value) >= 8 else ""
    return cfg


def update(conn, changes: dict) -> None:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    if "page_size" in changes:
        n = changes["page_size"]
        if not isinstance(n, int) or not 1 <= n <= 1000:
            raise SettingsError("Page size must be a whole number from 1 to 1000")
    if "api_key" in changes:
        changes["api_key"] = str(changes["api_key"]).strip()
    for key, value in changes.items():
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
    conn.commit()
