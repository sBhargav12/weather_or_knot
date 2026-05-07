from __future__ import annotations

from decimal import Decimal
from statistics import median, stdev
from typing import Any, Dict, Optional, Tuple

import config
from signal_engine.schemas import (
    Gate1Result,
    Gate2Result,
    Gate3Result,
    Gate4Result,
    Gate5Result,
    Gate6Result,
    GateCheckResult,
)

# ---------------------------------------------------------------------------
# TIERED GATE SYSTEM
#
# TIER 1 — Hard requirements. All must pass to generate a signal.
#   Gate 1: Model convergence (HGEFS or wethr-proxy); hard-blocks if |HGEFS–NBM| ≥ 15°F
#   Gate 2: Gumbel gap >= config.MIN_GAP_PP
#   Gate 3: Price band 0.25–0.75
#
# TIER 2 — Confidence modifiers only. Never block a signal.
#   Gate 4: Dead zone (35–40pp) → -25 confidence
#   Gate 5: METAR confirmation → +25 (confirms) / -15 (contradicts) / -10 (missing)
#   Gate 6: Evening reversal → ±30 confidence
#
# CONFIDENCE → POSITION SIZE:
#   >= 80: full Quarter-Kelly (max 5% bankroll)
#   60-79: half Quarter-Kelly (max 2.5%)
#   40-59: quarter Quarter-Kelly (max 1.25%)
#   < 40:  skip trade
# ---------------------------------------------------------------------------

_GATE1_MAX_SPREAD_BETWEEN = config.HGEFS_MAX_SPREAD_BETWEEN      # 1.5°F
_GATE1_MAX_SUBSET_SPREAD = config.HGEFS_MAX_SUBSET_SPREAD         # 3.0°F
_GATE1_PROXY_MAX_STD = 2.5                                         # wethr-proxy threshold
_GATE2_MIN_GAP_HARD = config.MIN_GAP_PP                            # strict hard floor (pp)
_GATE2_HIGH_CONFIDENCE_GAP = config.MIN_GAP_PP + 5.0


def _nbm_disagreement(hgefs_consensus: float, nbm_p50: Optional[float]) -> tuple[bool, float, float]:
    """Return (hard_block, gap_f, confidence_penalty) for NBM vs HGEFS gap check."""
    if nbm_p50 is None:
        return False, 0.0, 0.0
    gap = abs(hgefs_consensus - float(nbm_p50))
    if gap >= config.NBM_HGEFS_HARD_BLOCK_GAP_F:
        return True, gap, 0.0
    if gap >= config.NBM_HGEFS_PENALTY_GAP_F:
        return False, gap, -30.0
    return False, gap, 0.0


