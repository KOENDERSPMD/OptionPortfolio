from datetime import date, datetime

import pytest

from optport import db, ibkr, performance, refresh
from tests.conftest import FakeTWS

NY = refresh.NEW_YORK
LEG = {'qty': 2, 'right': 'C', 'strike': 100, 'expiry': '2027-01-15', 'avg_price': 5.0,
       'und_entry': 98, 'entry_date': '2026-09-01', 'commission': 2.6}


def test_due_date():
    assert performance.due_date(datetime(2026, 11, 9, 12, 0, tzinfo=NY)) is None            # Monday, open
    assert performance.due_date(datetime(2026, 11, 9, 17, 0, tzinfo=NY)) == '2026-11-09'    # Monday evening
    assert performance.due_date(datetime(2026, 11, 10, 8, 0, tzinfo=NY)) == '2026-11-09'    # Tuesday morning
    assert performance.due_date(datetime(2026, 11, 8, 12, 0, tzinfo=NY)) == '2026-11-06'    # Sunday -> Friday
    assert performance.due_date(datetime(2026, 11, 9, 8, 0, tzinfo=NY)) == '2026-11-06'     # Monday early -> Friday


def test_commissions_and_partial_close(client):
    p = client.post('/api/positions', json={'ticker': 'ABC', 'direction': 'long', 'legs': [LEG]}).json()
    leg_id = p['legs'][0]['id']
    p = client.post(f'/api/legs/{leg_id}/close', json={'qty': 1, 'price': 8, 'date': '2026-10-01', 'commission': 1.3}).json()
    closed = next(lg for lg in p['legs'] if lg['close_price'] is not None)
    still = next(lg for lg in p['legs'] if lg['close_price'] is None)
    assert closed['commission'] == 1.3 and still['commission'] == 1.3       # opening commission shared
    assert closed['m']['realized'] == pytest.approx(300 - 2.6)
    assert p['m']['open_commission'] == pytest.approx(1.3)
    # correcting a closed leg: both price and date, or neither
    assert client.patch(f"/api/legs/{closed['id']}", json={'close_date': None}).status_code == 400
    p = client.patch(f"/api/legs/{closed['id']}", json={'close_price': 9}).json()
    assert next(lg for lg in p['legs'] if lg['id'] == closed['id'])['m']['realized'] == pytest.approx(400 - 2.6)


def setup_history(conn):
    """A position opened in September; snapshots on three days; one leg closed on the 2nd day."""
    from optport import portfolio
    pid = portfolio.create_position(conn, {'ticker': 'ABC', 'direction': 'long', 'stop': None, 'target': None,
                                           'legs': [dict(LEG, commission=None), dict(LEG, qty=1, strike=110, avg_price=2.0, commission=None)]})
    legs = [r['id'] for r in conn.execute('SELECT id FROM legs ORDER BY id')]
    for day, unreal in [('2026-10-01', 100.0), ('2026-10-02', 50.0), ('2026-10-05', 150.0)]:
        conn.execute("INSERT INTO snapshots (date, positions, pos_risk, pos_size, unrealized, open_commission, realized, "
                     "taken_at) VALUES (?, 1, 1000, 1100, ?, 0, 0, 'x')", (day, unreal))
    portfolio.close_leg(conn, legs[1], None, 3.0, '2026-10-02')      # +100 realized on 2 Oct
    performance.store_bench(conn, 'SPY', [{'date': '2026-09-30', 'close': 500.0}, {'date': '2026-10-01', 'close': 505.0},
                                          {'date': '2026-10-02', 'close': 510.0}, {'date': '2026-10-05', 'close': 490.0}])
    conn.commit()
    return pid


def test_series_and_benchmark(client, conn):
    setup_history(conn)
    client.put('/api/settings', json={'capital': 10000})
    d = performance.build(conn, 'all', today=date(2026, 10, 5))
    assert [p['date'] for p in d['series']] == ['2026-10-01', '2026-10-02', '2026-10-05']   # today's snapshot exists
    assert [p['total'] for p in d['series']] == [100.0, 150.0, 250.0]                         # realized 100 from 2 Oct
    assert d['series'][-1]['pct'] == pytest.approx(0.025)
    assert d['series'][0]['bench_pct'] == 0 and d['series'][-1]['bench_pct'] == pytest.approx(490 / 505 - 1)
    assert d['summary']['realized'] == 100 and d['summary']['snapshots'] == 3

    later = performance.build(conn, 'all', today=date(2026, 10, 6))
    assert later['series'][-1]['now'] and later['series'][-1]['date'] == '2026-10-06'       # live point added

    # a period counts from the last point before it starts
    p = performance.build(conn, '1m', today=date(2026, 11, 3))
    assert p['start'] == '2026-10-03' and p['series'][0]['date'] == '2026-10-05'
    assert p['series'][0]['pnl'] == pytest.approx(250 - 150) and p['summary']['realized'] == 0
    assert p['series'][0]['bench_pct'] == pytest.approx(490 / 510 - 1)


