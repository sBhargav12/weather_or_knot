"""
Download TrevorJS/kalshi-trades HuggingFace dataset.
Filters to weather series (KXHIGH* and KXLOWT*) and saves parquet.

Usage:
    uv run python research/data/fetch_hf_kalshi_trades.py
"""

import json
import os
import sys
from pathlib import Path

import httpx
import pandas as pd

BASE_URL = "https://huggingface.co/datasets/TrevorJS/kalshi-trades/resolve/main"
OUT_DIR = Path("data/hf_kalshi_trades")
WEATHER_OUTPUT = OUT_DIR / "weather_trades.parquet"
MARKETS_OUTPUT = OUT_DIR / "markets.parquet"
DONE_SHARDS_FILE = OUT_DIR / "done_shards.json"

NUM_TRADE_SHARDS = 16   # trades-0000.parquet … trades-0015.parquet
NUM_MARKET_SHARDS = 4   # markets-0000.parquet … markets-0003.parquet
WEATHER_PREFIXES = ("KXHIGH", "KXLOWT")

TIMEOUT = httpx.Timeout(300.0, connect=30.0)


def load_done_shards() -> set:
    if DONE_SHARDS_FILE.exists():
        return set(json.loads(DONE_SHARDS_FILE.read_text()))
    return set()


def save_done_shards(done: set) -> None:
    DONE_SHARDS_FILE.write_text(json.dumps(sorted(done)))


def filter_weather(df: pd.DataFrame) -> pd.DataFrame:
    mask = df["ticker"].str.startswith(WEATHER_PREFIXES)
    return df[mask].copy()


def download_shard(client: httpx.Client, shard_idx: int, tmp_path: Path) -> pd.DataFrame:
    url = f"{BASE_URL}/trades-{shard_idx:04d}.parquet"
    print(f"  Downloading shard {shard_idx:02d}: {url}")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    df = pd.read_parquet(tmp_path)
    return df


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done_shards = load_done_shards()

    # Accumulate all weather rows across shards
    all_weather: list[pd.DataFrame] = []

    # Load existing output if partial run
    if WEATHER_OUTPUT.exists() and done_shards:
        print(f"Resuming — loading existing {WEATHER_OUTPUT} ({len(done_shards)} shards done)")
        all_weather.append(pd.read_parquet(WEATHER_OUTPUT))

    running_total = sum(len(df) for df in all_weather)
    tmp_path = OUT_DIR / "_shard_tmp.parquet"

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for shard_idx in range(NUM_TRADE_SHARDS):
            if shard_idx in done_shards:
                print(f"  Shard {shard_idx:02d}: already done, skipping")
                continue

            try:
                df = download_shard(client, shard_idx, tmp_path)
                shard_rows = len(df)
                weather_df = filter_weather(df)
                kept = len(weather_df)
                running_total += kept
                print(
                    f"  Shard {shard_idx:02d}: {shard_rows:,} rows total → "
                    f"{kept:,} weather kept | running total: {running_total:,}"
                )
                if kept > 0:
                    all_weather.append(weather_df)
                done_shards.add(shard_idx)

                # Save incrementally after each shard
                if all_weather:
                    combined = pd.concat(all_weather, ignore_index=True)
                    combined.to_parquet(WEATHER_OUTPUT, compression="snappy", index=False)
                    all_weather = [combined]  # replace list with single df to avoid memory bloat

                save_done_shards(done_shards)
                # Clean up tmp
                if tmp_path.exists():
                    tmp_path.unlink()

            except Exception as e:
                print(f"  ERROR on shard {shard_idx:02d}: {e}", file=sys.stderr)
                if tmp_path.exists():
                    tmp_path.unlink()
                continue

        # Download markets parquet (4 shards: markets-0000..markets-0003)
        print("\nDownloading markets parquet (4 shards)...")
        market_frames = []
        for midx in range(NUM_MARKET_SHARDS):
            murl = f"{BASE_URL}/markets-{midx:04d}.parquet"
            mtmp = OUT_DIR / f"_markets_tmp_{midx}.parquet"
            try:
                with client.stream("GET", murl) as r:
                    r.raise_for_status()
                    with open(mtmp, "wb") as f:
                        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
                mdf = pd.read_parquet(mtmp)
                market_frames.append(mdf)
                mtmp.unlink()
                print(f"  Markets shard {midx}: {len(mdf):,} rows")
            except Exception as e:
                print(f"  ERROR downloading markets shard {midx}: {e}", file=sys.stderr)
        if market_frames:
            pd.concat(market_frames, ignore_index=True).to_parquet(MARKETS_OUTPUT, compression="snappy", index=False)
            print(f"  Markets saved to {MARKETS_OUTPUT}")

    # Final summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if WEATHER_OUTPUT.exists():
        final_df = pd.read_parquet(WEATHER_OUTPUT)
        total_rows = len(final_df)
        unique_tickers = sorted(final_df["ticker"].unique())
        file_size_mb = WEATHER_OUTPUT.stat().st_size / 1024 / 1024

        print(f"Total weather rows:   {total_rows:,}")
        print(f"Unique tickers:       {len(unique_tickers)}")
        print(f"File size:            {file_size_mb:.1f} MB")
        print(f"Output:               {WEATHER_OUTPUT}")

        if "created_time" in final_df.columns:
            ts = pd.to_datetime(final_df["created_time"], errors="coerce")
            print(f"Date range:           {ts.min()} → {ts.max()}")

        print(f"\nTickers found ({len(unique_tickers)}):")
        for t in unique_tickers:
            n = (final_df["ticker"] == t).sum()
            print(f"  {t}: {n:,} trades")
    else:
        print("No weather trades file found — all shards may have failed.")

    if MARKETS_OUTPUT.exists():
        mkt_size_mb = MARKETS_OUTPUT.stat().st_size / 1024 / 1024
        print(f"\nMarkets file:         {MARKETS_OUTPUT} ({mkt_size_mb:.1f} MB)")
        mkt_df = pd.read_parquet(MARKETS_OUTPUT)
        print(f"Markets rows:         {len(mkt_df):,}")
        # Show weather markets
        weather_mkts = mkt_df[mkt_df["ticker"].str.startswith(WEATHER_PREFIXES, na=False)]
        print(f"Weather markets:      {len(weather_mkts):,}")

    print(f"\nDone shards:          {sorted(done_shards)}")


if __name__ == "__main__":
    main()