def check_gate_1(
    physics_mean: Optional[float],
    physics_spread: Optional[float],
    ai_mean: Optional[float],
    ai_spread: Optional[float],
    wethr_models: Optional[Dict[str, float]] = None,
    nbm_p50: Optional[float] = None,
) -> Tuple[bool, dict]:
    """TIER 1. Pass if real HGEFS agrees OR wethr-proxy spread is tight.

    Also hard-blocks when NBM p50 disagrees with HGEFS consensus by >=15°F —
    that gap is a 3-sigma signal that HGEFS missed a front (e.g. 2026-05-03:
    HGEFS=70.6°F, NBM=50°F, actual=55°F).  An 8–15°F gap adds -30 confidence.
    """

    # Path A: real HGEFS data
    if None not in (physics_mean, physics_spread, ai_mean, ai_spread):
        spread_between = abs(float(physics_mean) - float(ai_mean))
        hgefs_consensus = (float(physics_mean) + float(ai_mean)) / 2.0
        nbm_block, nbm_gap, nbm_penalty = _nbm_disagreement(hgefs_consensus, nbm_p50)
        convergence_pass = (
            spread_between <= _GATE1_MAX_SPREAD_BETWEEN
            and float(physics_spread) < _GATE1_MAX_SUBSET_SPREAD
            and float(ai_spread) < _GATE1_MAX_SUBSET_SPREAD
        )
        gate_pass = convergence_pass and not nbm_block
        if gate_pass:
            confidence_add = 30.0 + nbm_penalty
        else:
            confidence_add = 0.0
        if nbm_block:
            reason = f"nbm_hgefs_gap_{nbm_gap:.1f}F_hard_block"
        elif not convergence_pass:
            reason = f"real_hgefs_spread_{spread_between:.2f}F"
        else:
            reason = "pass"
        return gate_pass, {
            "physics_mean": physics_mean,
            "physics_spread": physics_spread,
            "ai_mean": ai_mean,
            "ai_spread": ai_spread,
            "spread_between": spread_between,
            "nbm_p50": nbm_p50,
            "nbm_hgefs_gap_f": nbm_gap,
            "pass": gate_pass,
            "hgefs_real": True,
            "confidence_add": confidence_add,
            "reason": reason,
        }

    # Path B: wethr-proxy — need >= 3 models within 3°F of each other
    if wethr_models:
        values = [float(v) for v in wethr_models.values() if v is not None]
        if len(values) >= 3:
            med = median(values)
            agreeing = [v for v in values if abs(v - med) <= 3.0]
            if len(agreeing) >= 3:
                proxy_std = stdev(agreeing) if len(agreeing) >= 2 else 0.0
                nbm_block, nbm_gap, nbm_penalty = _nbm_disagreement(med, nbm_p50)
                convergence_pass = proxy_std < _GATE1_PROXY_MAX_STD
                gate_pass = convergence_pass and not nbm_block
                if gate_pass:
                    confidence_add = 15.0 + nbm_penalty
                else:
                    confidence_add = 0.0
                if nbm_block:
                    reason = f"nbm_hgefs_gap_{nbm_gap:.1f}F_hard_block"
                elif not convergence_pass:
                    reason = f"proxy_spread_{proxy_std:.2f}F"
                else:
                    reason = "pass_proxy"
                return gate_pass, {
                    "physics_mean": med,
                    "physics_spread": proxy_std,
                    "ai_mean": med,
                    "ai_spread": proxy_std,
                    "spread_between": 0.0,
                    "nbm_p50": nbm_p50,
                    "nbm_hgefs_gap_f": nbm_gap,
                    "pass": gate_pass,
                    "hgefs_real": False,
                    "confidence_add": confidence_add,
                    "reason": reason,
                }

    return False, {
        "physics_mean": physics_mean,
        "physics_spread": physics_spread,
        "ai_mean": ai_mean,
        "ai_spread": ai_spread,
        "spread_between": None,
        "nbm_p50": nbm_p50,
        "nbm_hgefs_gap_f": None,
        "pass": False,
        "hgefs_real": False,
        "confidence_add": 0.0,
        "reason": "insufficient_model_data",
    }


def check_gate_2(model_prob: float, market_price: float) -> Tuple[bool, dict]:
    """TIER 1. Pass if abs(gap) exceeds the configured edge floor and dead zone."""
    gap_pp = (float(model_prob) - float(market_price)) * 100
    direction = "YES" if gap_pp > 0 else "NO"
    abs_gap = abs(gap_pp)

    # Dead zone check integrated here so direction is known
    in_dead_zone = config.DEAD_ZONE_LO <= abs_gap <= config.DEAD_ZONE_HI
    gate_pass = abs_gap > _GATE2_MIN_GAP_HARD and not in_dead_zone

    if abs_gap > _GATE2_HIGH_CONFIDENCE_GAP:
        confidence_add = 30.0
    elif abs_gap > _GATE2_MIN_GAP_HARD:
        confidence_add = 20.0
    else:
        confidence_add = 0.0

    return gate_pass, {
        "model_prob": model_prob,
        "market_price": market_price,
        "gap_pp": gap_pp,
        "direction": direction,
        "in_dead_zone": in_dead_zone,
        "pass": gate_pass,
        "confidence_add": confidence_add,
    }


