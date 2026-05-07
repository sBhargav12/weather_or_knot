from __future__ import annotations


def test_paper_config_imports_cleanly():
    from paper_trader import config_paper

    assert config_paper.PAPER_USE_RESEARCH_WEIGHTS is True
    assert config_paper.PAPER_TAIL_NO_ENABLED is False
    assert config_paper.PAPER_DEEP_TAIL_NO_ENABLED is True
    assert config_paper.PAPER_USE_CALIBRATED_PROBS is False
    assert config_paper.PAPER_SUSPEND_LOWER_WING is True
    assert config_paper.PAPER_CORE_MIN_CONFIDENCE == 60.0
    assert config_paper.PAPER_SLEEVE_STATES["S3_BRACKET_LOCK_YES"] == "paper_only"
    assert config_paper.PAPER_SLEEVE_STATES["S1_FAR_BRACKET_NO_OVERLAY"] == "paper_only"


def test_paper_config_keeps_live_threshold_separate():
    import config
    from paper_trader import config_paper

    assert config.MIN_GAP_PP == 20.0
    assert config_paper.PAPER_MIN_NET_EDGE_PP_CORE != config.MIN_GAP_PP
    assert config_paper.PAPER_MIN_NET_EDGE_PP_CORE == 10.0


def test_strategy_1_and_3_policy_sleeves_are_dedicated():
    from paper_trader.policy import paper_policy_allows_trade

    s3 = paper_policy_allows_trade(
        {
            "strategy_sleeve": "S3_BRACKET_LOCK_YES",
            "direction": "YES",
            "entry_price": 0.62,
            "market_price": 0.62,
            "model_prob": 0.0,
            "confidence_score": 75.0,
            "bracket": "50.0-51.0F",
        }
    )
    assert s3.allowed is True
    assert s3.min_required_net_edge_pp == 0.0

    s1 = paper_policy_allows_trade(
        {
            "strategy_sleeve": "S1_FAR_BRACKET_NO_OVERLAY",
            "direction": "NO",
            "entry_price": 0.97,
            "market_price": 0.03,
            "model_prob": 0.01,
            "confidence_score": 95.0,
            "bracket": "56.0-57.0F",
        }
    )
    assert s1.allowed is True
    assert s1.min_required_net_edge_pp == 0.0
