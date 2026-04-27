from __future__ import annotations


def test_paper_config_imports_cleanly():
    import config_paper

    assert config_paper.PAPER_USE_RESEARCH_WEIGHTS is True
    assert config_paper.PAPER_TAIL_NO_ENABLED is False
    assert config_paper.PAPER_DEEP_TAIL_NO_ENABLED is True
    assert config_paper.PAPER_USE_CALIBRATED_PROBS is False
    assert config_paper.PAPER_SUSPEND_LOWER_WING is True
    assert config_paper.PAPER_CORE_MIN_CONFIDENCE == 60.0


def test_paper_config_keeps_live_threshold_separate():
    import config
    import config_paper

    assert config.MIN_GAP_PP == 20.0
    assert config_paper.PAPER_MIN_NET_EDGE_PP_CORE != config.MIN_GAP_PP
    assert config_paper.PAPER_MIN_NET_EDGE_PP_CORE == 10.0
