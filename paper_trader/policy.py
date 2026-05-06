from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from paper_trader import config_paper
from execution.fill_model import half_spread_for_price
from execution.fill_model import kalshi_fee


REGIME_PERIODS = [
    ("pre_HGEFS", date.min, date(2024, 12, 16)),
    ("HGEFS_to_AIFS", date(2024, 12, 17), date(2025, 2, 24)),
    ("AIFS_to_NBM_v43", date(2025, 2, 25), date(2025, 5, 26)),
    ("NBM_v43_to_AIFS_ENS", date(2025, 5, 27), date(2025, 6, 30)),
    ("AIFS_ENS_to_NBM_v50", date(2025, 7, 1), date(2026, 4, 14)),
    ("NBM_v50_on", date(2026, 4, 15), date.max),
]


@dataclass(frozen=True)
class PaperPolicyDecision:
    """Structured paper-only policy decision.

    This object is deliberately auditable and serializable. It is not a live
    execution approval surface.
    """

    allowed: bool
    candidate_status: str
    policy_reason: str
    sleeve: str
    bracket_family: str
    raw_edge_pp: float
    est_execution_cost_pp: float
    fee_margin_pp: float
    est_net_edge_pp: float
    min_required_net_edge_pp: float
    seasonal_mult: float
    regime: str
    regime_mult: float
    final_size_mult: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_sleeve(signal: dict) -> str:
    value = str(signal.get("strategy_sleeve") or signal.get("sleeve") or "CORE_HGEFS_GUMBEL")
    if value in {"CORE", "CORE_HGEFS_GUMBEL"}:
        return "CORE"
    return value


def bracket_family(signal: dict) -> str:
    """Classify a bracket into lower tail, upper tail, or central range."""
    raw_type = str(signal.get("bracket_type") or "").lower()
    bracket = str(signal.get("bracket") or "")
    if raw_type in {"wing_low", "lower_tail", "lower"} or bracket.startswith("<="):
        return "lower_tail"
    if raw_type in {"wing_high", "upper_tail", "upper"} or bracket.startswith(">="):
        return "upper_tail"
    return "central"


def central_or_wing(family: str) -> str:
    return "central" if family == "central" else "wing"


def target_month(signal: dict) -> int:
    target = signal.get("target_date")
    if target:
        try:
            return date.fromisoformat(str(target)[:10]).month
        except ValueError:
            pass
    return date.today().month


def regime_for_date(target_date: str | None) -> str:
    if not target_date:
        return "unknown"
    try:
        parsed = date.fromisoformat(str(target_date)[:10])
    except ValueError:
        return "unknown"
    for label, start, end in REGIME_PERIODS:
        if start <= parsed <= end:
            return label
    return "unknown"


def seasonal_multiplier(signal: dict) -> float:
    if not config_paper.PAPER_USE_SEASONAL_SCALING:
        return 1.0
    return float(config_paper.PAPER_SEASONAL_MULTIPLIERS.get(target_month(signal), 1.0))


def regime_multiplier(signal: dict) -> tuple[str, float]:
    regime = regime_for_date(signal.get("target_date"))
    if not config_paper.PAPER_USE_REGIME_SCALING:
        return regime, 1.0
    return regime, float(config_paper.PAPER_REGIME_MULTIPLIERS.get(regime, config_paper.PAPER_REGIME_MULTIPLIERS["unknown"]))


def final_size_multiplier(signal: dict) -> tuple[str, float, float, float]:
    seasonal = seasonal_multiplier(signal)
    regime, regime_mult = regime_multiplier(signal)
    combined = seasonal * regime_mult
    clamped = min(max(combined, config_paper.PAPER_MIN_SIZE_MULT), config_paper.PAPER_MAX_SIZE_MULT)
    return regime, seasonal, regime_mult, float(clamped)


def raw_side_edge_pp(signal: dict) -> float:
    """Return edge in side-space: YES edge for YES, NO edge for NO."""
    if signal.get("gap_pp") is not None:
        gap = float(signal["gap_pp"])
        return abs(gap) if signal.get("direction", "YES") == "NO" else gap
    direction = str(signal.get("direction", "YES")).upper()
    model_prob_yes = float(signal.get("model_prob", 0.0))
    side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes
    side_price = float(signal.get("entry_price", signal.get("market_price", 0.0)))
    return (side_prob - side_price) * 100.0


