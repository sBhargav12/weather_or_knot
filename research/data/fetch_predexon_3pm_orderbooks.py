#!/usr/bin/env python3
"""Fetch Predexon KXHIGHNY orderbook snapshots around 3 PM ET.

This is a research collector for Strategy 1/3 testing. It intentionally stores
top-of-book fields only because the current Strategy 1/3 backtests need
executable best bid/ask/depth, not full ladder levels.

Requires PREDEXON_API_KEY in the environment.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKETS_CSV = ROOT / "data" / "kxhighny_markets.csv"
OUT = ROOT / "data" / "research" / "predexon_orderbooks_3pm.parquet"
PREDEXON_URL = "https://api.predexon.com/v2/kalshi/orderbooks"
ET = ZoneInfo("America/New_York")
START_DATE = "2026-01-07"


def et_window_ms(target_date: str, start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> tuple[int, int]:
    day = datetime.strptime(target_date, "%Y-%m-%d")
    start_et = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=ET)
    end_et = datetime(day.year, day.month, day.day, end_hour, end_minute, tzinfo=ET)
    return int(start_et.timestamp() * 1000), int(end_et.timestamp() * 1000)


def fetch_snapshots(api_key: str, ticker: str, start_ms: int, end_ms: int) -> list[dict]:
    headers = {"x-api-key": api_key}
    snapshots: list[dict] = []
    pagination_key: str | None = None
    seen_keys: set[str] = set()
    pages = 0

    while True:
        pages += 1
        if pages > 8:
            print(f"WARNING: stopping pagination after 8 pages for {ticker}", flush=True)
            break

        params: dict[str, object] = {
            "ticker": ticker,
            "start_time": start_ms,
            "end_time": end_ms,
            "limit": 200,
        }
        if pagination_key:
            params["pagination_key"] = pagination_key

        response = None
        for attempt in range(5):
            try:
                response = requests.get(PREDEXON_URL, params=params, headers=headers, timeout=30)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 4:
                    print(f"WARNING: failed {ticker}: {exc}", flush=True)
                    return snapshots
                time.sleep(1.0 * (attempt + 1))

        if response is None:
            return snapshots

        data = response.json()
        snapshots.extend(data.get("snapshots", []))
        pagination = data.get("pagination", {})
        if not pagination.get("has_more"):
            break

        pagination_key = pagination.get("pagination_key")
        if not pagination_key or pagination_key in seen_keys:
            print(f"WARNING: repeated/empty pagination key for {ticker}", flush=True)
            break
        seen_keys.add(pagination_key)
        time.sleep(0.15)

    return snapshots


def load_existing() -> tuple[pd.DataFrame, set[tuple[str, str]]]:
    if not OUT.exists():
        return pd.DataFrame(), set()

    existing = pd.read_parquet(OUT)
    if existing.empty:
        return existing, set()

    existing["target_date"] = existing["target_date"].astype(str)
    existing["ticker"] = existing["ticker"].astype(str)
    cached = set(zip(existing["ticker"], existing["target_date"]))
    return existing, cached


def main() -> None:
    api_key = os.environ.get("PREDEXON_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("PREDEXON_API_KEY is required")

    markets = pd.read_csv(MARKETS_CSV)
    markets["target_date"] = markets["target_date"].astype(str)
    ticker_dates = (
        markets[markets["target_date"] >= START_DATE][["ticker", "target_date"]]
        .drop_duplicates()
        .sort_values(["target_date", "ticker"])
        .reset_index(drop=True)
    )

    existing, cached = load_existing()
    rows = existing.to_dict("records") if not existing.empty else []
    fetched = 0
    skipped = 0
    empty = 0

    print(f"Fetching 3PM Predexon orderbooks for {len(ticker_dates)} ticker-dates", flush=True)
    for i, item in ticker_dates.iterrows():
        ticker = str(item["ticker"])
        target_date = str(item["target_date"])
        key = (ticker, target_date)
        if key in cached:
            skipped += 1
            continue

        # Strategy 1/3 only needs a point-in-time 3 PM book. A narrow final
        # minute avoids huge dense-orderbook pagination while still capturing
        # the visible market state around 3:05 PM ET.
        start_ms, end_ms = et_window_ms(target_date, 15, 4, 15, 5)
        snaps = fetch_snapshots(api_key, ticker, start_ms, end_ms)

        if snaps:
            for snap in snaps:
                rows.append(
                    {
                        "target_date": target_date,
                        "ticker": ticker,
                        "timestamp_ms": snap.get("timestamp"),
                        "best_bid": snap.get("best_bid"),
                        "best_ask": snap.get("best_ask"),
                        "bid_depth": snap.get("bid_depth"),
                        "ask_depth": snap.get("ask_depth"),
                        "sequence": snap.get("sequence", 0),
                    }
                )
        else:
            empty += 1
            rows.append(
                {
                    "target_date": target_date,
                    "ticker": ticker,
                    "timestamp_ms": np.nan,
                    "best_bid": np.nan,
                    "best_ask": np.nan,
                    "bid_depth": 0,
                    "ask_depth": 0,
                    "sequence": 0,
                }
            )

        fetched += 1
        if fetched % 25 == 0:
            print(f"  fetched={fetched} skipped={skipped} empty={empty} row={i + 1}/{len(ticker_dates)}", flush=True)
            pd.DataFrame(rows).to_parquet(OUT, index=False)
        time.sleep(0.2)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["target_date", "ticker", "timestamp_ms"], na_position="last").reset_index(drop=True)
        out.to_parquet(OUT, index=False)

    print(f"Saved {len(out):,} rows -> {OUT}", flush=True)
    if not out.empty:
        nonempty = out["timestamp_ms"].notna().sum()
        print(f"Non-empty snapshots: {nonempty:,}; empty ticker-date markers: {out['timestamp_ms'].isna().sum():,}", flush=True)


if __name__ == "__main__":
    main()
