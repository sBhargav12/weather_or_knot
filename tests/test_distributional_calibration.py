from __future__ import annotations

import pandas as pd

from models.distributional_temp import DistributionalTempModel


def test_calibrated_probabilities_remain_bounded_and_coherent():
    model = DistributionalTempModel()
    raw = [0.05, 0.15, 0.30, 0.55, 0.80, 0.90, 0.10, 0.20, 0.70, 0.95]
    outcomes = [0, 0, 0, 1, 1, 1, 0, 0, 1, 1]
    assert model.fit_calibrator(raw, outcomes)
    probs = model.calibrated_probabilities({"A": 0.2, "B": 0.3, "C": 0.5})
    assert all(0.0 <= value <= 1.0 for value in probs.values())
    assert abs(sum(probs.values()) - 1.0) < 0.001


def test_small_sample_skips_calibration_without_breaking_probability():
    model = DistributionalTempModel()
    assert not model.fit_calibrator([0.2, 0.8], [0, 1])
    assert model.calibrated_prob(0.25) == 0.25


def test_evaluator_runs_on_small_synthetic_dataset():
    model = DistributionalTempModel()
    predicted = pd.DataFrame(
        [
            {"date": "2025-01-01", "ticker": "LOW", "bracket_type": "lower_tail", "probability": 0.2},
            {"date": "2025-01-01", "ticker": "MID", "bracket_type": "range", "probability": 0.6},
            {"date": "2025-01-01", "ticker": "HIGH", "bracket_type": "upper_tail", "probability": 0.2},
            {"date": "2025-01-02", "ticker": "LOW", "bracket_type": "lower_tail", "probability": 0.1},
            {"date": "2025-01-02", "ticker": "MID", "bracket_type": "range", "probability": 0.3},
            {"date": "2025-01-02", "ticker": "HIGH", "bracket_type": "upper_tail", "probability": 0.6},
        ]
    )
    actual = pd.DataFrame(
        [
            {"date": "2025-01-01", "ticker": "LOW", "bracket_type": "lower_tail", "outcome": 0},
            {"date": "2025-01-01", "ticker": "MID", "bracket_type": "range", "outcome": 1},
            {"date": "2025-01-01", "ticker": "HIGH", "bracket_type": "upper_tail", "outcome": 0},
            {"date": "2025-01-02", "ticker": "LOW", "bracket_type": "lower_tail", "outcome": 0},
            {"date": "2025-01-02", "ticker": "MID", "bracket_type": "range", "outcome": 0},
            {"date": "2025-01-02", "ticker": "HIGH", "bracket_type": "upper_tail", "outcome": 1},
        ]
    )
    result = model.evaluate(predicted, actual)
    assert result["n_days"] == 2
    assert result["n_rows"] == 6
    assert abs(result["prob_mass_check"] - 1.0) < 0.001
    assert "central" in result["central_vs_wing"]
    assert "wing" in result["central_vs_wing"]
