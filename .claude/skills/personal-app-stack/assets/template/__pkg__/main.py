"""FastAPI app: JSON API under /api, the single-page UI from __pkg__/web."""

import os
import signal
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, settings

WEB_DIR = Path(__file__).resolve().parent / "web"
STATUSES = ["open", "done"]


@asynccontextmanager
async def lifespan(_app):
    db.init()
    # Start background threads and clients for external services here (not during tests:
    # conftest sets __ENV___NO_BACKGROUND=1), and stop them cleanly after the yield.
    yield


app = FastAPI(title="__TITLE__", lifespan=lifespan)


def get_conn():
    """One connection per request."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_item_row(conn, item_id: int):
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Item #{item_id:04d} not found")
    return row


def item_dict(row) -> dict:
    return {**dict(row), "number": f"#{row['id']:04d}"}


# ---- items --------------------------------------------------------------------------------------

class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["open", "done"] | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)  # null clears it


@app.get("/api/items")
def list_items(show: Literal["open", "done", "all"] = "open", q: str = "", conn=Depends(get_conn)):
    where, args = [], []
    if show != "all":
        where.append("status = ?")
        args.append(show)
    if q.strip():
        where.append("name LIKE ?")
        args.append(f"%{q.strip()}%")
    sql = "SELECT * FROM items" + (" WHERE " + " AND ".join(where) if where else "")
    return [item_dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]


@app.post("/api/items", status_code=201)
def create_item(body: ItemCreate, conn=Depends(get_conn)):
    now = db.now_iso()
    cur = conn.execute("INSERT INTO items (name, created_at, updated_at) VALUES (?, ?, ?)",
                       (body.name.strip(), now, now))
    conn.commit()
    return item_dict(get_item_row(conn, cur.lastrowid))


@app.get("/api/items/{item_id}")
def get_item(item_id: int, conn=Depends(get_conn)):
    return item_dict(get_item_row(conn, item_id))


@app.patch("/api/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, conn=Depends(get_conn)):
    get_item_row(conn, item_id)
    # Only fields that were sent; an explicit null clears a nullable field, but not a required one.
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "status", "notes"):
        if key in fields and fields[key] is None:
            raise HTTPException(400, f"{key.capitalize()} cannot be empty")
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE items SET {sets}, updated_at = ? WHERE id = ?",
                     [*fields.values(), db.now_iso(), item_id])
        conn.commit()
    return item_dict(get_item_row(conn, item_id))


@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: int, conn=Depends(get_conn)):
    get_item_row(conn, item_id)
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()


# ---- settings -----------------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings(conn=Depends(get_conn)):
    return settings.public(conn)


@app.put("/api/settings")
def put_settings(body: dict, conn=Depends(get_conn)):
    try:
        settings.update(conn, body)
    except settings.SettingsError as e:
        raise HTTPException(400, str(e)) from e
    return settings.public(conn)


# ---- app lifecycle ------------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """start.sh checks this to know the app (not some other program) is up on the port."""
    return {"ok": True, "app": "__pkg__"}


def busy(conn) -> list[str]:
    """Work that Quit would interrupt; the UI asks before closing."""
    n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
    return [f"{n} job(s) still running"] if n else []


@app.get("/api/busy")
def get_busy(conn=Depends(get_conn)):
    return {"busy": busy(conn)}


@app.post("/api/shutdown", status_code=202)
def shutdown(request: Request):
    """Stop the app, only from the machine it runs on (an SSH tunnel counts as local)."""
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "The app can only be closed from the computer it runs on.")
    # Uvicorn handles SIGINT as a normal, clean shutdown (exit code 0, so systemd won't restart it).
    threading.Timer(0.5, os.kill, args=(os.getpid(), signal.SIGINT)).start()
    return {"ok": True}


# ---- UI -----------------------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    import uvicorn

    host = os.environ.get("__ENV___HOST", "127.0.0.1")
    port = int(os.environ.get("__ENV___PORT", "__PORT__"))
    uvicorn.run("__pkg__.main:app", host=host, port=port)


if __name__ == "__main__":
    run()
