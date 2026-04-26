from __future__ import annotations

from dashboard.daily_report import generate_daily_report, print_paper_strategy_health
from data_store.schema import create_database


def test_report_builder_no_current_trades(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    report = print_paper_strategy_health(str(db_path), "2026-04-25")
    assert "PAPER STRATEGY HEALTH" in report
    assert "TAIL_NO=suspended_policy" in report


def test_daily_report_includes_paper_strategy_health(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    report = generate_daily_report(str(db_path), "2026-04-25")
    assert "PAPER STRATEGY HEALTH" in report
    assert "paper policy only" in report
