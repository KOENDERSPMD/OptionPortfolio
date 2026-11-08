"""FastAPI app: JSON API under /api, the single-page UI from optport/web."""

import hashlib
import os
import signal
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db, ibkr, portfolio, refresh, settings

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(_app):
    db.init()
    background = os.environ.get("OPTPORT_NO_BACKGROUND") != "1"
    if background:
        with db.closing(db.connect()) as conn:
            cfg = settings.load(conn)
        ibkr.client().start(cfg["ib_host"], cfg["ib_port"], cfg["ib_client_id"])
        refresh.scheduler.start()
    yield
    if background:
        refresh.scheduler.stop()
        ibkr.client().stop()


app = FastAPI(title="Option Portfolio", lifespan=lifespan)


def code_version() -> str:
    """Fingerprint of the server code on disk (after a git pull it changes; the running server doesn't)."""
    h = hashlib.sha1()
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:12]


RUNNING_VERSION = code_version()


@app.middleware("http")
async def no_stale_ui(request: Request, call_next):
    """The page files are read from disk; make the browser check for newer ones after an update."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def get_conn():
    """One connection per request."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def domain_errors(fn):
    """Run fn, turning the domain modules' exceptions into HTTP errors with their sentence."""
    try:
        return fn()
    except portfolio.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except portfolio.RuleError as e:
        raise HTTPException(400, str(e)) from e


# ---- input models -----------------------------------------------------------------------------------

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _valid_date(v):
    if v is None:
        return v
    try:
        date.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"{v} is not a valid date (use YYYY-MM-DD)") from e
    return v


class LegIn(BaseModel):
    qty: int = Field(ge=-10_000, le=10_000)
    right: Literal["C", "P"]
    strike: float = Field(gt=0, le=1_000_000)
    expiry: str = Field(pattern=ISO_DATE)
    avg_price: float = Field(ge=0, le=1_000_000)
    und_entry: float | None = Field(default=None, gt=0, le=1_000_000)
    entry_date: str = Field(pattern=ISO_DATE)
    multiplier: int = Field(default=100, ge=1, le=10_000)
    trading_class: str | None = Field(default=None, max_length=12)

    _dates = field_validator("expiry", "entry_date")(_valid_date)


class LegUpdate(BaseModel):
    qty: int | None = Field(default=None, ge=-10_000, le=10_000)
    right: Literal["C", "P"] | None = None
    strike: float | None = Field(default=None, gt=0, le=1_000_000)
    expiry: str | None = Field(default=None, pattern=ISO_DATE)
    avg_price: float | None = Field(default=None, ge=0, le=1_000_000)
    und_entry: float | None = Field(default=None, gt=0, le=1_000_000)
    entry_date: str | None = Field(default=None, pattern=ISO_DATE)
    multiplier: int | None = Field(default=None, ge=1, le=10_000)
    trading_class: str | None = Field(default=None, max_length=12)

    _dates = field_validator("expiry", "entry_date")(_valid_date)


class PositionIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, pattern=r"^\s*[A-Za-z0-9.\- ]+\s*$")
    direction: Literal["long", "short"]
    stop: float | None = Field(default=None, gt=0, le=1_000_000)
    target: float | None = Field(default=None, gt=0, le=1_000_000)
    notes: str = Field(default="", max_length=20_000)
    legs: list[LegIn] = Field(default_factory=list, max_length=12)


class PositionUpdate(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=12, pattern=r"^\s*[A-Za-z0-9.\- ]+\s*$")
    direction: Literal["long", "short"] | None = None
    stop: float | None = Field(default=None, gt=0, le=1_000_000)
    target: float | None = Field(default=None, gt=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=20_000)


class CloseIn(BaseModel):
    price: float = Field(ge=0, le=1_000_000)
    date: str = Field(pattern=ISO_DATE)
    qty: int | None = Field(default=None, ge=1, le=10_000)   # contracts to close; empty = all

    _dates = field_validator("date")(_valid_date)


REQUIRED = {"ticker", "direction", "notes", "qty", "right", "strike", "expiry", "avg_price", "entry_date", "multiplier"}


def changes(body: BaseModel) -> dict:
    """Only the fields that were sent; an explicit null clears a nullable field, not a required one."""
    fields = body.model_dump(exclude_unset=True)
    for key in REQUIRED & set(fields):
        if fields[key] is None:
            raise HTTPException(400, f"{key.replace('_', ' ').capitalize()} cannot be empty.")
    return fields


# ---- portfolio --------------------------------------------------------------------------------------

def one_position(conn, pos_id: int) -> dict:
    data = portfolio.build(conn, [pos_id], show="all")
    if not data["positions"]:
        raise HTTPException(404, f"Position #{pos_id:04d} not found.")
    return data["positions"][0]


@app.get("/api/portfolio")
def get_portfolio(show: Literal["open", "closed", "all"] = "open", conn=Depends(get_conn)):
    data = portfolio.build(conn, show=show)
    data["refresh"] = refresh.last_job(conn)
    return data


