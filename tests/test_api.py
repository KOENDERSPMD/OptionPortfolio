from datetime import date, datetime

import pytest

from optport import earnings, ibkr, refresh
from tests.conftest import FakeTWS

LEG = {'qty': 3, 'right': 'P', 'strike': 55, 'expiry': '2027-01-15', 'avg_price': 7.40,
       'und_entry': 53.86, 'entry_date': '2026-09-14'}


def make(client, **kw):
    body = {'ticker': ' tgtx ', 'direction': 'short', 'stop': 60.29, 'target': 42, 'legs': [LEG], **kw}
    r = client.post('/api/positions', json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_position_with_legs(client):
    p = make(client, legs=[LEG, {**LEG, 'qty': -2, 'strike': 48, 'expiry': '2026-11-20', 'avg_price': 1.30,
                                 'entry_date': '2026-10-23'}])
    assert p['number'] == '#0001' and p['ticker'] == 'TGTX' and len(p['legs']) == 2
    assert {lg['number'] for lg in p['legs']} == {'#0001-01', '#0001-02'}
    assert p['m']['pos_risk'] == pytest.approx(2220 - 260)
    assert p['m']['pnl'] is None   # no quotes yet
    assert client.get('/api/portfolio').json()['totals']['positions'] == 1


def test_bad_input_is_refused(client):
    assert client.post('/api/positions', json={'ticker': '', 'direction': 'long'}).status_code == 422
    assert client.post('/api/positions', json={'ticker': 'A', 'direction': 'up'}).status_code == 422
    bad = client.post('/api/positions', json={'ticker': 'A', 'direction': 'long', 'legs': [{**LEG, 'qty': 0}]})
    assert bad.status_code == 400 and 'negative' in bad.json()['detail']
    assert client.post('/api/positions', json={'ticker': 'A', 'direction': 'long',
                                               'legs': [{**LEG, 'expiry': '2027-02-30'}]}).status_code == 422
    assert client.get('/api/positions/99').json()['detail'] == 'Position #0099 not found.'


def test_edit_position_and_legs(client):
    p = make(client)
    r = client.patch(f"/api/positions/{p['id']}", json={'stop': None, 'target': 40, 'notes': 'wait for earnings'})
    assert r.json()['stop'] is None and r.json()['target'] == 40
    assert client.patch(f"/api/positions/{p['id']}", json={'ticker': None}).status_code == 400
    p = client.post(f"/api/positions/{p['id']}/legs", json={**LEG, 'qty': -1, 'strike': 45}).json()
    assert len(p['legs']) == 2
    leg_id = next(lg['id'] for lg in p['legs'] if lg['strike'] == 45)
    p = client.patch(f'/api/legs/{leg_id}', json={'avg_price': 1.1, 'trading_class': ' tgtx '}).json()
    changed = next(lg for lg in p['legs'] if lg['id'] == leg_id)
    assert changed['avg_price'] == 1.1 and changed['trading_class'] == 'TGTX'
    assert client.patch(f'/api/legs/{leg_id}', json={'qty': 0}).status_code == 400
    assert len(client.delete(f'/api/legs/{leg_id}').json()['legs']) == 1
    assert client.delete(f"/api/positions/{p['id']}").status_code == 204
    assert client.get('/api/portfolio?show=all').json()['positions'] == []


def test_partial_and_full_close(client):
    p = make(client)
    leg_id = p['legs'][0]['id']
    assert client.post(f'/api/legs/{leg_id}/close', json={'price': 9, 'date': '2026-11-01', 'qty': 4}).status_code == 400
    assert client.post(f'/api/legs/{leg_id}/close', json={'price': 9, 'date': '2026-01-01'}).status_code == 400
    p = client.post(f'/api/legs/{leg_id}/close', json={'price': 9.40, 'date': '2026-11-01', 'qty': 1}).json()
    open_leg = next(lg for lg in p['legs'] if lg['close_price'] is None)
    closed = next(lg for lg in p['legs'] if lg['close_price'] is not None)
    assert open_leg['qty'] == 2 and closed['qty'] == 1 and closed['m']['realized'] == pytest.approx(200)
    assert p['m']['open'] and p['m']['realized'] == pytest.approx(200)

    p = client.post(f"/api/legs/{open_leg['id']}/close", json={'price': 5, 'date': '2026-11-02'}).json()
    assert not p['m']['open'] and p['m']['realized'] == pytest.approx(200 - 480)
    assert client.get('/api/portfolio').json()['positions'] == []
    assert len(client.get('/api/portfolio?show=closed').json()['positions']) == 1
    assert client.post(f"/api/legs/{open_leg['id']}/close", json={'price': 5, 'date': '2026-11-02'}).status_code == 400
    p = client.post(f"/api/legs/{open_leg['id']}/reopen").json()
    assert p['m']['open']


def test_refresh_fills_prices_quotes_earnings_and_broker_check(client, monkeypatch):
    p = make(client, legs=[LEG, {**LEG, 'qty': -2, 'strike': 48, 'expiry': '2026-11-20', 'avg_price': 1.30}])
    make(client, ticker='SPX', direction='long', stop=None, target=None,
         legs=[{**LEG, 'qty': 1, 'right': 'C', 'strike': 7000, 'trading_class': 'SPXW'}])
    ibkr.set_client(FakeTWS(
        und={'TGTX': 59.83},
        quotes={('TGTX', '2027-01-15', 'P', 55.0): {'bid': 4.5, 'ask': 4.6, 'delta': -0.3},
                ('TGTX', '2026-11-20', 'P', 48.0): {'bid': 1.4, 'ask': 1.6, 'delta': -0.05},
                ('SPX', '2027-01-15', 'C', 7000.0): {'last': 50.0, 'und_price': 6800.0}},
        positions=[{'ticker': 'TGTX', 'expiry': '2027-01-15', 'right': 'P', 'strike': 55.0, 'qty': 3},
                   {'ticker': 'TGTX', 'expiry': '2026-11-20', 'right': 'P', 'strike': 48.0, 'qty': -1}]))
    asked = []
    monkeypatch.setattr(earnings, 'fetch_dates', lambda t: asked.append(t) or [date(2020, 1, 1), date(2099, 11, 9)])
    refresh.start(wait=True)

    data = client.get('/api/portfolio').json()
    assert data['refresh']['status'] == 'done' and '3 option quote(s)' in data['refresh']['message']
    assert 'SPX' in data['refresh']['message']        # no index price: noted, then taken from the option
    tgtx = next(x for x in data['positions'] if x['ticker'] == 'TGTX')
    spx = next(x for x in data['positions'] if x['ticker'] == 'SPX')
    assert tgtx['und']['price'] == 59.83 and spx['und'] == {**spx['und'], 'price': 6800.0, 'source': 'option'}
    assert tgtx['earnings']['date'] == '2099-11-09' and asked == ['TGTX']   # indexes have no earnings
    assert tgtx['m']['stop_state'] == 'near'
    assert tgtx['m']['pnl'] == pytest.approx((1365 - 300) - (2220 - 260))
    short = next(lg for lg in tgtx['legs'] if lg['qty'] == -2)
    assert short['broker_qty'] == -1 and short['broker_mismatch']
    assert not next(lg for lg in tgtx['legs'] if lg['qty'] == 3)['broker_mismatch']
    assert spx['legs'][0]['broker_qty'] == 0 and spx['legs'][0]['broker_mismatch']
    assert data['totals']['positions'] == 2 and data['totals']['missing'] == 0


def test_refresh_without_tws_keeps_old_prices(client, monkeypatch):
    make(client)
    ibkr.set_client(FakeTWS(connected=False))
    refresh.start(wait=True)
    job = client.get('/api/refresh').json()['job']
    assert job['status'] == 'error' and 'Not connected to TWS' in job['message']


def test_market_hours():
    ny = refresh.NEW_YORK
    assert refresh.market_open(datetime(2026, 11, 9, 10, 0, tzinfo=ny))
    assert not refresh.market_open(datetime(2026, 11, 9, 9, 0, tzinfo=ny))
    assert not refresh.market_open(datetime(2026, 11, 8, 12, 0, tzinfo=ny))   # Sunday


def test_settings_and_tws(client):
    s = client.put('/api/settings', json={'ib_port': 4001, 'interest_rate': 0.045}).json()
    assert s['ib_port'] == 4001 and ibkr.client().configured == ('127.0.0.1', 4001, 18)
    assert client.put('/api/settings', json={'ib_port': 'x'}).status_code == 400
    assert client.put('/api/settings', json={'refresh_minutes': 1.5}).status_code == 400
    assert client.put('/api/settings', json={'nope': 1}).status_code == 400
    assert client.get('/api/tws').json()['connected'] is True


def test_health_busy_and_index(client):
    assert client.get('/api/health').json() == {'ok': True, 'app': 'optport'}
    assert client.get('/api/busy').json() == {'busy': []}
    assert client.get('/').status_code == 200
