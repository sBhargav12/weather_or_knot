from __future__ import annotations

import pandas as pd

from features.bracket_targets import build_feature_matrix
from models.distributional_temp import DistributionalTempModel


def test_bracket_probs_sum_to_one():
    model = DistributionalTempModel()
    brackets = [
        {"ticker": "T60", "lo_f": 0, "hi_f": 62, "bracket_type": "lower_tail"},
        {"ticker": "T64", "lo_f": 62, "hi_f": 64, "bracket_type": "range"},
        {"ticker": "T66", "lo_f": 64, "hi_f": 66, "bracket_type": "range"},
        {"ticker": "T68", "lo_f": 66, "hi_f": 68, "bracket_type": "range"},
        {"ticker": "T70", "lo_f": 68, "hi_f": 70, "bracket_type": "range"},
        {"ticker": "T72", "lo_f": 70, "hi_f": 999, "bracket_type": "upper_tail"},
    ]
    probs = model.bracket_probabilities(68.0, brackets)
    assert abs(sum(probs.values()) - 1.0) < 0.001
    assert all(prob >= 0 for prob in probs.values())


def test_bracket_probs_no_negatives_with_extreme_consensus():
    model = DistributionalTempModel()
    brackets = [
        {"ticker": "A", "lo_f": 0, "hi_f": 50, "bracket_type": "lower_tail"},
        {"ticker": "B", "lo_f": 50, "hi_f": 52, "bracket_type": "range"},
        {"ticker": "C", "lo_f": 52, "hi_f": 999, "bracket_type": "upper_tail"},
    ]
    probs = model.bracket_probabilities(90.0, brackets)
    assert all(prob >= 0 for prob in probs.values())
    assert abs(sum(probs.values()) - 1.0) < 0.001


def test_lower_middle_upper_cover_whole_distribution():
    model = DistributionalTempModel()
    brackets = [
        {"ticker": "LOW", "lo_f": None, "hi_f": 60, "bracket_type": "lower_tail"},
        {"ticker": "MID", "lo_f": 60, "hi_f": 80, "bracket_type": "range"},
        {"ticker": "HIGH", "lo_f": 80, "hi_f": None, "bracket_type": "upper_tail"},
    ]
    probs = model.bracket_probabilities(70.0, brackets)
    assert set(probs) == {"LOW", "MID", "HIGH"}
    assert abs(sum(probs.values()) - 1.0) < 0.001
    assert probs["MID"] > probs["LOW"]
    assert probs["MID"] > probs["HIGH"]


def test_feature_matrix_contains_core_research_features():
    markets = pd.DataFrame(
        [
            {"date": "2025-06-15", "ticker": "LOW", "lo_f": None, "hi_f": 66, "bracket_type": "lower_tail", "market_price": 0.10},
            {"date": "2025-06-15", "ticker": "MID", "lo_f": 66, "hi_f": 68, "bracket_type": "range", "market_price": 0.60},
            {"date": "2025-06-15", "ticker": "HIGH", "lo_f": 68, "hi_f": None, "bracket_type": "upper_tail", "market_price": 0.30},
        ]
    )
    forecasts = pd.DataFrame(
        [
            {"date": "2025-06-14", "gfs_maxt": 65.0, "ecmwf_maxt": 66.0, "ukmo_maxt": 65.5, "nbm_maxt": 66.0},
            {"date": "2025-06-15", "gfs_maxt": 67.0, "ecmwf_maxt": 68.0, "ukmo_maxt": 67.5, "nbm_maxt": 68.0},
        ]
    )
    obs = pd.DataFrame([{"date": "2025-06-14", "actual_temp_f": 66.5}])

    features = build_feature_matrix(markets, forecasts, obs, entry_time="11:00")

    assert len(features) == 3
    assert {"consensus_temp_f", "model_spread_f", "distance_lo_f", "distance_hi_f", "gap_pp"}.issubset(features.columns)
    assert abs(features["model_prob"].sum() - 1.0) < 0.001
    assert features["hours_to_close"].iloc[0] == 12.0
