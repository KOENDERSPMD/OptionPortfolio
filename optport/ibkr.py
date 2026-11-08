"""Connection to Interactive Brokers TWS / IB Gateway (read-only): prices, option quotes, positions.

Adapted from the Trade Idea Management System. ib_async runs on asyncio, so one background thread
owns an event loop and the IB connection; other threads call into it with `TWSClient.call()`.
While TWS is not reachable, the client retries quietly every RETRY_SECONDS.
"""

import asyncio
import logging
import math
import threading

from . import db

RETRY_SECONDS = 30
CONNECT_TIMEOUT = 6
REQUEST_TIMEOUT = 90
QUOTE_WAIT = 10        # seconds to wait for option quotes (delayed ones arrive more slowly)
BATCH = 40             # market data lines per batch, well inside IBKR's limit of 100

# Index options: the index and the exchange IBKR lists it on. Everything else is treated as a stock/ETF.
INDEXES = {"SPX": "CBOE", "XSP": "CBOE", "VIX": "CBOE", "DJX": "CBOE", "NDX": "NASDAQ", "RUT": "RUSSELL"}

INFO_CODES = {2103, 2104, 2105, 2106, 2107, 2108, 2119, 2150, 2158, 10167}
DELAYED_TYPES = {3, 4}   # IBKR market data types: 1 live, 2 frozen, 3 delayed, 4 delayed frozen

logging.getLogger("ib_async").setLevel(logging.CRITICAL)


class TWSError(Exception):
    pass


def ib_symbol(ticker: str) -> str:
    """IBKR writes share classes with a space: BRK.B -> BRK B."""
    return ticker.strip().upper().replace(".", " ").replace("-", " ")


def is_index(ticker: str) -> bool:
    return ticker.strip().upper() in INDEXES


def explain(code: int, message: str, symbol: str = "") -> str:
    """Turn a TWS error into something actionable."""
    if code == 200:
        return f"IBKR does not know {symbol!r} (no security definition). Check the ticker, strike and expiry."
    if "delayed market data is not enabled" in message.lower() or code == 10186:
        return (f"No market data subscription for {symbol}, and free delayed data is not switched on yet. In TWS, open "
                "any option quote and click Free Delayed Data once. ({message})")
    if code in (354, 10089, 10090, 10168) or (code == 162 and "permission" in message.lower()):
        return f"No market data permission for {symbol}: check your market data subscriptions at IBKR. ({message})"
    if code == 326:
        return "The client ID is already in use by another API connection. Choose another client ID in Settings."
    if code in (502, 504):
        return "Not connected to TWS."
    if code in (1100, 2110):
        return "TWS has lost its connection to IBKR. Check TWS."
    return f"TWS error {code}: {message}"


