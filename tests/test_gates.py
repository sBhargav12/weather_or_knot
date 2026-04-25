from __future__ import annotations

from signal_engine.gate_checker import (
    check_gate_1,
    check_gate_2,
    check_gate_3,
    check_gate_4,
    check_gate_5,
    check_gate_6,
    run_all_gates,
)


# ---------------------------------------------------------------------------
# Gate 1 — TIER 1 (hard requirement)
# ---------------------------------------------------------------------------

def test_gate_1_real_hgefs_pass():
    passed, d = check_gate_1(70.0, 2.0, 71.4, 2.0)
    assert passed is True
    assert d["hgefs_real"] is True
    assert d["confidence_add"] == 30.0


def test_gate_1_real_hgefs_fail_spread_between():
    passed, d = check_gate_1(70.0, 2.0, 71.6, 2.0)
    assert passed is False


def test_gate_1_real_hgefs_fail_physics_spread():
    passed, d = check_gate_1(70.0, 3.1, 71.0, 2.0)
    assert passed is False


def test_gate_1_wethr_proxy_pass():
    models = {"HRRR": 70.0, "NBM": 70.5, "GFS": 69.8, "ECMWF": 70.2}
    passed, d = check_gate_1(None, None, None, None, wethr_models=models)
    assert passed is True
    assert d["hgefs_real"] is False
    assert d["confidence_add"] == 15.0


def test_gate_1_wethr_proxy_too_spread():
    models = {"HRRR": 70.0, "NBM": 73.0, "GFS": 76.0}
    passed, d = check_gate_1(None, None, None, None, wethr_models=models)
    assert passed is False


def test_gate_1_insufficient_models():
    # Only 2 models — below minimum of 3
    models = {"HRRR": 70.0, "NBM": 70.5}
    passed, d = check_gate_1(None, None, None, None, wethr_models=models)
    assert passed is False


# ---------------------------------------------------------------------------
# Gate 2 — TIER 1 (hard requirement, gap > config.MIN_GAP_PP)
# ---------------------------------------------------------------------------

def test_gate_2_gap_above_30pp_high_confidence():
    passed, d = check_gate_2(0.81, 0.50)
    assert passed is True
    assert d["confidence_add"] == 30.0


def test_gate_2_gap_25_to_30pp():
    passed, d = check_gate_2(0.76, 0.50)   # gap = 26pp
    assert passed is True
    assert d["confidence_add"] == 20.0


def test_gate_2_gap_below_configured_floor():
    passed, d = check_gate_2(0.74, 0.50)   # gap = 24pp
    assert passed is False


def test_gate_2_no_direction():
    passed, details = check_gate_2(0.24, 0.50)
    assert passed is True
    assert details["direction"] == "NO"


def test_gate_2_dead_zone_blocks():
    # gap = 37pp (in 35-40pp dead zone) → hard fail
    passed, d = check_gate_2(0.87, 0.50)
    assert passed is False
    assert d["in_dead_zone"] is True


# ---------------------------------------------------------------------------
# Gate 3 — TIER 1 (price band)
# ---------------------------------------------------------------------------

def test_gate_3_uses_traded_side_price():
    assert check_gate_3(0.24, "YES")[0] is False
    assert check_gate_3(0.25, "YES")[0] is True
    assert check_gate_3(0.75, "YES")[0] is True
    assert check_gate_3(0.76, "YES")[0] is False
    assert check_gate_3(0.76, "NO")[0] is False
    assert check_gate_3(0.30, "NO")[0] is True


# ---------------------------------------------------------------------------
# Gate 4 — TIER 2 (confidence modifier, always passes)
# ---------------------------------------------------------------------------

def test_gate_4_always_passes():
    assert check_gate_4(37.0)[0] is True   # dead zone → confidence penalty
    assert check_gate_4(34.0)[0] is True
    assert check_gate_4(41.0)[0] is True


def test_gate_4_dead_zone_reduces_confidence():
    _, d = check_gate_4(37.0)
    assert d["confidence_delta"] == -25.0
    assert d["in_dead_zone"] is True


def test_gate_4_normal_gap_adds_confidence():
    _, d = check_gate_4(25.0)
    assert d["confidence_delta"] == 10.0


