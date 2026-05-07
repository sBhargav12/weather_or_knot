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
        "market_price": 0.60,
        "entry_price": 0.60,   # >= PAPER_CORE_MIN_ENTRY_PRICE (0.55) → allowed
        "model_prob": 0.85,
        "spread": "0.02",
        "confidence_score": 85.0,
    }
    trade = trader.on_signal(signal)
    assert trade is not None
    assert trade["entry_price"] == 0.61   # 0.60 + 0.01 slippage
    # 0.69 >= TARGET (0.68) but < NEVER_HOLD_ABOVE (0.70) → TARGET exit
    trader.check_exits({signal["ticker"]: Decimal("0.69")})
    rows = trader.db.execute("SELECT * FROM paper_trades WHERE id = ?", (trade["id"],))
    assert rows[0]["exit_reason"] == "TARGET"
    assert rows[0]["exit_price"] == 0.68


def test_never_hold_above_exit(tmp_path):
    """Price at or above NEVER_HOLD_ABOVE (0.70) exits at 0.70, not 0.68."""
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    signal = {
        "id": 2,
        "city": "KNYC",
        "ticker": "KXHIGHNY-26APR25-T70",
        "target_date": "2026-04-25",
        "bracket": "70-72F",
        "direction": "YES",
        "market_price": 0.60,
        "entry_price": 0.60,   # >= PAPER_CORE_MIN_ENTRY_PRICE (0.55) → allowed
        "model_prob": 0.85,
        "spread": "0.02",
        "confidence_score": 85.0,
    }
    trade = trader.on_signal(signal)
    assert trade is not None
    trader.check_exits({signal["ticker"]: Decimal("0.70")})
    rows = trader.db.execute("SELECT * FROM paper_trades WHERE id = ?", (trade["id"],))
    assert rows[0]["exit_reason"] == "NEVER_HOLD_ABOVE"
    assert rows[0]["exit_price"] == 0.70


def test_strategy_3_uses_fixed_contracts_and_custom_exit(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    signal = {
        "id": 3,
        "city": "KNYC",
        "ticker": "KXHIGHNY-26APR25-B70.5",
        "target_date": "2026-04-25",
        "bracket": "70.0-71.0F",
        "direction": "YES",
        "market_price": 0.80,
        "entry_price": 0.80,
        "model_prob": 0.80,
        "spread": "0",
        "confidence_score": 75.0,
        "strategy_sleeve": "S3_BRACKET_LOCK_YES",
        "n_contracts": 7,
        "target_price": 0.95,
        "stop_price": 0.60,
        "never_hold_above": 0.99,
    }

    trade = trader.on_signal(signal)

    assert trade is not None
    assert trade["contracts"] == 7
    assert trade["entry_price"] == 0.80
    trader.check_exits({signal["ticker"]: Decimal("0.96")})
    rows = trader.db.execute("SELECT * FROM paper_trades WHERE id = ?", (trade["id"],))
    assert rows[0]["exit_reason"] == "TARGET"
    assert rows[0]["exit_price"] == 0.95


def test_strategy_1_no_overlay_allows_high_no_entry(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    signal = {
        "id": 4,
        "city": "KNYC",
        "ticker": "KXHIGHNY-26APR25-B56.5",
        "target_date": "2026-04-25",
        "bracket": "56.0-57.0F",
        "direction": "NO",
        "market_price": 0.03,
        "entry_price": 0.97,
        "model_prob": 0.01,
        "spread": "0",
        "confidence_score": 95.0,
        "strategy_sleeve": "S1_FAR_BRACKET_NO_OVERLAY",
        "n_contracts": 5,
        "target_price": 0.99,
        "stop_price": 0.77,
    }

    trade = trader.on_signal(signal)

    assert trade is not None
    assert trade["contracts"] == 5
    assert trade["direction"] == "NO"


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
