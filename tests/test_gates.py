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


def test_gate_1_thresholds():
    assert check_gate_1(70.0, 2.0, 71.4, 2.0)[0] is True
    assert check_gate_1(70.0, 2.0, 71.6, 2.0)[0] is False
    assert check_gate_1(70.0, 3.1, 71.0, 2.0)[0] is False


def test_gate_2_gap_thresholds():
    assert check_gate_2(0.71, 0.50)[0] is True
    assert check_gate_2(0.69, 0.50)[0] is False
    passed, details = check_gate_2(0.29, 0.50)
    assert passed is True
    assert details["direction"] == "NO"


def test_gate_3_uses_traded_side_price():
    assert check_gate_3(0.24, "YES")[0] is False
    assert check_gate_3(0.25, "YES")[0] is True
    assert check_gate_3(0.75, "YES")[0] is True
    assert check_gate_3(0.76, "YES")[0] is False
    assert check_gate_3(0.76, "NO")[0] is False
    assert check_gate_3(0.30, "NO")[0] is True


def test_gate_4_dead_zone():
    assert check_gate_4(37.0)[0] is False
    assert check_gate_4(34.0)[0] is True
    assert check_gate_4(41.0)[0] is True


def test_gate_5_metar_confirmation():
    assert check_gate_5(63.0, 70.0, "YES")[0] is True
    assert check_gate_5(61.0, 70.0, "YES")[0] is False
    assert check_gate_5(66.0, 70.0, "NO")[0] is True
    assert check_gate_5(68.0, 70.0, "NO")[0] is False


def test_gate_6_reversal_on_cold_bracket_fails():
    assert check_gate_6("TICKER", 50.0, [("t0", 0.20), ("t1", 0.32), ("t2", 0.21)])[0] is False
    assert check_gate_6("TICKER", 70.0, [("t0", 0.20), ("t1", 0.32), ("t2", 0.21)])[0] is True
    assert check_gate_6("TICKER", 50.0, [("t0", 0.20)])[0] is True


def test_run_all_gates_good_values():
    result = run_all_gates(
        physics_mean=70.0,
        physics_spread=2.0,
        ai_mean=70.5,
        ai_spread=2.0,
        model_prob=0.72,
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


def test_run_all_gates_bad_hgefs_and_dead_zone():
    bad_hgefs = run_all_gates(70, 2, 72, 2, 0.72, 0.50, 0.50, 64, 70, 69, "YES", [], "T")
    assert bad_hgefs["all_pass"] is False
    assert bad_hgefs["skip_reason"] == "gate1_fail"

    dead_zone = run_all_gates(70, 2, 70.5, 2, 0.87, 0.50, 0.50, 64, 70, 69, "YES", [], "T")
    assert dead_zone["gate4"]["pass"] is False
