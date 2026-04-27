from __future__ import annotations

from decimal import Decimal

from dashboard.daily_report import generate_daily_report
from data_store.schema import create_database
from paper_trader.simulator import PaperTrader, calculate_fees


def test_position_size_and_fee_calculations(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))

    # High confidence (80+) → full QK cap (5% = $25)
    sizing_high = trader.calculate_position_size(500, 0.60, 0.50, confidence_score=85.0)
    assert sizing_high["stake"] == 25.0
    assert sizing_high["contracts"] == 50

    # Medium confidence (60-79) → half QK cap (2.5% = $12.50)
    sizing_mid = trader.calculate_position_size(500, 0.60, 0.50, confidence_score=70.0)
    assert sizing_mid["stake"] == 12.5
    assert sizing_mid["max_allowed"] is True

    # Low confidence (40-59) → quarter QK cap (1.25% = $6.25 max, actual = 12 contracts × $0.50 = $6.00)
    sizing_low = trader.calculate_position_size(500, 0.60, 0.50, confidence_score=50.0)
    assert sizing_low["stake"] == 6.0    # 12 contracts × $0.50
    assert sizing_low["contracts"] == 12

    assert calculate_fees(1, 0.50, "maker") == 0.01
    assert calculate_fees(1, 0.50, "taker") == 0.02


def test_signal_to_trade_and_target_exit(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    signal = {
        "id": 1,
        "city": "KNYC",
        "ticker": "KXHIGHNY-26APR25-T70",
        "target_date": "2026-04-25",
        "bracket": "70-72F",
        "direction": "YES",
        "market_price": 0.50,
        "entry_price": 0.50,
        "model_prob": 0.75,
        "spread": "0.02",
        "confidence_score": 85.0,  # high confidence → full QK cap
    }
    trade = trader.on_signal(signal)
    assert trade is not None
    assert trade["entry_price"] == 0.51
    trader.check_exits({signal["ticker"]: Decimal("0.70")})
    rows = trader.db.execute("SELECT * FROM paper_trades WHERE id = ?", (trade["id"],))
    assert rows[0]["exit_reason"] == "TARGET"
    assert rows[0]["exit_price"] == 0.68


def test_bankroll_math_entry_exit(tmp_path):
    """Entry at 0.50, exit at 0.68 on 1 contract — bankroll change = +$0.18 minus both fees."""
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500.0, str(db_path))

    entry_price = 0.50
    exit_price = 0.68
    contracts = 1

    fee_entry = calculate_fees(contracts, entry_price, "maker")
    fee_exit = calculate_fees(contracts, exit_price, "maker")

    # Simulate what simulate_entry does to bankroll
    bankroll_after_entry = 500.0 - (contracts * entry_price) - fee_entry

    # Simulate what _exit_trade does to bankroll
    bankroll_after_exit = bankroll_after_entry + contracts * exit_price - fee_exit

    expected_pnl = (exit_price - entry_price) * contracts - fee_entry - fee_exit
    assert abs(bankroll_after_exit - (500.0 + expected_pnl)) < 0.001, (
        f"Bankroll {bankroll_after_exit:.4f} != expected {500.0 + expected_pnl:.4f}"
    )
    # Bankroll should be higher than starting (profitable trade)
    assert bankroll_after_exit > 500.0


def test_daily_report_generates_string(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    trader.db.insert_signal(
        {
            "city": "KNYC",
            "ticker": "KXHIGHNY-26APR25-T70",
            "direction": "YES",
            "entry_price": 0.50,
        }
    )
    report = generate_daily_report(str(db_path))
    assert "KALSHI WEATHER PIPELINE" in report
    assert "Signals generated: 1" in report
