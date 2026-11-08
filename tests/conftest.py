import pytest
from fastapi.testclient import TestClient

from optport import db, earnings, ibkr
from optport.main import app


class FakeTWS:
    """Stands in for TWS: fixed prices and quotes, no network."""

    def __init__(self, und=None, quotes=None, positions=None, connected=True):
        self.und = und or {}            # ticker -> price
        self.quotes = quotes or {}      # (ticker, expiry, right, strike) -> dict
        self.broker = positions or []
        self.connected = connected
        self.loop = None
        self.configured = None

    def status(self):
        return {'connected': self.connected, 'host': '127.0.0.1', 'port': 7496, 'client_id': 18,
                'error': None if self.connected else 'Nothing answers on 127.0.0.1:7496.',
                'last_attempt': None, 'connected_since': None}

    def test(self):
        return self.status()

    def configure(self, *a):
        self.configured = a

    def underlying_price(self, ticker):
        if ticker not in self.und:
            raise ibkr.TWSError(f"No price for {ticker} from IBKR.")
        return {'price': self.und[ticker], 'source': 'live'}

    def option_quotes(self, contracts):
        out = []
        for c in contracts:
            key = (c['ticker'], c['expiry'], c['right'], c['strike'])
            q = self.quotes.get(key)
            out.append({**c, **q, 'error': None} if q else {**c, 'error': f'IBKR does not know {key}.'})
        return out

    def positions(self):
        return self.broker

    def daily_closes(self, ticker, duration='2 Y'):
        return getattr(self, 'closes', [])


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A fresh database file per test; the app's own connections use it too (via OPTPORT_DB)."""
    path = str(tmp_path / 'test.db')
    monkeypatch.setenv('OPTPORT_DB', path)
    monkeypatch.setenv('OPTPORT_NO_BACKGROUND', '1')   # no background threads or external clients
    monkeypatch.setattr(earnings, 'fetch_dates', lambda t: [])
    ibkr.set_client(FakeTWS())
    db.init(path)
    c = db.connect(path)
    yield c
    c.close()
    ibkr.set_client(None)


@pytest.fixture
def client(conn):
    with TestClient(app) as c:
        yield c
