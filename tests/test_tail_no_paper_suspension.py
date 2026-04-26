from __future__ import annotations

from data_store.schema import create_database
from paper_trader.policy import paper_policy_allows_trade
from paper_trader.simulator import PaperTrader


def test_tail_no_paper_suspension_works():
    signal = {
        "strategy_sleeve": "TAIL_NO",
        "direction": "NO",
        "model_prob": 0.20,
        "entry_price": 0.40,
        "market_price": 0.62,
        "gap_pp": -42.0,
        "bracket": "70-72F",
        "target_date": "2026-04-25",
    }
    decision = paper_policy_allows_trade(signal)
    assert not decision.allowed
    assert decision.candidate_status == "suspended_policy"


def test_tail_no_logs_candidate_but_creates_no_paper_trade(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500, str(db_path))
    signal = {
        "id": 1,
        "city": "KNYC",
        "ticker": "TAIL",
        "strategy_sleeve": "TAIL_NO",
        "direction": "NO",
        "model_prob": 0.20,
        "entry_price": 0.40,
        "market_price": 0.62,
        "gap_pp": -42.0,
        "bracket": "70-72F",
        "target_date": "2026-04-25",
        "confidence_score": 90,
    }
    assert trader.on_signal(signal) is None
    candidates = trader.db.execute("SELECT * FROM candidate_signals")
    trades = trader.db.execute("SELECT * FROM paper_trades")
    assert len(candidates) == 1
    assert candidates[0]["candidate_status"] == "suspended_policy"
    assert len(trades) == 0


def test_deep_tail_no_remains_eligible():
    signal = {
        "strategy_sleeve": "DEEP_TAIL_NO",
        "direction": "NO",
        "model_prob": 0.01,
        "entry_price": 0.20,
        "market_price": 0.82,
        "gap_pp": -81.0,
        "bracket": ">=80F",
        "target_date": "2026-04-25",
    }
    decision = paper_policy_allows_trade(signal)
    assert decision.allowed
    assert decision.candidate_status == "active"
