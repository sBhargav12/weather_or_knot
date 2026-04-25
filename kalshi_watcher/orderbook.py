from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Tuple

import websockets

import config
from data_ingest.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)


class OrderbookSequenceGap(RuntimeError):
    """Raised when a WebSocket sequence gap makes local books untrustworthy."""


class KalshiOrderBook:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes_bids: Dict[Decimal, Decimal] = {}
        self.no_bids: Dict[Decimal, Decimal] = {}
        self.last_seq: Optional[int] = None
        self.connected = False

    def apply_snapshot(self, msg: dict) -> None:
        data = msg.get("msg", {})
        self.yes_bids = {}
        self.no_bids = {}
        for price_raw, qty_raw in data.get("yes_dollars_fp", data.get("yes", [])):
            price = Decimal(str(price_raw))
            qty = Decimal(str(qty_raw))
            if qty > 0:
                self.yes_bids[price] = qty
        for price_raw, qty_raw in data.get("no_dollars_fp", data.get("no", [])):
            price = Decimal(str(price_raw))
            qty = Decimal(str(qty_raw))
            if qty > 0:
                self.no_bids[price] = qty
        self.last_seq = msg.get("seq")
        self.connected = True

    def apply_delta(self, msg: dict) -> None:
        data = msg.get("msg", {})
        price = Decimal(str(data.get("price_dollars", data.get("price", "0"))))
        delta = Decimal(str(data.get("delta_fp", data.get("delta", "0"))))
        side = data.get("side")
        book = self.yes_bids if side == "yes" else self.no_bids
        new_qty = book.get(price, Decimal("0")) + delta
        if new_qty <= 0:
            book.pop(price, None)
        else:
            book[price] = new_qty
        self.last_seq = msg.get("seq", self.last_seq)

    @property
    def best_yes_bid(self) -> Decimal:
        return max(self.yes_bids.keys()) if self.yes_bids else Decimal("0")

    @property
    def best_no_bid(self) -> Decimal:
        return max(self.no_bids.keys()) if self.no_bids else Decimal("0")

    @property
    def yes_ask(self) -> Decimal:
        return Decimal("1.00") - self.best_no_bid if self.no_bids else Decimal("1.00")

    @property
    def no_ask(self) -> Decimal:
        return Decimal("1.00") - self.best_yes_bid if self.yes_bids else Decimal("1.00")

    @property
    def spread(self) -> Decimal:
        return self.yes_ask - self.best_yes_bid


class KalshiOrderbookManager:
    def __init__(self, key_id: str, key_path: str, db=None):
        self.auth_client = KalshiClient(key_id, key_path)
        self.books: Dict[str, KalshiOrderBook] = {}
        self.price_history: Dict[str, Deque[Tuple[datetime, Decimal]]] = defaultdict(lambda: deque(maxlen=2000))
        self.db = db
        self.last_seq: Optional[int] = None

    async def run(self, tickers: list) -> None:
        if not tickers:
            logger.warning("No Kalshi tickers supplied to orderbook manager")
            await asyncio.sleep(5)
            return
        self.books = {ticker: KalshiOrderBook(ticker) for ticker in tickers}
        backoff = 1
        while True:
            try:
                headers = self.auth_client._sign_request("GET", "/trade-api/ws/v2")
                async with websockets.connect(config.KALSHI_WS_URL, additional_headers=headers, ping_interval=20) as ws:
                    backoff = 1
                    await ws.send(
                        json.dumps(
                            {
                                "id": 1,
                                "cmd": "subscribe",
                                "params": {"channels": ["orderbook_delta"], "market_tickers": tickers},
                            }
                        )
                    )
                    async for raw in ws:
                        msg = json.loads(raw)
                        self.handle_message(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Kalshi WebSocket error: %s. Reconnecting in %ss", exc, backoff)
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    def handle_message(self, msg: dict) -> None:
        ticker = msg.get("msg", {}).get("market_ticker")
        if not ticker:
            return
        seq = msg.get("seq")
        if seq is not None and self.last_seq is not None and seq > self.last_seq + 1:
            expected = self.last_seq + 1
            logger.warning("Kalshi stream sequence gap: expected %s, got %s; reconnecting for fresh snapshots", expected, seq)
            self._invalidate_books()
            self.last_seq = None
            raise OrderbookSequenceGap(f"expected seq {expected}, got {seq}")
        if seq is not None:
            self.last_seq = seq
        book = self.books.setdefault(ticker, KalshiOrderBook(ticker))
        msg_type = msg.get("type")
        if msg_type == "orderbook_snapshot":
            book.apply_snapshot(msg)
        elif msg_type == "orderbook_delta":
            book.apply_delta(msg)
        else:
            return
        now = datetime.now(timezone.utc)
        self.price_history[ticker].append((now, book.best_yes_bid))
        if self.db:
            self.db.insert_kalshi_price(
                {
                    "ticker": ticker,
                    "city": self._city_from_ticker(ticker),
                    "yes_bid": str(book.best_yes_bid),
                    "yes_ask": str(book.yes_ask),
                    "no_bid": str(book.best_no_bid),
                    "no_ask": str(book.no_ask),
                    "spread": str(book.spread),
                    "spread_cents": float(book.spread * 100),
                    "source": "websocket",
                }
            )

    def _invalidate_books(self) -> None:
        for book in self.books.values():
            book.yes_bids.clear()
            book.no_bids.clear()
            book.last_seq = None
            book.connected = False

    def get_current_price(self, ticker: str) -> Decimal:
        return self.books.get(ticker, KalshiOrderBook(ticker)).best_yes_bid

    def get_spread(self, ticker: str) -> Decimal:
        return self.books.get(ticker, KalshiOrderBook(ticker)).spread

    def get_price_history(self, ticker: str, minutes: int) -> list:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [(ts, price) for ts, price in self.price_history.get(ticker, []) if ts >= cutoff]

    def check_reversal_pattern(self, ticker: str) -> bool:
        history = self.get_price_history(ticker, minutes=8 * 60)
        if len(history) < 2:
            return False
        prices = [price for _, price in history]
        max_price = max(prices)
        return any(price >= prices[0] + config.REVERSAL_THRESHOLD for price in prices) and (
            max_price - prices[-1] >= config.REVERSAL_THRESHOLD
        )

    def passes_liquidity_filter(self, ticker: str, bracket_type: str) -> bool:
        spread = self.get_spread(ticker)
        limit = config.LIQUIDITY_CENTRAL_MAX if bracket_type == "central" else config.LIQUIDITY_WING_MAX
        return spread <= limit

    @staticmethod
    def _city_from_ticker(ticker: str) -> str:
        if ticker.startswith("KXHIGHNY"):
            return "KNYC"
        if ticker.startswith("KXHIGHPHL"):
            return "KPHL"
        if ticker.startswith("KXHIGHCHI"):
            return "KMDW"
        return "UNKNOWN"