def estimate_execution_cost_pp(signal: dict) -> float:
    """Paper execution-cost prior, expressed in percentage points.

    This is a reserve, not a true queue model. It uses observed spread when
    available and falls back to bracket-family half-spread assumptions from the
    research fill model.
    """
    family = bracket_family(signal)
    sleeve = canonical_sleeve(signal)
    try:
        entry_price_for_spread = float(signal.get("entry_price", signal.get("market_price", 0.50)))
    except (TypeError, ValueError):
        entry_price_for_spread = 0.50
    atlas_half_spread = half_spread_for_price(entry_price_for_spread, family) * 100.0
    spread = signal.get("spread")
    spread_reserve = atlas_half_spread
    if spread is not None:
        try:
            spread_reserve = max(0.0, float(spread) * 50.0)
        except (TypeError, ValueError):
            pass

    maker_fee_pp = kalshi_fee(min(max(entry_price_for_spread, 0.01), 0.99), 1, "maker") * 100.0

    if sleeve == "CORE":
        stress_buffer = float(config_paper.PAPER_CORE_STRESS_BUFFER_PP)
    elif sleeve == "DEEP_TAIL_NO":
        stress_buffer = float(config_paper.PAPER_DEEP_TAIL_STRESS_BUFFER_PP)
    elif family != "central":
        stress_buffer = float(config_paper.PAPER_WING_STRESS_BUFFER_PP)
    else:
        stress_buffer = 0.0

    return float(spread_reserve + maker_fee_pp + stress_buffer)


def min_required_net_edge_pp(sleeve: str, family: str) -> float:
    if sleeve == "DEEP_TAIL_NO":
        return float(config_paper.PAPER_MIN_NET_EDGE_PP_DEEP_TAIL)
    if config_paper.PAPER_USE_WING_CENTRAL_SPLIT and family != "central":
        return float(config_paper.PAPER_MIN_NET_EDGE_PP_WING)
    return float(config_paper.PAPER_MIN_NET_EDGE_PP_CORE)


def paper_policy_allows_trade(signal: dict) -> PaperPolicyDecision:
    """Evaluate paper-only policy for a candidate signal."""
    sleeve = canonical_sleeve(signal)
    family = bracket_family(signal)
    raw_edge = raw_side_edge_pp(signal)
    execution_cost = estimate_execution_cost_pp(signal) if config_paper.PAPER_REQUIRE_EXECUTION_MARGIN else 0.0
    fee_margin = float(config_paper.PAPER_FEE_MARGIN_PP) if config_paper.PAPER_REQUIRE_EXECUTION_MARGIN else 0.0
    net_edge = raw_edge - execution_cost - fee_margin
    required = min_required_net_edge_pp(sleeve, family)
    regime, seasonal_mult, regime_mult, final_mult = final_size_multiplier(signal)
    confidence = float(signal.get("confidence_score", 50.0) or 50.0)

    if config_paper.PAPER_SUSPEND_LOWER_WING and family == "lower_tail":
        return PaperPolicyDecision(
            False,
            "suspended_policy",
            "lower/cold wing suspended in paper after report-improvement backtest",
            sleeve,
            family,
            raw_edge,
            execution_cost,
            fee_margin,
            net_edge,
            required,
            seasonal_mult,
            regime,
            regime_mult,
            final_mult,
        )

    if sleeve == "TAIL_NO" and not config_paper.PAPER_TAIL_NO_ENABLED:
        return PaperPolicyDecision(
            False,
            "suspended_policy",
            "TAIL_NO suspended in paper; logged as research candidate only",
            sleeve,
            family,
            raw_edge,
            execution_cost,
            fee_margin,
            net_edge,
            required,
            seasonal_mult,
            regime,
            regime_mult,
            final_mult,
        )
    if sleeve == "DEEP_TAIL_NO" and not config_paper.PAPER_DEEP_TAIL_NO_ENABLED:
        return PaperPolicyDecision(
            False,
            "suspended_policy",
            "DEEP_TAIL_NO disabled by paper config",
            sleeve,
            family,
            raw_edge,
            execution_cost,
            fee_margin,
            net_edge,
            required,
            seasonal_mult,
            regime,
            regime_mult,
            final_mult,
        )
    if sleeve == "CORE" and confidence < float(config_paper.PAPER_CORE_MIN_CONFIDENCE):
        return PaperPolicyDecision(
            False,
            "rejected_low_core_confidence",
            (
                f"CORE confidence {confidence:.1f} below paper minimum "
                f"{config_paper.PAPER_CORE_MIN_CONFIDENCE:.1f}"
            ),
            sleeve,
            family,
            raw_edge,
            execution_cost,
            fee_margin,
            net_edge,
            required,
            seasonal_mult,
            regime,
            regime_mult,
            final_mult,
        )
    if config_paper.PAPER_REQUIRE_EXECUTION_MARGIN and (net_edge + 1e-9) < required:
        return PaperPolicyDecision(
            False,
            "rejected_execution_margin",
            f"net edge {net_edge:.2f}pp below required {required:.2f}pp",
            sleeve,
            family,
            raw_edge,
            execution_cost,
            fee_margin,
            net_edge,
            required,
            seasonal_mult,
            regime,
            regime_mult,
            final_mult,
        )

    return PaperPolicyDecision(
        True,
        "active",
        "accepted by paper policy",
        sleeve,
        family,
        raw_edge,
        execution_cost,
        fee_margin,
        net_edge,
        required,
        seasonal_mult,
        regime,
        regime_mult,
        final_mult,
    )
