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
from logging.handlers import RotatingFileHandler

import config
from dashboard.daily_report import generate_daily_report
from data_ingest.kalshi_client import KalshiClient
from data_ingest.model_fetcher import ModelFetcher
from data_ingest.wethr_client import WethrClient
from data_store.db import Database
from data_store.schema import create_database
from kalshi_watcher.orderbook import KalshiOrderbookManager
from paper_trader.simulator import PaperTrader
from signal_engine.event_triggers import EventTriggerEngine
from signal_engine.gumbel_model import GumbelModel


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


def validate_credentials() -> None:
    missing = []
    if not config.KALSHI_API_KEY:
        missing.append("KALSHI_API_KEY")
    if not config.KALSHI_KEY_PATH:
        missing.append("KALSHI_KEY_PATH")
    if not config.WETHR_API_KEY:
        missing.append("WETHR_API_KEY")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    if not Path(config.KALSHI_KEY_PATH).expanduser().exists():
        raise RuntimeError(f"Kalshi key file not found: {config.KALSHI_KEY_PATH}")


async def build_engine() -> tuple[EventTriggerEngine, KalshiOrderbookManager, list]:
    create_database(config.DB_PATH)
    db = Database(config.DB_PATH)
    wethr = WethrClient(config.WETHR_API_KEY)
    kalshi = KalshiClient(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH)
    model_fetcher = ModelFetcher()
    gumbel = GumbelModel()
    paper_trader = PaperTrader(config.STARTING_BANKROLL, config.DB_PATH)

    active_tickers = []
    for city, cfg in config.CITIES.items():
        if not cfg.get("active"):
            continue
        markets = kalshi.get_active_markets(cfg["series_ticker"])
        active_tickers.extend(market["ticker"] for market in markets)

    orderbook_manager = KalshiOrderbookManager(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH, db=db)
    engine = EventTriggerEngine(
        wethr=wethr,
        kalshi=kalshi,
        model_fetcher=model_fetcher,
        gumbel=gumbel,
        paper_trader=paper_trader,
        orderbook_manager=orderbook_manager,
        db=db,
    )
    return engine, orderbook_manager, active_tickers


async def async_main(args: argparse.Namespace) -> None:
    logger = logging.getLogger("main")
    setup_logging()
    validate_credentials()
    engine, orderbook_manager, active_tickers = await build_engine()
    logger.info("Starting paper trading pipeline with $%.2f bankroll", config.STARTING_BANKROLL)
    logger.info("Active tickers: %s", active_tickers)

    if args.report:
        print(generate_daily_report(config.DB_PATH, args.report))
        return

    if args.once:
        await engine.run_once()
        return

    tasks = [
        asyncio.create_task(orderbook_manager.run(active_tickers)),
        asyncio.create_task(engine.run_forever()),
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
    return parser.parse_args()


def main() -> None:
    asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    main()
