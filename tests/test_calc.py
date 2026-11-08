"""The arithmetic, checked against rows of the owner's portfolio sheet."""
from datetime import date

import pytest

from optport import calc

TODAY = date(2026, 11, 7)
CFG = {'stop_warn_pct': 3.0}


def leg(**kw):
    base = {'qty': 1, 'right': 'C', 'strike': 100.0, 'expiry': '2027-01-15', 'avg_price': 1.0,
            'und_entry': None, 'multiplier': 100, 'close_price': None}
    return {**base, **kw}


def test_tgtx_put_matches_the_sheet():
    # TGTX: 3 puts 55, 15-Jan-27, av. price 7.40, stock 53.86 at entry; now 4.55 with the stock at 59.83
    m = calc.leg_metrics(leg(qty=3, right='P', strike=55, avg_price=7.40, und_entry=53.86),
                         59.83, {'bid': 4.50, 'ask': 4.60}, 0.04, TODAY)
    assert m['iv_entry'] == pytest.approx(1.14) and m['tv_entry'] == pytest.approx(6.26)
    assert m['pos_risk'] == pytest.approx(2220) and m['dte'] == 69
    assert m['price_now'] == pytest.approx(4.55) and m['price_source'] == 'mid'
    assert m['pos_size'] == pytest.approx(1365) and m['pnl'] == pytest.approx(-855)
    assert m['iv_now'] == 0 and m['tv_now'] == pytest.approx(4.55)
    assert m['delta'] < 0 and m['delta_calc'] and m['delta_dollars'] < 0   # puts: negative exposure


def test_wk_call_intrinsic_and_short_leg():
    # WK call 70 at 5.45 with the stock at 72.76: IV* 2.76, TV* 2.69 (sheet)
    m = calc.leg_metrics(leg(qty=2, strike=70, avg_price=7.90, und_entry=71.24, expiry='2026-11-20'),
                         72.76, {'last': 5.45, 'delta': 0.62}, 0.04, TODAY)
    assert m['iv_now'] == pytest.approx(2.76) and m['tv_now'] == pytest.approx(2.69)
    assert m['iv_entry'] == pytest.approx(1.24) and m['tv_entry'] == pytest.approx(6.66)
    assert m['price_source'] == 'last' and not m['delta_calc']
    assert m['delta_dollars'] == pytest.approx(2 * 100 * 0.62 * 72.76)
    # MRK -2 puts 140 sold at 3.00, now 0.62: pos risk -600, pos size -124, P&L +476
    s = calc.leg_metrics(leg(qty=-2, right='P', strike=140, avg_price=3.00, expiry='2026-11-13'),
                         146.73, {'bid': 0.60, 'ask': 0.64}, 0.04, TODAY)
    assert s['pos_risk'] == -600 and s['pos_size'] == pytest.approx(-124) and s['pnl'] == pytest.approx(476)


def test_closed_and_expired_legs():
    c = calc.leg_metrics(leg(qty=-1, avg_price=4.25, close_price=0.01), 67.88, None, 0.04, TODAY)
    assert c['realized'] == pytest.approx(424) and c['pnl'] is None
    e = calc.leg_metrics(leg(qty=-1, strike=100, avg_price=4.25, expiry='2026-11-06'), 67.88, None, 0.04, TODAY)
    assert e['dte'] == -1 and e['price_now'] == 0 and e['price_source'] == 'expired' and e['pnl'] == pytest.approx(425)
    none = calc.leg_metrics(leg(), None, None, 0.04, TODAY)
    assert none['price_now'] is None and none['pnl'] is None and none['delta_dollars'] is None


def test_stop_state():
    assert calc.stop_state('long', 240.30, 235.00, 3) == 'near'
    assert calc.stop_state('long', 240.30, 233.03, 3) is None   # 3.03% away
    assert calc.stop_state('long', 240.30, 200, 3) is None
    assert calc.stop_state('long', 21.81, 25.43, 3) == 'hit'
    assert calc.stop_state('short', 44.45, 43.43, 3) == 'hit'
    assert calc.stop_state('short', 75.36, 79.76, 3) is None
    assert calc.stop_state('short', 75.36, None, 3) is None


def test_position_metrics_and_totals():
    legs = [leg(qty=3, right='P', strike=145, avg_price=8.75, expiry='2027-01-15'),
            leg(qty=-2, right='P', strike=140, avg_price=3.00, expiry='2026-11-13'),
            leg(qty=1, right='P', strike=130, avg_price=2.00, close_price=3.00)]
    quotes = [{'last': 7.03, 'delta': -0.4}, {'last': 0.62, 'delta': -0.1}, None]
    for lg, q in zip(legs, quotes):
        lg['m'] = calc.leg_metrics(lg, 146.73, q, 0.04, TODAY)
    pos = {'direction': 'short', 'stop': 149.74, 'target': 122.0}
    m = calc.position_metrics(pos, legs, 146.73, '2026-12-01', CFG, TODAY)
    assert m['pos_risk'] == pytest.approx(2625 - 600) and m['realized'] == pytest.approx(100)
    assert m['pnl'] == pytest.approx((2109 - 124) - (2625 - 600))
    assert m['stop_state'] == 'near' and m['earnings_before_expiry'] and m['min_dte'] == 6
    assert m['to_target'] == pytest.approx(122 / 146.73 - 1)
    assert not calc.position_metrics(pos, legs, 146.73, '2027-02-01', CFG, TODAY)['earnings_before_expiry']
    t = calc.portfolio_totals([{'m': m}, {'m': {**m, 'open': False}}])
    assert t['positions'] == 1 and t['realized'] == pytest.approx(200) and t['pos_risk'] == pytest.approx(2025)
