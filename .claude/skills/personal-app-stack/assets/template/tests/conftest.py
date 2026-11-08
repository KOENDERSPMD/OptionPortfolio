import pytest
from fastapi.testclient import TestClient

from __pkg__ import db
from __pkg__.main import app


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A fresh database file per test; the app's own connections use it too (via __ENV___DB)."""
    path = str(tmp_path / 'test.db')
    monkeypatch.setenv('__ENV___DB', path)
    monkeypatch.setenv('__ENV___NO_BACKGROUND', '1')   # no background threads or external clients
    monkeypatch.delenv('__ENV___API_KEY', raising=False)
    db.init(path)
    c = db.connect(path)
    yield c
    c.close()


@pytest.fixture
def client(conn):
    with TestClient(app) as c:
        yield c