def check_gate_3(yes_price: float, direction: str = "YES") -> Tuple[bool, dict]:
    """TIER 1. Entry price must be in the 0.25–0.75 band."""
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
    """TIER 2. Dead zone is a confidence modifier, not a hard block."""
    in_dead_zone = config.DEAD_ZONE_LO <= abs(float(gap_pp)) <= config.DEAD_ZONE_HI
    confidence_delta = -25.0 if in_dead_zone else 10.0
    # Always passes as a standalone gate (dead zone handled in Gate 2 for hard block)
    return True, {
        "gap_pp": gap_pp,
        "in_dead_zone": in_dead_zone,
        "pass": True,
        "confidence_delta": confidence_delta,
    }


def check_gate_5(
    metar_temp_f: Optional[float],
    bracket_center_f: float,
    direction: str,
    six_hour_high_f: Optional[float] = None,
) -> Tuple[bool, dict]:
    """TIER 2. METAR modifies confidence; missing reading = neutral (no penalty).

    For YES brackets the effective temperature is max(metar, six_hour_high) — the
    rolling 6-hour high is a better floor for where today's peak is heading than
    the instantaneous METAR reading, which can be temporarily depressed by wind or
    instrumentation lag.
    """
    if metar_temp_f is None and six_hour_high_f is None:
        return True, {
            "metar_temp_f": None,
            "six_hour_high_f": None,
            "effective_temp_f": None,
            "bracket_center_f": bracket_center_f,
            "distance": None,
            "direction": direction,
            "pass": True,
            "confidence_delta": -10.0,
            "reason": "metar_unavailable_penalty",
        }

    # For YES: peak observed so far is the most informative signal.
    # For NO: use metar_temp_f only (six_hour_high being high hurts a NO bet —
    #         that's already captured by distance > threshold).
    candidates = [v for v in (metar_temp_f, six_hour_high_f if direction == "YES" else None) if v is not None]
    effective_temp = max(candidates) if candidates else (metar_temp_f or six_hour_high_f)

    distance = abs(float(effective_temp) - float(bracket_center_f))
    if direction == "YES":
        within_threshold = distance <= config.METAR_YES_MAX_DISTANCE
    else:
        within_threshold = distance > config.METAR_NO_MIN_DISTANCE

    confidence_delta = 25.0 if within_threshold else -15.0

    return True, {   # always passes — TIER 2 modifier only
        "metar_temp_f": metar_temp_f,
        "six_hour_high_f": six_hour_high_f,
        "effective_temp_f": effective_temp,
        "bracket_center_f": bracket_center_f,
        "distance": distance,
        "direction": direction,
        "pass": True,
        "metar_confirms": within_threshold,
        "confidence_delta": confidence_delta,
        "reason": "metar_confirms" if within_threshold else "metar_contradicts",
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
    """TIER 2. Evening reversal modifies confidence; never blocks a signal."""
    is_cold_bracket = float(bracket_low_f) <= config.COLD_BRACKET_MAX_TEMP

    if not price_history or len(price_history) < 2:
        return True, {
            "ticker": ticker,
            "pass": True,
            "is_cold_bracket": is_cold_bracket,
            "reversal_detected": False,
            "confidence_delta": 10.0,
            "reason": "no_history",
        }

    prices = [_price_from_history_item(item) for item in price_history]
    max_price = max(prices)
    current_price = prices[-1]
    rose_10 = any(price >= prices[0] + float(config.REVERSAL_THRESHOLD) for price in prices)
    reversal_detected = rose_10 and (max_price - current_price >= float(config.REVERSAL_THRESHOLD))

    if reversal_detected and is_cold_bracket:
        confidence_delta = -30.0
    elif reversal_detected:
        confidence_delta = -15.0
    else:
        confidence_delta = 10.0

    return True, {   # always passes — TIER 2 modifier only
        "ticker": ticker,
        "is_cold_bracket": is_cold_bracket,
        "reversal_detected": reversal_detected,
        "max_price": max_price,
        "current_price": current_price,
        "pass": True,
        "confidence_delta": confidence_delta,
        "reason": "98pct_no_rate_cold_bracket" if (reversal_detected and is_cold_bracket) else "pass",
    }


def compute_confidence_score(gate_results: GateCheckResult) -> float:
    """Sum confidence contributions from all gates, clamped to [0, 100]."""
    score = (
        gate_results.gate1.confidence_add
        + gate_results.gate2.confidence_add
        + gate_results.gate4.confidence_delta
        + gate_results.gate5.confidence_delta
        + gate_results.gate6.confidence_delta
    )
    return round(min(100.0, max(0.0, score)), 2)


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
    wethr_models: Optional[Dict[str, float]] = None,
    nbm_p50: Optional[float] = None,
    six_hour_high_f: Optional[float] = None,
) -> GateCheckResult:
    g1_pass, g1 = check_gate_1(physics_mean, physics_spread, ai_mean, ai_spread, wethr_models, nbm_p50)
    g2_pass, g2 = check_gate_2(model_prob, market_price)
    effective_direction = g2["direction"]
    g3_pass, g3 = check_gate_3(yes_price, effective_direction)

    tier1_pass = g1_pass and g2_pass and g3_pass

    _, g4 = check_gate_4(g2["gap_pp"])
    _, g5 = check_gate_5(metar_temp_f, bracket_center_f, effective_direction, six_hour_high_f)
    _, g6 = check_gate_6(ticker, bracket_low_f, price_history)

    skip_reason = None if tier1_pass else next(
        f"gate{i + 1}_fail"
        for i, passed in enumerate([g1_pass, g2_pass, g3_pass])
        if not passed
    )

    result = GateCheckResult(
        all_pass=tier1_pass,
        direction=effective_direction,
        requested_direction=direction,
        gap_pp=g2["gap_pp"],
        gate1=Gate1Result(
            physics_mean=g1.get("physics_mean"),
            physics_spread=g1.get("physics_spread"),
            ai_mean=g1.get("ai_mean"),
            ai_spread=g1.get("ai_spread"),
            spread_between=g1.get("spread_between"),
            nbm_p50=g1.get("nbm_p50"),
            nbm_hgefs_gap_f=g1.get("nbm_hgefs_gap_f"),
            passed=g1_pass,
            hgefs_real=g1.get("hgefs_real", False),
            confidence_add=g1.get("confidence_add", 0.0),
            reason=g1.get("reason", ""),
        ),
        gate2=Gate2Result(
            model_prob=g2["model_prob"],
            market_price=g2["market_price"],
            gap_pp=g2["gap_pp"],
            direction=g2["direction"],
            in_dead_zone=g2["in_dead_zone"],
            passed=g2_pass,
            confidence_add=g2["confidence_add"],
        ),
        gate3=Gate3Result(
            yes_price=g3["yes_price"],
            entry_price=g3["entry_price"],
            direction=g3["direction"],
            passed=g3_pass,
            reason=g3["reason"],
        ),
        gate4=Gate4Result(
            gap_pp=g4["gap_pp"],
            in_dead_zone=g4["in_dead_zone"],
            passed=True,
            confidence_delta=g4["confidence_delta"],
        ),
        gate5=Gate5Result(
            metar_temp_f=g5.get("metar_temp_f"),
            six_hour_high_f=g5.get("six_hour_high_f"),
            effective_temp_f=g5.get("effective_temp_f"),
            bracket_center_f=g5["bracket_center_f"],
            distance=g5.get("distance"),
            direction=g5["direction"],
            passed=True,
            metar_confirms=g5.get("metar_confirms"),
            confidence_delta=g5["confidence_delta"],
            reason=g5["reason"],
        ),
        gate6=Gate6Result(
            ticker=g6["ticker"],
            is_cold_bracket=g6["is_cold_bracket"],
            reversal_detected=g6.get("reversal_detected", False),
            max_price=g6.get("max_price"),
            current_price=g6.get("current_price"),
            passed=True,
            confidence_delta=g6["confidence_delta"],
            reason=g6["reason"],
        ),
        skip_reason=skip_reason,
    )
    result.confidence_score = compute_confidence_score(result)
    return result


def decimal_price(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