def test_closed_position_stats(client, conn):
    from optport import portfolio
    mk = lambda t, d, legs: portfolio.create_position(conn, {'ticker': t, 'direction': d, 'stop': None, 'target': None, 'legs': legs})
    a = mk('AAA', 'long', [dict(LEG, commission=None)])                       # cost 1000
    b = mk('BBB', 'short', [dict(LEG, right='P', commission=None)])
    mk('CCC', 'long', [dict(LEG)])                                            # stays open
    for pid, price, day in [(a, 7.0, '2026-10-10'), (b, 3.0, '2026-11-02')]:
        leg = conn.execute('SELECT id FROM legs WHERE position_id = ?', (pid,)).fetchone()['id']
        portfolio.close_leg(conn, leg, None, price, day)
    d = client.get('/api/performance').json()
    s = d['stats']
    assert s['count'] == 2 and s['wins'] == 1 and s['win_rate'] == 0.5
    assert s['avg_win'] == 400 and s['avg_loss'] == -400 and s['profit_factor'] == 1 and s['total'] == 0
    assert [c['ticker'] for c in d['closed']] == ['BBB', 'AAA'] and d['closed'][1]['return'] == pytest.approx(0.4)
    assert d['closed'][1]['days'] == 39
    assert {m['key'] for m in d['by_month']} == {'2026-10', '2026-11'}
    assert [g['key'] for g in d['by_direction']] == ['long', 'short'] and d['by_ticker'][0]['key'] == 'AAA'
    assert client.get('/api/performance?period=5y').status_code == 422


def test_snapshot_if_due(client, conn, monkeypatch):
    monday_evening = datetime(2026, 11, 9, 17, 0, tzinfo=NY)
    assert performance.snapshot_if_due(datetime(2026, 11, 9, 12, 0, tzinfo=NY)) == 'market open'
    client.post('/api/positions', json={'ticker': 'ABC', 'direction': 'long', 'legs': [LEG]})
    ibkr.set_client(FakeTWS(connected=False))
    assert performance.snapshot_if_due(monday_evening) == 'no prices'          # no stale snapshot
    fake = FakeTWS(und={'ABC': 101.0}, quotes={('ABC', '2027-01-15', 'C', 100.0): {'bid': 6, 'ask': 6.2}})
    fake.closes = [{'date': '2026-11-06', 'close': 600.0}, {'date': '2026-11-09', 'close': 605.0}]
    ibkr.set_client(fake)
    assert performance.snapshot_if_due(monday_evening) == 'saved'
    row = dict(conn.execute('SELECT * FROM snapshots').fetchone())
    assert row['date'] == '2026-11-09' and row['unrealized'] == pytest.approx(2 * 610 - 1000)
    assert row['open_commission'] == pytest.approx(2.6)
    assert performance.snapshot_if_due(monday_evening) == 'already saved'
    fake.closes = [{'date': '2026-11-25', 'close': 600.0}]
    assert performance.snapshot_if_due(datetime(2026, 11, 26, 17, 0, tzinfo=NY)) == 'holiday'   # Thanksgiving


def test_migration_adds_commission_columns(tmp_path):
    path = str(tmp_path / 'old.db')
    with db.closing(db.connect(path)) as c:
        c.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, direction TEXT NOT NULL, "
                  "stop REAL, target REAL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("CREATE TABLE legs (id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER NOT NULL, qty INTEGER NOT NULL, "
                  "right TEXT NOT NULL, strike REAL NOT NULL, expiry TEXT NOT NULL, avg_price REAL NOT NULL, und_entry REAL, "
                  "entry_date TEXT NOT NULL, multiplier INTEGER NOT NULL DEFAULT 100, trading_class TEXT, close_price REAL, "
                  "close_date TEXT, created_at TEXT NOT NULL)")
        c.execute("INSERT INTO positions (ticker, direction, created_at, updated_at) VALUES ('KEEP', 'long', 'x', 'x')")
        c.execute("INSERT INTO legs (position_id, qty, right, strike, expiry, avg_price, entry_date, created_at) "
                  "VALUES (1, 1, 'C', 10, '2027-01-15', 1, '2026-10-01', 'x')")
        c.commit()
    db.init(path)
    with db.closing(db.connect(path)) as c:
        cols = {r['name'] for r in c.execute('PRAGMA table_info(legs)')}
        assert {'commission', 'close_commission'} <= cols
        assert c.execute('SELECT ticker FROM positions').fetchone()['ticker'] == 'KEEP'
