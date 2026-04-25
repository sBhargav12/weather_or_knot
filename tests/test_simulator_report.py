from __future__ import annotations

from decimal import Decimal

from dashboard.daily_report import generate_daily_report
from data_store.schema import create_database
from paper_trader.simulator import PaperTrader, calculate_fees


def test_position_size_and_fee_calculations(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    sizing = trader.calculate_position_size(500, 0.60, 0.50)
    assert sizing["stake"] == 25.0
    assert sizing["contracts"] == 50
    assert sizing["max_allowed"] is False
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
        "model_prob": 0.60,
        "spread": "0.02",
    }
    trade = trader.on_signal(signal)
    assert trade is not None
    assert trade["entry_price"] == 0.51
    trader.check_exits({signal["ticker"]: Decimal("0.70")})
    rows = trader.db.execute("SELECT * FROM paper_trades WHERE id = ?", (trade["id"],))
    assert rows[0]["exit_reason"] == "TARGET"
    assert rows[0]["exit_price"] == 0.68


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
