from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import config


def check_gate_1(
    physics_mean: Optional[float],
    physics_spread: Optional[float],
    ai_mean: Optional[float],
    ai_spread: Optional[float],
) -> Tuple[bool, dict]:
    if None in (physics_mean, physics_spread, ai_mean, ai_spread):
        return False, {
            "physics_mean": physics_mean,
            "physics_spread": physics_spread,
            "ai_mean": ai_mean,
            "ai_spread": ai_spread,
            "spread_between": None,
            "pass": False,
            "reason": "missing_hgefs_data",
        }
    spread_between = abs(float(physics_mean) - float(ai_mean))
    gate_pass = (
        spread_between <= config.HGEFS_MAX_SPREAD_BETWEEN
        and float(physics_spread) < config.HGEFS_MAX_SUBSET_SPREAD
        and float(ai_spread) < config.HGEFS_MAX_SUBSET_SPREAD
    )
    return gate_pass, {
        "physics_mean": physics_mean,
        "physics_spread": physics_spread,
        "ai_mean": ai_mean,
        "ai_spread": ai_spread,
        "spread_between": spread_between,
        "pass": gate_pass,
        "reason": "pass" if gate_pass else f"spread {spread_between:.2f}F exceeds threshold",
    }


def check_gate_2(model_prob: float, market_price: float) -> Tuple[bool, dict]:
    gap_pp = (float(model_prob) - float(market_price)) * 100
    direction = "YES" if gap_pp > 0 else "NO"
    gate_pass = abs(gap_pp) > config.MIN_GAP_PP
    return gate_pass, {
        "model_prob": model_prob,
        "market_price": market_price,
        "gap_pp": gap_pp,
        "direction": direction,
        "pass": gate_pass,
    }


def check_gate_3(yes_price: float, direction: str = "YES") -> Tuple[bool, dict]:
    entry_price = float(yes_price) if direction == "YES" else 1.0 - float(yes_price)
    gate_pass = float(config.MIN_YES_PRICE) <= entry_price <= float(config.MAX_YES_PRICE)
    reason = "pass"
    if not gate_pass:
        reason = "longshot_trap" if entry_price < float(config.MIN_YES_PRICE) else "nws_error_risk"
    return gate_pass, {
        "yes_price": yes_price,
        "entry_price": entry_price,
        "direction": direction,
        "pass": gate_pass,
        "reason": reason,
    }


def check_gate_4(gap_pp: float) -> Tuple[bool, dict]:
    in_dead_zone = config.DEAD_ZONE_LO <= abs(float(gap_pp)) <= config.DEAD_ZONE_HI
    gate_pass = not in_dead_zone
    return gate_pass, {"gap_pp": gap_pp, "in_dead_zone": in_dead_zone, "pass": gate_pass}


def check_gate_5(metar_temp_f: Optional[float], bracket_center_f: float, direction: str) -> Tuple[bool, dict]:
    if metar_temp_f is None:
        return False, {
            "metar_temp_f": None,
            "bracket_center_f": bracket_center_f,
            "distance": None,
            "direction": direction,
            "pass": False,
            "reason": "missing_metar",
        }
    distance = abs(float(metar_temp_f) - float(bracket_center_f))
    if direction == "YES":
        gate_pass = distance <= config.METAR_YES_MAX_DISTANCE
    else:
        gate_pass = distance > config.METAR_NO_MIN_DISTANCE
    return gate_pass, {
        "metar_temp_f": metar_temp_f,
        "bracket_center_f": bracket_center_f,
        "distance": distance,
        "direction": direction,
        "pass": gate_pass,
        "reason": "pass" if gate_pass else "metar_misaligned",
    }


def _price_from_history_item(item: Any) -> float:
    if isinstance(item, dict):
        for key in ("yes_price", "yes_bid", "yes_last", "price"):
            value = item.get(key)
            if value is not None:
                return float(value)
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return float(item[1])
    return float(item)


