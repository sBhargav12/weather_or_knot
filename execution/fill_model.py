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

# KXHIGHNY maker-return priors from the microstructure atlas (research/becker/microstructure_atlas.py).
# Values are gross maker return fractions observed in settled Becker trades; higher return →
# tighter effective spread assumption. Atlas finding: weather 60-70c and 70-80c buckets have
# the strongest maker returns (+3.0pp and +3.2pp), while 40-50c and 50-60c are weakest (~0.9pp).
# These are used as a price-bucket override for spread estimates in paper policy — they do not
# change live execution or config.py.
_ATLAS_HALF_SPREAD_BY_PRICE_BUCKET: dict[tuple[float, float], float] = {
    (0.00, 0.05): 0.040,  # atlas: +0.70pp maker return — very thin
    (0.05, 0.10): 0.030,  # atlas: +1.15pp
    (0.10, 0.20): 0.025,  # atlas: not in top slice
    (0.20, 0.30): 0.020,
    (0.30, 0.40): 0.018,  # atlas: +0.62pp — weak bucket
    (0.40, 0.50): 0.020,  # atlas: +0.88pp — weakest core bucket
    (0.50, 0.60): 0.018,  # atlas: +0.91pp
    (0.60, 0.70): 0.012,  # atlas: +2.99pp — strongest core bucket
    (0.70, 0.80): 0.012,  # atlas: +3.20pp — strongest overall
    (0.80, 0.90): 0.013,  # atlas: +3.71pp maker return (high price = thin liquidity, but strong return)
    (0.90, 0.95): 0.020,  # atlas: +2.48pp
    (0.95, 1.00): 0.030,  # atlas: +1.32pp — near-certainty, spread widens
}


def half_spread_for_price(price: float, bracket_type: str) -> float:
    """Return the atlas-informed half-spread for a given YES-side price and bracket type.

    Falls back to the bracket-type flat spread when price is out of range.
    Atlas priors are capped by the bracket-type floor so tail brackets never
    underestimate execution cost based on price alone.
    """
    floor = HALF_SPREADS.get(bracket_type, 0.020)
    for (lo, hi), spread in _ATLAS_HALF_SPREAD_BY_PRICE_BUCKET.items():
        if lo <= price < hi:
            return max(spread, floor)
    return floor


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
    half_spread = half_spread_for_price(desired_price, bracket_type)
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
