from __future__ import annotations

import math

import pandas as pd


HALF_SPREADS = {
    "central": 0.015,
    "wing_low": 0.025,
    "wing_high": 0.025,
    "lower_tail": 0.040,
    "upper_tail": 0.040,
}


def kalshi_fee(price: float, contracts: int, order_type: str = "maker") -> float:
    """Ceiling-rounded Kalshi fee for research fill simulations."""
    rate = 0.07 if order_type == "taker" else 0.0175
    return math.ceil(rate * contracts * price * (1 - price) * 100) / 100


def simulate_fill(
    desired_price: float,
    bracket_type: str,
    direction: str,
    order_type: str,
    contracts: int = 1,
) -> dict:
    """
    Simulate a research-only fill with simple spread and fee assumptions.

    Maker orders post at the desired price with no slippage but imperfect fill
    probability. Taker orders cross a bracket-family half-spread.
    """
    half_spread = HALF_SPREADS.get(bracket_type, 0.020)
    side = direction.upper()
    kind = order_type.lower()

    if kind == "taker":
        slippage = half_spread if side == "YES" else -half_spread
        fill_prob = 0.95
    else:
        slippage = 0.0
        fill_prob = 0.70
        kind = "maker"

    fill_price = round(min(max(desired_price + slippage, 0.01), 0.99), 4)
    fee = kalshi_fee(fill_price, contracts, kind)
    return {
        "fill_price": fill_price,
        "slippage": slippage,
        "fee": fee,
        "fill_probability": fill_prob,
        "order_type": kind,
    }


def stress_test_fills(trades: pd.DataFrame, extra_cents: float = 3.0) -> pd.DataFrame:
    """
    Add extra slippage to every fill to test execution robustness.

    The stress subtracts the penalty twice to approximate worse entry plus
    worse exit/repricing friction in settlement-style research backtests.
    """
    t = trades.copy()
    penalty = extra_cents / 100.0
    contracts = t["contracts"] if "contracts" in t.columns else 1
    t["entry_price_stressed"] = (t["entry_price"] + penalty).clip(upper=0.99)
    t["net_pnl_stressed"] = t["net_pnl"] - penalty * contracts - penalty * contracts
    t["stress_cents"] = extra_cents
    return t
