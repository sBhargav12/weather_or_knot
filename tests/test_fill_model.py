from __future__ import annotations

import math

import pandas as pd


def test_taker_adds_slippage():
    from execution.fill_model import simulate_fill

    fill = simulate_fill(0.45, "central", "YES", "taker", 1)
    assert fill["fill_price"] > 0.45
    assert fill["slippage"] > 0


def test_maker_no_slippage():
    from execution.fill_model import simulate_fill

    fill = simulate_fill(0.45, "central", "YES", "maker", 1)
    assert fill["slippage"] == 0.0
    assert fill["fill_price"] == 0.45


def test_deep_tail_wider_spread():
    from execution.fill_model import HALF_SPREADS

    assert HALF_SPREADS["lower_tail"] > HALF_SPREADS["central"]


def test_stress_test_reduces_pnl():
    from execution.fill_model import stress_test_fills

    trades = pd.DataFrame([{"entry_price": 0.45, "net_pnl": 0.20, "contracts": 1}])
    stressed = stress_test_fills(trades, extra_cents=3.0)
    assert stressed["net_pnl_stressed"].iloc[0] < trades["net_pnl"].iloc[0]


def test_fee_formula():
    from execution.fill_model import kalshi_fee

    price = 0.50
    expected_taker = math.ceil(0.07 * 1 * price * (1 - price) * 100) / 100
    assert kalshi_fee(0.50, 1, "taker") == expected_taker
