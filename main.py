#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_venv() -> None:
    venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_bootstrap_venv()

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import config
from dashboard.daily_report import generate_daily_report
from data_ingest.kalshi_client import KalshiClient
from data_ingest.model_fetcher import ModelFetcher
from data_ingest.wethr_client import WethrClient
from data_ingest.wethr_stream import WethrStreamClient
from data_store.db import Database
from data_store.schema import create_database
from kalshi_watcher.orderbook import KalshiOrderbookManager
from live_trader import config_live
from live_trader.trader import LiveTrader
from paper_trader.simulator import PaperTrader
from signal_engine.event_triggers import EventTriggerEngine
from signal_engine.gumbel_model import GumbelModel


@dataclass
class MarketDataUniverse:
    tickers: list[str] = field(default_factory=list)

    def update(self, tickers: list[str]) -> None:
        self.tickers = sorted(set(tickers))

    def current(self) -> list[str]:
        return list(self.tickers)


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler("logs/pipeline.log", maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def validate_credentials(require_wethr: bool = True) -> None:
    missing = []
    if not config.KALSHI_API_KEY:
        missing.append("KALSHI_API_KEY")
    if not config.KALSHI_KEY_PATH:
        missing.append("KALSHI_KEY_PATH")
    if require_wethr and not config.WETHR_API_KEY:
        missing.append("WETHR_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    if not Path(config.KALSHI_KEY_PATH).expanduser().exists():
        raise RuntimeError(f"Kalshi key file not found: {config.KALSHI_KEY_PATH}")


def _collection_city_configs(include_inactive: bool = True) -> list[tuple[str, dict]]:
    return [
        (city, cfg)
        for city, cfg in config.CITIES.items()
        if cfg.get("active") or include_inactive
    ]


def _collection_target_dates(cfg: dict) -> set[str]:
    tz = ZoneInfo(cfg.get("timezone", "America/New_York"))
    today = datetime.now(tz).date()
    return {
        (today + timedelta(days=offset)).isoformat()
        for offset in range(config.KALSHI_COLLECT_TARGET_DAYS + 1)
    }


def _store_rest_market_snapshot(db: Database, city: str, bracket: dict) -> None:
    db.insert_kalshi_price(
        {
            "ticker": bracket["ticker"],
            "city": city,
            "target_date": bracket.get("target_date"),
            "bracket_label": bracket.get("bracket_label"),
            "strike_lo": bracket.get("strike_lo"),
            "strike_hi": bracket.get("strike_hi"),
            "bracket_type": bracket.get("bracket_type"),
            "yes_bid": str(bracket.get("yes_bid")) if bracket.get("yes_bid") is not None else None,
            "yes_ask": str(bracket.get("yes_ask")) if bracket.get("yes_ask") is not None else None,
            "yes_last": str(bracket.get("yes_last")) if bracket.get("yes_last") is not None else None,
            "no_bid": str(bracket.get("no_bid")) if bracket.get("no_bid") is not None else None,
            "no_ask": str(bracket.get("no_ask")) if bracket.get("no_ask") is not None else None,
            "spread": str(bracket.get("spread")) if bracket.get("spread") is not None else None,
            "spread_cents": bracket.get("spread_cents"),
            "volume": bracket.get("volume"),
            "open_interest": bracket.get("open_interest"),
            "source": "rest_collector",
        }
    )


def collect_market_data_once(
    kalshi: KalshiClient,
    db: Database | None,
    *,
    include_inactive: bool = True,
    store_snapshots: bool = True,
) -> list[str]:
    """Collect REST top-of-book snapshots and return current websocket universe."""
    tickers: list[str] = []
    logger = logging.getLogger("market_data")
    for city, cfg in _collection_city_configs(include_inactive=include_inactive):
        target_dates = _collection_target_dates(cfg)
        try:
            markets = kalshi.get_active_markets(cfg["series_ticker"])
            brackets = kalshi.parse_brackets(markets)
        except Exception as exc:
            logger.warning("Kalshi REST collection failed for %s: %s", city, exc)
            continue
        kept = 0
        for bracket in brackets:
            if bracket.get("target_date") not in target_dates:
                continue
            kept += 1
            tickers.append(bracket["ticker"])
            if store_snapshots and db is not None:
                _store_rest_market_snapshot(db, city, bracket)
        logger.info(
            "Collected %d/%d %s markets for %s",
            kept,
            len(brackets),
            cfg["series_ticker"],
            ", ".join(sorted(target_dates)),
        )
    return sorted(set(tickers))


async def market_data_collection_loop(
    kalshi: KalshiClient,
    db: Database | None,
    universe: MarketDataUniverse,
    *,
    include_inactive: bool = True,
    store_snapshots: bool = True,
) -> None:
    logger = logging.getLogger("market_data")
    while True:
        try:
            tickers = await asyncio.to_thread(
                collect_market_data_once,
                kalshi,
                db,
                include_inactive=include_inactive,
                store_snapshots=store_snapshots,
            )
            universe.update(tickers)
            logger.info("Market data universe now has %d today/tomorrow tickers", len(tickers))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Market data collection loop failed: %s", exc)
        await asyncio.sleep(config.KALSHI_REST_COLLECTION_INTERVAL_SECONDS)


async def build_engine() -> tuple[EventTriggerEngine, KalshiOrderbookManager, MarketDataUniverse]:
    create_database(config.DB_PATH)
    db = Database(config.DB_PATH)
    wethr = WethrClient(config.WETHR_API_KEY)
    kalshi = KalshiClient(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH)
    model_fetcher = ModelFetcher()
    gumbel = GumbelModel()
    paper_trader = PaperTrader(config.STARTING_BANKROLL, config.DB_PATH)

    universe = MarketDataUniverse()
    universe.update(
        await asyncio.to_thread(
            collect_market_data_once,
            kalshi,
            None,
            include_inactive=False,
            store_snapshots=False,
        )
    )

    live_trader = None
    if config_live.LIVE_TRADING_ENABLED and not config_live.LIVE_KILL_SWITCH:
        live_trader = LiveTrader(config_live.LIVE_BANKROLL, config.DB_PATH, kalshi)
        logging.getLogger("main").info(
            "Live trading ENABLED — sleeve=%s bankroll=$%.2f",
            config_live.LIVE_SLEEVE,
            config_live.LIVE_BANKROLL,
        )
    else:
        logging.getLogger("main").info("Live trading DISABLED (set LIVE_TRADING_ENABLED=true to enable)")

    orderbook_manager = KalshiOrderbookManager(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH, db=None)
    engine = EventTriggerEngine(
        wethr=wethr,
        kalshi=kalshi,
        model_fetcher=model_fetcher,
        gumbel=gumbel,
        paper_trader=paper_trader,
        orderbook_manager=orderbook_manager,
        db=db,
        live_trader=live_trader,
    )
    active_stations = [
        cfg["wethr_station"]
        for city, cfg in config.CITIES.items()
        if cfg.get("active")
    ]
    if active_stations and config.WETHR_API_KEY:
        stream_client = WethrStreamClient(config.WETHR_API_KEY, active_stations)
        stream_client.register_new_high(engine.on_stream_new_high)
        stream_client.register_cli(engine.on_stream_cli)
        stream_client.register_dsm(engine.on_stream_dsm)
        engine.stream_client = stream_client
        logging.getLogger("main").info(
            "WethrStreamClient configured for stations: %s", active_stations
        )

    return engine, orderbook_manager, universe


async def build_market_data_collector() -> tuple[KalshiClient, Database, KalshiOrderbookManager, MarketDataUniverse]:
    create_database(config.DB_PATH)
    db = Database(config.DB_PATH)
    kalshi = KalshiClient(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH)
    universe = MarketDataUniverse()
    universe.update(
        await asyncio.to_thread(
            collect_market_data_once,
            kalshi,
            db,
            include_inactive=config.COLLECT_MARKET_DATA_FOR_INACTIVE_CITIES,
            store_snapshots=True,
        )
    )
    orderbook_manager = KalshiOrderbookManager(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH, db=db)
    return kalshi, db, orderbook_manager, universe


async def async_main(args: argparse.Namespace) -> None:
    logger = logging.getLogger("main")
    setup_logging()
    validate_credentials(require_wethr=not args.collect_only)

    if args.collect_only:
        kalshi, db, orderbook_manager, universe = await build_market_data_collector()
        logger.info("Starting Kalshi market-data collector with %d initial tickers", len(universe.current()))
        if args.once:
            return
        tasks = [
            asyncio.create_task(orderbook_manager.run_dynamic(universe.current)),
            asyncio.create_task(
                market_data_collection_loop(
                    kalshi,
                    db,
                    universe,
                    include_inactive=config.COLLECT_MARKET_DATA_FOR_INACTIVE_CITIES,
                    store_snapshots=True,
                )
            ),
        ]
        if args.duration:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=args.duration)
            except TimeoutError:
                logger.info("Duration reached; shutting down collector cleanly")
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            await asyncio.gather(*tasks)
        return

    engine, orderbook_manager, universe = await build_engine()
    logger.info("Starting paper trading pipeline with $%.2f bankroll", config.STARTING_BANKROLL)
    logger.info("Initial market-data tickers: %s", universe.current())

    if args.report:
        print(generate_daily_report(config.DB_PATH, args.report))
        return

    if args.once:
        await engine.run_once()
        return

    tasks = [
        asyncio.create_task(orderbook_manager.run_dynamic(universe.current)),
        asyncio.create_task(
            market_data_collection_loop(
                engine.kalshi,
                None,
                universe,
                include_inactive=False,
                store_snapshots=False,
            )
        ),
        asyncio.create_task(engine.run_forever()),
        asyncio.create_task(
            engine.stream_client.run_forever() if engine.stream_client is not None
            else asyncio.sleep(0)
        ),
    ]
    if args.duration:
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=args.duration)
        except TimeoutError:
            logger.info("Duration reached; shutting down cleanly")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    else:
        await asyncio.gather(*tasks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kalshi weather paper-trading pipeline")
    parser.add_argument("--once", action="store_true", help="Run one polling pass and exit")
    parser.add_argument("--duration", type=int, default=0, help="Run for N seconds, then exit")
    parser.add_argument("--report", help="Print daily report for YYYY-MM-DD and exit")
    parser.add_argument("--collect-only", action="store_true", help="Collect Kalshi market/orderbook data without signal checks")
    return parser.parse_args()


def main() -> None:
    asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    main()
