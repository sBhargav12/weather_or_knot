from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from signal_engine.event_triggers import EventTriggerEngine


def test_brackets_for_target_date_skips_stale_markets():
    brackets = [
        {"ticker": "KXHIGHNY-26APR28-B65.5", "target_date": "2026-04-28"},
        {"ticker": "KXHIGHNY-26APR29-B62.5", "target_date": "2026-04-29"},
        {"ticker": "KXHIGHNY-26APR30-B62.5", "target_date": "2026-04-30"},
    ]

    filtered = EventTriggerEngine._brackets_for_target_date(brackets, "2026-04-29", "KNYC")

    assert [bracket["ticker"] for bracket in filtered] == ["KXHIGHNY-26APR29-B62.5"]


def test_allowed_target_dates_includes_today_and_tomorrow():
    now = datetime(2026, 4, 29, 10, 15, tzinfo=ZoneInfo("America/New_York"))

    assert EventTriggerEngine._allowed_target_dates(now) == {"2026-04-29", "2026-04-30"}


def test_next_day_target_date_returns_tomorrow_for_deep_tail():
    now = datetime(2026, 4, 29, 10, 15, tzinfo=ZoneInfo("America/New_York"))

    assert EventTriggerEngine._next_day_target_date(now) == "2026-04-30"


def test_brackets_for_trading_horizon_allows_only_configured_dates():
    brackets = [
        {"ticker": "KXHIGHNY-26APR28-B65.5", "target_date": "2026-04-28"},
        {"ticker": "KXHIGHNY-26APR29-B62.5", "target_date": "2026-04-29"},
        {"ticker": "KXHIGHNY-26APR30-B63.5", "target_date": "2026-04-30"},
        {"ticker": "KXHIGHNY-26MAY01-B63.5", "target_date": "2026-05-01"},
    ]

    filtered = EventTriggerEngine._brackets_for_trading_horizon(
        brackets,
        {"2026-04-29", "2026-04-30"},
        "KNYC",
    )

    assert [bracket["ticker"] for bracket in filtered] == [
        "KXHIGHNY-26APR29-B62.5",
        "KXHIGHNY-26APR30-B63.5",
    ]


def test_group_brackets_by_target_date():
    grouped = EventTriggerEngine._group_brackets_by_target_date(
        [
            {"ticker": "A", "target_date": "2026-04-29"},
            {"ticker": "B", "target_date": "2026-04-30"},
            {"ticker": "C", "target_date": "2026-04-29"},
        ]
    )

    assert [bracket["ticker"] for bracket in grouped["2026-04-29"]] == ["A", "C"]
    assert [bracket["ticker"] for bracket in grouped["2026-04-30"]] == ["B"]


def test_deep_tail_no_sleeve_accepts_nbm_context_without_name_error():
    class StubDb:
        def insert_candidate_signal(self, data):
            return 1

        def insert_signal(self, data):
            return 1

    class StubTrader:
        def on_signal(self, signal):
            return None

    engine = object.__new__(EventTriggerEngine)
    engine.db = StubDb()
    engine.paper_trader = StubTrader()

    engine._check_deep_tail_no_sleeve(
        "KNYC",
        {
            "ticker": "KXHIGHNY-26MAY06-T80",
            "bracket_label": ">=80F",
            "bracket_type": "wing_high",
            "strike_lo": 80.0,
            "spread": "0.01",
        },
        "2026-05-06",
        0.01,
        0.08,
        {
            "physics_mean": 70.0,
            "physics_spread": 1.0,
            "ai_mean": 70.5,
            "ai_spread": 1.0,
        },
        {},
        {},
        None,
    )
