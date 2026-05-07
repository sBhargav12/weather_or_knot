from __future__ import annotations

from data_store.db import Database
from data_store.schema import create_database
from paper_trader.simulator import PaperTrader


def test_no_trade_exit_uses_no_side_price(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    db = Database(str(db_path))
    trade_id = db.insert_paper_trade(
        {
            "city": "KNYC",
            "ticker": "KXHIGHNY-26APR29-B60.5",
            "direction": "NO",
            "contracts": 10,
            "stake_dollars": 5.5,
            "entry_price": 0.55,
            "maker_fee_entry": 0.01,
            "taker_fee_entry": 0.02,
        }
    )
    trader = PaperTrader(500.0, str(db_path))

    # CORE stop is 0.35 wide: stop at max(0, 0.55 - 0.35) = 0.20.
    # YES = 0.82 → NO side price = 0.18, which is below the 0.20 stop.
    trader.check_exits({"KXHIGHNY-26APR29-B60.5": 0.82})

    assert trader.open_trades == {}
    row = db.execute("SELECT exit_price, exit_reason FROM paper_trades WHERE id = ?", (trade_id,))[0]
    assert row["exit_price"] == 0.18
    assert row["exit_reason"] == "STOP"


def test_no_trade_side_price_conversion_for_stop():
    trade = {"direction": "NO"}
    assert PaperTrader.current_side_price(trade, 0.65) == 0.35


def test_high_price_no_trade_does_not_exit_at_yes_target_or_never_hold(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    db = Database(str(db_path))
    trade_id = db.insert_paper_trade(
        {
            "city": "KNYC",
            "ticker": "KXHIGHNY-26APR29-B60.5",
            "direction": "NO",
            "contracts": 10,
            "stake_dollars": 9.0,
            "entry_price": 0.90,
            "maker_fee_entry": 0.01,
            "taker_fee_entry": 0.02,
        }
    )
    trader = PaperTrader(500.0, str(db_path))

    trader.check_exits({"KXHIGHNY-26APR29-B60.5": 0.08})

    assert trade_id in trader.open_trades
    row = db.execute("SELECT exit_reason FROM paper_trades WHERE id = ?", (trade_id,))[0]
    assert row["exit_reason"] is None


def test_open_trades_are_loaded_on_startup_and_block_duplicate_entry(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    db = Database(str(db_path))
    db.insert_paper_trade(
        {
            "city": "KNYC",
            "ticker": "KXHIGHNY-26APR29-B62.5",
            "target_date": "2026-04-29",
            "bracket": "62-63F",
            "direction": "YES",
            "contracts": 1,
            "stake_dollars": 0.3,
            "entry_price": 0.3,
            "strategy_sleeve": "CORE_HGEFS_GUMBEL",
        }
    )

    trader = PaperTrader(500.0, str(db_path))

    assert len(trader.open_trades) == 1
    duplicate = trader.on_signal(
        {
            "city": "KNYC",
            "ticker": "KXHIGHNY-26APR29-B62.5",
            "target_date": "2026-04-29",
            "bracket": "62-63F",
            "direction": "YES",
            "entry_price": 0.3,
            "market_price": 0.3,
            "model_prob": 0.8,
            "gap_pp": 50.0,
            "confidence_score": 80.0,
            "strategy_sleeve": "CORE_HGEFS_GUMBEL",
            "spread": "0",
        }
    )

    assert duplicate is None
    count = db.execute("SELECT COUNT(*) AS n FROM paper_trades")[0]["n"]
    assert count == 1