class TWSClient:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ib = None
        self.host, self.port, self.client_id = "127.0.0.1", 7496, 18
        self.last_error: str | None = None
        self.last_attempt: str | None = None
        self.connected_since: str | None = None
        self._errors: list[tuple[int, str]] = []
        self._connect_lock: asyncio.Lock | None = None
        self._started = threading.Event()

    # ---- lifecycle -------------------------------------------------------------------------------

    def start(self, host: str, port: int, client_id: int) -> None:
        self.host, self.port, self.client_id = host, port, client_id
        if self.loop:
            return
        threading.Thread(target=self._run_loop, name="tws", daemon=True).start()
        self._started.wait(5)
        asyncio.run_coroutine_threadsafe(self._monitor(), self.loop)

    def _run_loop(self) -> None:
        from ib_async import IB

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.ib = IB()
        self.ib.errorEvent += self._on_error
        self.ib.disconnectedEvent += self._on_disconnect
        self._connect_lock = asyncio.Lock()
        self._started.set()
        self.loop.run_forever()

    def call(self, coro_fn, timeout: float = REQUEST_TIMEOUT):
        if not self.loop:
            raise TWSError("The TWS connection is not started.")
        return asyncio.run_coroutine_threadsafe(coro_fn(), self.loop).result(timeout)

    def configure(self, host: str, port: int, client_id: int) -> None:
        """New connection settings: drop the current connection; the next call reconnects."""
        self.host, self.port, self.client_id = host, port, client_id
        if self.loop:
            self.call(self._disconnect, timeout=10)

    def stop(self) -> None:
        if self.loop:
            try:
                self.call(self._disconnect, timeout=5)
            except Exception:  # noqa: BLE001 - the app is closing anyway
                pass

    def _on_error(self, req_id, code, message, contract=None):
        if code not in INFO_CODES:
            self._errors.append((code, message))
            del self._errors[:-20]

    def _on_disconnect(self):
        self.connected_since = None

    async def _disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
        self.connected_since = None

    async def _monitor(self):
        while True:
            if not self.ib.isConnected():
                try:
                    await self._ensure_connected()
                except TWSError:
                    pass
            await asyncio.sleep(RETRY_SECONDS)

    async def _ensure_connected(self):
        async with self._connect_lock:
            if self.ib.isConnected():
                return
            from ib_async.ib import StartupFetch

            self.last_attempt = db.now_iso()
            self._errors.clear()
            try:
                await self.ib.connectAsync(self.host, self.port, clientId=self.client_id,
                                           timeout=CONNECT_TIMEOUT, readonly=True, fetchFields=StartupFetch(0))
            except ConnectionRefusedError:
                self.last_error = (f"Nothing answers on {self.host}:{self.port}. Is TWS or IB Gateway running and logged "
                                   "in, with the API enabled on this port (TWS 7496/7497, IB Gateway 4001/4002)?")
            except (asyncio.TimeoutError, TimeoutError):
                self.last_error = ("TWS / IB Gateway did not complete the connection. Check that this computer's address "
                                   "is a trusted IP in the API settings (or accept the connection prompt).")
            except Exception as e:  # noqa: BLE001 - shown in Settings
                codes = [c for c, _ in self._errors]
                self.last_error = explain(326, "") if 326 in codes else f"Could not connect to TWS: {e}"
            else:
                self.last_error = None
                self.connected_since = db.now_iso()
                # 4 = live where subscribed, otherwise free delayed quotes; after the close the last known ones.
                self.ib.reqMarketDataType(4)
                return
            if self.ib.isConnected():
                self.ib.disconnect()
            raise TWSError(self.last_error)

    # ---- public API ------------------------------------------------------------------------------

    def status(self) -> dict:
        return {"connected": bool(self.ib and self.ib.isConnected()), "host": self.host, "port": self.port,
                "client_id": self.client_id, "error": self.last_error, "last_attempt": self.last_attempt,
                "connected_since": self.connected_since}

    def test(self) -> dict:
        try:
            self.call(self._ensure_connected, timeout=CONNECT_TIMEOUT + 5)
        except TWSError:
            pass
        return self.status()

    def underlying_price(self, ticker: str) -> dict:
        """{'price', 'source'}: live/delayed quote, else the last daily close."""
        return self.call(lambda: self._underlying_price(ticker))

    def option_quotes(self, contracts: list[dict]) -> list[dict]:
        """Quotes for specific options: dicts with ticker, expiry (YYYY-MM-DD), right, strike and
        optionally trading_class. Returns one dict per input, with `error` set when it failed."""
        return self.call(lambda: self._option_quotes(contracts), timeout=REQUEST_TIMEOUT + 30)

    def positions(self) -> list[dict]:
        return self.call(self._positions)

    def daily_closes(self, ticker: str, duration: str = "2 Y") -> list[dict]:
        """[{'date': 'YYYY-MM-DD', 'close'}] from the price history (needs no market data subscription)."""
        return self.call(lambda: self._daily_closes(ticker, duration))

    # ---- implementation ----------------------------------------------------------------------------

    async def _underlying(self, ticker: str):
        from ib_async import Index, Stock

        await self._ensure_connected()
        symbol = ib_symbol(ticker)
        self._errors.clear()
        if is_index(symbol):
            found = await self.ib.qualifyContractsAsync(Index(symbol, INDEXES[symbol], "USD"))
        else:
            found = await self.ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"), returnAll=True)
        contract = found[0] if found else None
        if isinstance(contract, list):  # ambiguous: prefer the primary US listing
            contract = next((c for c in contract if c and c.primaryExchange in ("NYSE", "NASDAQ", "ARCA", "AMEX", "BATS")),
                            contract[0] if contract else None)
        if not contract or not contract.conId:
            raise TWSError(self._error_text(symbol) or f"IBKR does not know {symbol!r}.")
        return contract

    async def _underlying_price(self, ticker: str) -> dict:
        contract = await self._underlying(ticker)
        t = self.ib.reqMktData(contract, "", False, False)
        try:
            await wait_for(lambda: num(t.marketPrice()) is not None, 5)
        finally:
            self.ib.cancelMktData(contract)
        price = num(t.marketPrice()) or num(t.last) or num(t.close)
        if price is not None:
            return {"price": price, "source": "delayed" if getattr(t, "marketDataType", 1) in DELAYED_TYPES else "live"}
        # No quote (no subscription): the last daily close needs none.
        bars = await self.ib.reqHistoricalDataAsync(contract, endDateTime="", durationStr="5 D", barSizeSetting="1 day",
                                                    whatToShow="TRADES", useRTH=True, formatDate=1, timeout=30)
        if not bars:
            raise TWSError(self._error_text(contract.symbol) or f"No price for {contract.symbol} from IBKR.")
        return {"price": bars[-1].close, "source": "close"}

    async def _daily_closes(self, ticker: str, duration: str) -> list[dict]:
        contract = await self._underlying(ticker)
        bars = await self.ib.reqHistoricalDataAsync(contract, endDateTime="", durationStr=duration, barSizeSetting="1 day",
                                                    whatToShow="TRADES", useRTH=True, formatDate=1, timeout=60)
        if not bars:
            raise TWSError(self._error_text(contract.symbol) or f"IBKR returned no price history for {contract.symbol}.")
        return [{"date": str(b.date)[:10], "close": b.close} for b in bars]

    async def _option_quotes(self, wanted: list[dict]) -> list[dict]:
        from ib_async import Option

        await self._ensure_connected()
        out, chosen = [], []
        for w in wanted:
            symbol = ib_symbol(w["ticker"])
            self._errors.clear()
            opt = Option(symbol, w["expiry"].replace("-", ""), w["strike"], w["right"],
                         "SMART", currency="USD", tradingClass=w.get("trading_class") or "")
            found = await self.ib.qualifyContractsAsync(opt, returnAll=True)
            c = found[0] if found else None
            if isinstance(c, list):  # several classes (e.g. SPX and SPXW): the standard one, else the first
                c = next((x for x in c if x.tradingClass == symbol), c[0] if c else None)
            if not c or not c.conId:
                out.append({**w, "error": self._error_text(symbol) or
                            f"IBKR does not know the {symbol} {w['expiry']} {w['strike']:g} {w['right']} option."})
                continue
            chosen.append((w, c))
        for i in range(0, len(chosen), BATCH):
            batch = chosen[i:i + BATCH]
            tickers = [self.ib.reqMktData(c, "", False, False) for _, c in batch]
            try:
                await wait_for(lambda: all(t.modelGreeks is not None and
                                           (num(t.bid) is not None or num(t.close) is not None) for t in tickers),
                               QUOTE_WAIT)
            finally:
                for _, c in batch:
                    self.ib.cancelMktData(c)
            for (w, c), t in zip(batch, tickers):
                g = t.modelGreeks
                out.append({**w, "trading_class": c.tradingClass,
                            "bid": price_or_none(t.bid), "ask": price_or_none(t.ask),
                            "last": price_or_none(t.last), "close": price_or_none(t.close),
                            "delta": num(g.delta) if g else None, "impl_vol": num(g.impliedVol) if g else None,
                            "und_price": num(g.undPrice) if g else None,
                            "delayed": getattr(t, "marketDataType", 1) in DELAYED_TYPES, "error": None})
        return out

    async def _positions(self) -> list[dict]:
        await self._ensure_connected()
        out = []
        for p in await self.ib.reqPositionsAsync():
            c = p.contract
            if c.secType not in ("OPT", "FOP") or not p.position:
                continue
            e = c.lastTradeDateOrContractMonth or ""
            out.append({"ticker": c.symbol, "expiry": f"{e[:4]}-{e[4:6]}-{e[6:8]}" if len(e) == 8 else e,
                        "strike": num(c.strike), "right": (c.right or "")[:1], "qty": num(p.position)})
        return out

    def _error_text(self, symbol: str) -> str | None:
        if not self._errors:
            return None
        code, msg = self._errors[-1]
        return explain(code, msg, symbol)


def num(v):
    """IBKR uses NaN (and sometimes -1) for 'no value'."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def price_or_none(v):
    f = num(v)
    return f if f is not None and f >= 0 else None


async def wait_for(cond, timeout: float) -> bool:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if cond():
            return True
        await asyncio.sleep(0.15)
    return cond()


_client: TWSClient | None = None


def client() -> TWSClient:
    global _client
    if _client is None:
        _client = TWSClient()
    return _client


def set_client(c) -> None:
    """For tests."""
    global _client
    _client = c