def check_gate_6(ticker: str, bracket_low_f: float, price_history: list) -> Tuple[bool, dict]:
    is_cold_bracket = float(bracket_low_f) <= config.COLD_BRACKET_MAX_TEMP
    if not price_history or len(price_history) < 2:
        return True, {
            "ticker": ticker,
            "pass": True,
            "is_cold_bracket": is_cold_bracket,
            "reversal_detected": False,
            "reason": "no_history",
        }
    prices = [_price_from_history_item(item) for item in price_history]
    max_price = max(prices)
    current_price = prices[-1]
    rose_10 = any(price >= prices[0] + float(config.REVERSAL_THRESHOLD) for price in prices)
    reversal_detected = rose_10 and (max_price - current_price >= float(config.REVERSAL_THRESHOLD))
    gate_pass = not (reversal_detected and is_cold_bracket)
    return gate_pass, {
        "ticker": ticker,
        "is_cold_bracket": is_cold_bracket,
        "reversal_detected": reversal_detected,
        "max_price": max_price,
        "current_price": current_price,
        "pass": gate_pass,
        "reason": "98pct_no_rate_cold_bracket" if not gate_pass else "pass",
    }


def compute_confidence_score(gate_results: dict) -> float:
    gate1 = gate_results.get("gate1", {})
    gate2 = gate_results.get("gate2", {})
    gate5 = gate_results.get("gate5", {})
    gate6 = gate_results.get("gate6", {})

    spread_between = gate1.get("spread_between")
    gate1_score = 0.0
    if gate1.get("pass") and spread_between is not None:
        gate1_score = 30.0 * max(0.0, 1.0 - spread_between / config.HGEFS_MAX_SPREAD_BETWEEN)

    gap_pp = abs(float(gate2.get("gap_pp", 0.0)))
    gate2_score = 0.0
    if gate2.get("pass"):
        gate2_score = min(30.0, 30.0 * (gap_pp - config.MIN_GAP_PP) / 30.0)

    distance = gate5.get("distance")
    gate5_score = 0.0
    if gate5.get("pass") and distance is not None:
        if gate5.get("direction") == "YES":
            gate5_score = 20.0 * max(0.0, 1.0 - distance / config.METAR_YES_MAX_DISTANCE)
        else:
            gate5_score = min(20.0, 20.0 * distance / 12.0)

    gate6_score = 20.0 if gate6.get("pass") and not gate6.get("reversal_detected") else 0.0
    return round(min(100.0, gate1_score + gate2_score + gate5_score + gate6_score), 2)


def run_all_gates(
    physics_mean,
    physics_spread,
    ai_mean,
    ai_spread,
    model_prob,
    market_price,
    yes_price,
    metar_temp_f,
    bracket_center_f,
    bracket_low_f,
    direction,
    price_history,
    ticker,
) -> dict:
    g1_pass, g1 = check_gate_1(physics_mean, physics_spread, ai_mean, ai_spread)
    g2_pass, g2 = check_gate_2(model_prob, market_price)
    effective_direction = g2["direction"]
    g3_pass, g3 = check_gate_3(yes_price, effective_direction)
    g4_pass, g4 = check_gate_4(g2["gap_pp"])
    g5_pass, g5 = check_gate_5(metar_temp_f, bracket_center_f, effective_direction)
    g6_pass, g6 = check_gate_6(ticker, bracket_low_f, price_history)

    pass_list = [g1_pass, g2_pass, g3_pass, g4_pass, g5_pass, g6_pass]
    all_pass = all(pass_list)
    result = {
        "all_pass": all_pass,
        "direction": effective_direction,
        "requested_direction": direction,
        "gap_pp": g2["gap_pp"],
        "gate1": g1,
        "gate2": g2,
        "gate3": g3,
        "gate4": g4,
        "gate5": g5,
        "gate6": g6,
        "skip_reason": None
        if all_pass
        else next(f"gate{i + 1}_fail" for i, passed in enumerate(pass_list) if not passed),
    }
    result["confidence_score"] = compute_confidence_score(result)
    return result


def decimal_price(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
