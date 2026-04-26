from __future__ import annotations

from paper_trader.policy import bracket_family, min_required_net_edge_pp, paper_policy_allows_trade


def test_bracket_family_classification():
    assert bracket_family({"bracket": "<=60F"}) == "lower_tail"
    assert bracket_family({"bracket": ">=80F"}) == "upper_tail"
    assert bracket_family({"bracket": "70-72F"}) == "central"


def test_wing_and_central_have_different_thresholds():
    assert min_required_net_edge_pp("CORE", "central") > min_required_net_edge_pp("CORE", "upper_tail")


def test_wing_can_pass_where_central_fails():
    common = {
        "strategy_sleeve": "CORE_HGEFS_GUMBEL",
        "direction": "YES",
        "model_prob": 0.679,
        "entry_price": 0.58,
        "market_price": 0.58,
        "spread": "0.02",
        "target_date": "2026-04-25",
    }
    central = paper_policy_allows_trade({**common, "bracket": "70-72F"})
    wing = paper_policy_allows_trade({**common, "bracket": ">=80F"})
    assert not central.allowed
    assert wing.allowed