# ---------------------------------------------------------------------------
# Gate 5 — TIER 2 (METAR modifier, missing = neutral)
# ---------------------------------------------------------------------------

def test_gate_5_always_passes():
    # Available and confirming
    p, d = check_gate_5(63.0, 70.0, "YES")
    assert p is True
    assert d["confidence_delta"] == 25.0
    # Available but contradicting
    p, d = check_gate_5(61.0, 70.0, "YES")
    assert p is True
    assert d["confidence_delta"] == -15.0
    # Missing METAR — neutral
    p, d = check_gate_5(None, 70.0, "YES")
    assert p is True
    assert d["confidence_delta"] == 0.0


def test_gate_5_no_direction():
    p, d = check_gate_5(66.0, 70.0, "NO")
    assert p is True
    assert d["confidence_delta"] == 25.0


# ---------------------------------------------------------------------------
# Gate 6 — TIER 2 (reversal modifier, always passes)
# ---------------------------------------------------------------------------

def test_gate_6_always_passes():
    # Cold bracket reversal — big confidence penalty but still passes
    p, d = check_gate_6("TICKER", 50.0, [("t0", 0.20), ("t1", 0.32), ("t2", 0.21)])
    assert p is True
    assert d["confidence_delta"] == -30.0
    # Warm bracket reversal — smaller penalty
    p, d = check_gate_6("TICKER", 70.0, [("t0", 0.20), ("t1", 0.32), ("t2", 0.21)])
    assert p is True
    assert d["confidence_delta"] == -15.0
    # No reversal
    p, d = check_gate_6("TICKER", 50.0, [("t0", 0.20)])
    assert p is True
    assert d["confidence_delta"] == 10.0


# ---------------------------------------------------------------------------
# run_all_gates integration
# ---------------------------------------------------------------------------

def test_run_all_gates_good_values_real_hgefs():
    result = run_all_gates(
        physics_mean=70.0,
        physics_spread=2.0,
        ai_mean=70.5,
        ai_spread=2.0,
        model_prob=0.77,
        market_price=0.50,
        yes_price=0.50,
        metar_temp_f=64.0,
        bracket_center_f=70.0,
        bracket_low_f=69.0,
        direction="YES",
        price_history=[],
        ticker="KXHIGHNY-26APR25-T70",
    )
    assert result["all_pass"] is True
    assert result["confidence_score"] > 0
    assert result["gate1"]["hgefs_real"] is True


def test_run_all_gates_wethr_proxy_passes_with_tight_models():
    """With wethr proxy and 4 tight models, Gate 1 should pass (15pp confidence)."""
    result = run_all_gates(
        physics_mean=None,
        physics_spread=None,
        ai_mean=None,
        ai_spread=None,
        model_prob=0.77,
        market_price=0.50,
        yes_price=0.50,
        metar_temp_f=64.0,
        bracket_center_f=70.0,
        bracket_low_f=69.0,
        direction="YES",
        price_history=[],
        ticker="KXHIGHNY-26APR25-T70",
        wethr_models={"HRRR": 70.0, "NBM": 70.3, "GFS": 69.9, "ECMWF": 70.1},
    )
    assert result["all_pass"] is True
    assert result["gate1"]["hgefs_real"] is False
    assert result["gate1"]["pass"] is True


def test_run_all_gates_bad_hgefs_no_proxy_fails():
    result = run_all_gates(70, 2, 72, 2, 0.72, 0.50, 0.50, 64, 70, 69, "YES", [], "T")
    assert result["all_pass"] is False
    assert result["skip_reason"] == "gate1_fail"


def test_run_all_gates_gap_below_configured_floor_fails():
    # gap = 24pp — below the 25pp production floor
    result = run_all_gates(70, 2, 70.5, 2, 0.74, 0.50, 0.50, 64, 70, 69, "YES", [], "T")
    assert result["all_pass"] is False
    assert result["skip_reason"] == "gate2_fail"


def test_run_all_gates_dead_zone_still_fails_gate2():
    # dead zone integrated into gate 2 check
    dead_zone = run_all_gates(70, 2, 70.5, 2, 0.87, 0.50, 0.50, 64, 70, 69, "YES", [], "T")
    assert dead_zone["gate2"]["in_dead_zone"] is True
    assert dead_zone["all_pass"] is False
