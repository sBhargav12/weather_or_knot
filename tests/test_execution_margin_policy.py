from __future__ import annotations

from paper_trader.policy import estimate_execution_cost_pp, paper_policy_allows_trade


def test_execution_margin_can_reject_positive_raw_edge():
    signal = {
        "strategy_sleeve": "CORE_HGEFS_GUMBEL",
        "direction": "YES",
        "model_prob": 0.60,
        "entry_price": 0.55,
        "market_price": 0.55,
        "spread": "0.06",
        "bracket": "70-72F",
        "target_date": "2026-01-15",
        "confidence_score": 70.0,
    }
    decision = paper_policy_allows_trade(signal)
    assert decision.raw_edge_pp > 0
    assert decision.est_net_edge_pp < decision.min_required_net_edge_pp
    assert decision.candidate_status == "rejected_execution_margin"
    assert not decision.allowed


def test_execution_cost_uses_observed_spread_when_available():
    signal = {"spread": "0.04", "bracket": "70-72F", "entry_price": 0.50}
    # Observed half-spread reserve 2pp + maker-fee reserve 1pp + core stress buffer 3pp.
    assert estimate_execution_cost_pp(signal) == 6.0


def test_core_low_confidence_is_rejected():
    signal = {
        "strategy_sleeve": "CORE_HGEFS_GUMBEL",
        "direction": "YES",
        "model_prob": 0.90,
        "entry_price": 0.55,
        "market_price": 0.55,
        "spread": "0.02",
        "bracket": "70-72F",
        "target_date": "2026-04-25",
        "confidence_score": 55.0,
    }
    decision = paper_policy_allows_trade(signal)
    assert not decision.allowed
    assert decision.candidate_status == "rejected_low_core_confidence"
