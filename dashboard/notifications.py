from __future__ import annotations

import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


def notify_phone(title: str, message: str, *, priority: str = "default", tags: str = "") -> None:
    """Best-effort phone notification via ntfy."""
    topic = config.NTFY_TOPIC.strip()
    if not topic:
        logger.info("phone notification skipped: NTFY_TOPIC is not set title=%r", title)
        return
    url = f"{config.NTFY_URL.rstrip('/')}/{topic}"
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        response.raise_for_status()
        logger.info("phone notification sent: title=%r status=%s", title, response.status_code)
    except Exception as exc:
        logger.warning("phone notification failed: title=%r error=%s", title, exc)


def format_trade_entry(trade: dict[str, Any]) -> str:
    return (
        f"{trade.get('direction')} {trade.get('contracts')}x {trade.get('ticker')}\n"
        f"Bracket: {trade.get('bracket')}\n"
        f"Entry: {float(trade.get('entry_price', 0)):.2f}\n"
        f"Stake: ${float(trade.get('stake_dollars', 0)):.2f}\n"
        f"Sleeve: {trade.get('strategy_sleeve')}"
    )


def format_trade_exit(trade: dict[str, Any], exit_price: float, reason: str, net_pnl_maker: float) -> str:
    return (
        f"{trade.get('direction')} {trade.get('contracts')}x {trade.get('ticker')}\n"
        f"Bracket: {trade.get('bracket')}\n"
        f"Exit: {exit_price:.2f} ({reason})\n"
        f"Net P&L: ${net_pnl_maker:.2f}"
    )
