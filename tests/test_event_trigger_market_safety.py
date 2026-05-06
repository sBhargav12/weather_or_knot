from __future__ import annotations

from signal_engine.event_triggers import EventTriggerEngine


def test_brackets_for_target_date_skips_stale_markets():
    brackets = [
        {"ticker": "KXHIGHNY-26APR28-B65.5", "target_date": "2026-04-28"},
        {"ticker": "KXHIGHNY-26APR29-B62.5", "target_date": "2026-04-29"},
        {"ticker": "KXHIGHNY-26APR30-B62.5", "target_date": "2026-04-30"},
    ]

    filtered = EventTriggerEngine._brackets_for_target_date(brackets, "2026-04-29", "KNYC")

    assert [bracket["ticker"] for bracket in filtered] == ["KXHIGHNY-26APR29-B62.5"]


def test_brackets_for_trading_horizon_allows_today_and_tomorrow():
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
