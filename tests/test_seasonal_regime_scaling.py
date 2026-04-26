from __future__ import annotations

from paper_trader.policy import final_size_multiplier, regime_for_date


def test_seasonal_regime_scaling_reduces_but_does_not_zero():
    _regime, seasonal, regime_mult, final_mult = final_size_multiplier({"target_date": "2026-01-15"})
    assert seasonal < 1.0
    assert regime_mult > 0.0
    assert final_mult > 0.0


def test_strong_month_can_mildly_boost_but_is_capped():
    _regime, seasonal, _regime_mult, final_mult = final_size_multiplier({"target_date": "2025-10-15"})
    assert seasonal >= 1.0
    assert final_mult <= 1.15


def test_regime_detection():
    assert regime_for_date("2024-12-16") == "pre_HGEFS"
    assert regime_for_date("2024-12-17") == "HGEFS_to_AIFS"
    assert regime_for_date("2026-04-20") == "NBM_v50_on"