@app.post("/api/positions", status_code=201)
def create_position(body: PositionIn, conn=Depends(get_conn)):
    data = body.model_dump()
    data["legs"] = [lg.model_dump() for lg in body.legs]
    pos_id = domain_errors(lambda: portfolio.create_position(conn, data))
    return one_position(conn, pos_id)


@app.get("/api/positions/{pos_id}")
def get_position(pos_id: int, conn=Depends(get_conn)):
    return one_position(conn, pos_id)


@app.patch("/api/positions/{pos_id}")
def update_position(pos_id: int, body: PositionUpdate, conn=Depends(get_conn)):
    domain_errors(lambda: portfolio.update_position(conn, pos_id, changes(body)))
    return one_position(conn, pos_id)


@app.delete("/api/positions/{pos_id}", status_code=204)
def delete_position(pos_id: int, conn=Depends(get_conn)):
    domain_errors(lambda: portfolio.delete_position(conn, pos_id))


@app.post("/api/positions/{pos_id}/legs", status_code=201)
def add_leg(pos_id: int, body: LegIn, conn=Depends(get_conn)):
    domain_errors(lambda: portfolio.add_leg(conn, pos_id, body.model_dump()))
    return one_position(conn, pos_id)


@app.patch("/api/legs/{leg_id}")
def update_leg(leg_id: int, body: LegUpdate, conn=Depends(get_conn)):
    pos_id = domain_errors(lambda: portfolio.update_leg(conn, leg_id, changes(body)))
    return one_position(conn, pos_id)


@app.delete("/api/legs/{leg_id}")
def delete_leg(leg_id: int, conn=Depends(get_conn)):
    pos_id = domain_errors(lambda: portfolio.delete_leg(conn, leg_id))
    return one_position(conn, pos_id)


@app.post("/api/legs/{leg_id}/close")
def close_leg(leg_id: int, body: CloseIn, conn=Depends(get_conn)):
    pos_id = domain_errors(lambda: portfolio.close_leg(conn, leg_id, body.qty, body.price, body.date))
    return one_position(conn, pos_id)


@app.post("/api/legs/{leg_id}/reopen")
def reopen_leg(leg_id: int, conn=Depends(get_conn)):
    pos_id = domain_errors(lambda: portfolio.reopen_leg(conn, leg_id))
    return one_position(conn, pos_id)


# ---- prices -----------------------------------------------------------------------------------------

@app.post("/api/refresh", status_code=202)
def start_refresh(earnings: bool = True):
    """Refresh prices now; with earnings=true also the earnings dates, even when fetched today."""
    try:
        job_id = refresh.start(force_earnings=earnings)
    except refresh.Busy as e:
        raise HTTPException(409, str(e)) from e
    return {"job_id": job_id}


@app.get("/api/refresh")
def refresh_status(conn=Depends(get_conn)):
    return {"job": refresh.last_job(conn), "market_open": refresh.market_open()}


@app.get("/api/tws")
def tws_status():
    return ibkr.client().status()


@app.post("/api/tws/test")
def tws_test():
    return ibkr.client().test()


# ---- settings ---------------------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings(conn=Depends(get_conn)):
    return settings.public(conn)


@app.put("/api/settings")
def put_settings(body: dict, conn=Depends(get_conn)):
    before = settings.load(conn)
    try:
        settings.update(conn, body)
    except settings.SettingsError as e:
        raise HTTPException(400, str(e)) from e
    cfg = settings.load(conn)
    keys = ("ib_host", "ib_port", "ib_client_id")
    if any(before[k] != cfg[k] for k in keys):
        ibkr.client().configure(*(cfg[k] for k in keys))
    return settings.public(conn)


# ---- app lifecycle ----------------------------------------------------------------------------------

@app.get("/api/health")
def health():
    """start.sh checks this to know the app (not some other program) is up on the port."""
    return {"ok": True, "app": "optport"}


@app.get("/api/version")
def get_version():
    """outdated = the code on disk is newer than this running server: the app needs a restart."""
    return {"running": RUNNING_VERSION, "outdated": code_version() != RUNNING_VERSION}


def busy(conn) -> list[str]:
    """Work that Quit would interrupt; the UI asks before closing."""
    n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()[0]
    return ["a price refresh is still running"] if n else []


@app.get("/api/busy")
def get_busy(conn=Depends(get_conn)):
    return {"busy": busy(conn)}


@app.post("/api/shutdown", status_code=202)
def shutdown(request: Request):
    """Stop the app, only from the machine it runs on (an SSH tunnel counts as local)."""
    if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "The app can only be closed from the computer it runs on.")
    threading.Timer(0.5, os.kill, args=(os.getpid(), signal.SIGINT)).start()
    return {"ok": True}


# ---- UI ---------------------------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    import uvicorn

    host = os.environ.get("OPTPORT_HOST", "127.0.0.1")
    port = int(os.environ.get("OPTPORT_PORT", "8771"))
    uvicorn.run("optport.main:app", host=host, port=port)


if __name__ == "__main__":
    run()
