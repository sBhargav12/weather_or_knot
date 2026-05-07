"""
Download Kalshi orderbook history for all weather series from Predexon API.
Writes one Parquet file per series to data/predexon_orderbooks/.

Pure synchronous — no asyncio, no concurrency, no rate-limiter complexity.
One request every 1/rps seconds via time.sleep().

Rate limits:
  Free $0:    0.9 rps  → all weather ~2-3 hrs
  Dev  $49:  20   rps  → ~6-8 min
  Pro  $249: 100  rps  → ~2 min

Usage:
    uv run python research/data/predexon_orderbook_download.py
    uv run python research/data/predexon_orderbook_download.py --series KXHIGHNY
    uv run python research/data/predexon_orderbook_download.py --rps 20 --resume
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY = "C8aUAEMoUg1SgKhRCBhbs8vkvLGKVwar0GUNtN60"
BASE_URL = "https://api.predexon.com"
DATA_START_MS = int(datetime(2026, 1, 7, tzinfo=timezone.utc).timestamp() * 1000)

WEATHER_SERIES = [
    "KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHAUS", "KXHIGHLAX",
    "KXHIGHDEN", "KXHIGHPHIL", "KXLOWTNYC", "KXLOWTCHI", "KXLOWTDEN",
    "KXLOWTMIA", "KXLOWTAUS", "KXLOWTLAX", "KXLOWTPHIL",
]

OUT_DIR      = Path("data/predexon_orderbooks")
PAGE_LIMIT   = 200
RETRY_MAX    = 6
RATE_LIMIT_RPS = 0.9
CHECKPOINT   = 5
HEADERS      = {"x-api-key": API_KEY}


# ── HTTP ──────────────────────────────────────────────────────────────────────

_interval   = 1.0 / RATE_LIMIT_RPS
_next_call  = 0.0   # monotonic time of next allowed request


_client: httpx.Client | None = None


def _get(url: str) -> dict:
    """Synchronous GET with rate limiting and exponential backoff on 429."""
    global _next_call, _client
    wait = _next_call - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _next_call = time.monotonic() + _interval

    for attempt in range(RETRY_MAX):
        try:
            r = _client.get(url, timeout=30)
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                backoff = float(ra) + 1 if ra else 3.0 * (2 ** attempt)
                print(f"  429 backoff {backoff:.0f}s (attempt {attempt+1}/{RETRY_MAX})",
                      flush=True)
                time.sleep(backoff)
                _next_call = time.monotonic() + _interval
                continue
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  {type(e).__name__} attempt {attempt+1}: {e}", flush=True)
            if attempt < RETRY_MAX - 1:
                time.sleep(3.0 * (2 ** attempt))
            else:
                raise
    raise RuntimeError(f"Max retries: {url}")


# ── Market enumeration ────────────────────────────────────────────────────────

def _parse_ms(ts: str | None, default: int) -> int:
    if not ts:
        return default
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return default


def get_markets(series: str) -> list[tuple[str, int, int]]:
    """Return (ticker, start_ms, end_ms) for markets with data (post Jan 7 2026)."""
    results, skipped = [], 0
    pag_key = None
    while True:
        url = f"{BASE_URL}/v2/kalshi/markets?series_ticker={series}&limit=100"
        if pag_key:
            url += f"&pagination_key={pag_key}"
        data = _get(url)
        for m in data.get("markets", []):
            close_ms = _parse_ms(m.get("close_time"), 0)
            if close_ms and close_ms < DATA_START_MS:
                skipped += 1
                continue
            start_ms = max(_parse_ms(m.get("open_time"), DATA_START_MS), DATA_START_MS)
            end_ms   = (close_ms + 86_400_000) if close_ms else (DATA_START_MS + 365 * 86_400_000)
            results.append((m["ticker"], start_ms, end_ms))
        pag = data.get("pagination", {})
        if not pag.get("has_more"):
            break
        pag_key = pag["pagination_key"]
    return results, skipped


# ── Orderbook fetch ───────────────────────────────────────────────────────────

def get_orderbook(ticker: str, start_ms: int, end_ms: int) -> list[dict]:
    snapshots, pag_key = [], None
    while True:
        url = (f"{BASE_URL}/v2/kalshi/orderbooks"
               f"?ticker={ticker}&start_time={start_ms}&end_time={end_ms}&limit={PAGE_LIMIT}")
        if pag_key:
            url += f"&pagination_key={pag_key}"
        data = _get(url)
        snapshots.extend(data.get("snapshots", []))
        if not data.get("pagination", {}).get("has_more"):
            break
        pag_key = data["pagination"]["pagination_key"]
    return snapshots


# ── Parquet helpers ───────────────────────────────────────────────────────────

def to_df(snapshots: list[dict]) -> pd.DataFrame:
    if not snapshots:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "ticker":        s["ticker"],
        "timestamp_ms":  s["timestamp"],
        "best_bid":      s["best_bid"],
        "best_ask":      s["best_ask"],
        "bid_depth":     s["bid_depth"],
        "ask_depth":     s["ask_depth"],
        "sequence":      s["sequence"],
        "yes_bids_json": json.dumps(s.get("yes_bids", [])),
        "yes_asks_json": json.dumps(s.get("yes_asks", [])),
    } for s in snapshots])
    df["ts_utc"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    return df


def save(out_path, done_path, new_snaps, existing_df, done_tickers):
    new_df = to_df(new_snaps)
    if not existing_df.empty and not new_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    elif not new_df.empty:
        combined = new_df
    else:
        combined = existing_df
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["ticker", "timestamp_ms", "sequence"])
        combined = combined.sort_values(["ticker", "timestamp_ms"]).reset_index(drop=True)
        combined.to_parquet(out_path, index=False, compression="snappy")
    done_path.write_text(json.dumps(sorted(done_tickers)))


# ── Per-series download ───────────────────────────────────────────────────────

def download_series(series: str, resume: bool) -> dict:
    out_path  = OUT_DIR / f"{series.lower()}_orderbooks.parquet"
    done_path = OUT_DIR / f"{series.lower()}_done_tickers.json"
    t0 = time.time()

    done_tickers: set[str] = set()
    existing_df = pd.DataFrame()
    if resume and out_path.exists() and done_path.exists():
        done_tickers = set(json.loads(done_path.read_text()))
        existing_df = pd.read_parquet(out_path)
        print(f"[{series}] resuming — {len(done_tickers)} already done", flush=True)

    print(f"[{series}] enumerating markets...", flush=True)
    markets, skipped = get_markets(series)
    eligible = [(t, s, e) for t, s, e in markets if t not in done_tickers]
    print(f"[{series}] {len(markets)} eligible, {skipped} pre-Jan-7 skipped, "
          f"{len(eligible)} to fetch", flush=True)

    if not eligible:
        print(f"[{series}] nothing to do", flush=True)
        return {"series": series, "markets": len(markets), "skipped": skipped,
                "snapshots": len(existing_df), "size_mb": 0, "errors": 0}

    all_snaps: list[dict] = []
    errors = 0
    checkpoint = CHECKPOINT

    for idx, (ticker, start_ms, end_ms) in enumerate(eligible, 1):
        print(f"[{series}] {idx}/{len(eligible)} fetching {ticker}", flush=True)
        try:
            snaps = get_orderbook(ticker, start_ms, end_ms)
            all_snaps.extend(snaps)
            done_tickers.add(ticker)
            print(f"[{series}] {idx}/{len(eligible)} got {len(snaps)} snaps", flush=True)
        except Exception as e:
            print(f"[{series}] ERROR {ticker}: {e}", flush=True)
            errors += 1

        if idx % checkpoint == 0 or idx == len(eligible):
            elapsed = time.time() - t0
            rate = idx / elapsed
            eta_min = (len(eligible) - idx) / rate / 60
            print(f"[{series}] {idx}/{len(eligible)}  {len(all_snaps):,} snaps  "
                  f"{rate:.2f} mkts/s  ETA {eta_min:.0f}m", flush=True)
            save(out_path, done_path, all_snaps, existing_df, done_tickers)

    elapsed = time.time() - t0
    size_mb = out_path.stat().st_size / 1e6 if out_path.exists() else 0
    print(f"[{series}] DONE — {len(all_snaps):,} snaps  {size_mb:.1f} MB  {elapsed:.0f}s",
          flush=True)
    return {"series": series, "markets": len(markets), "skipped": skipped,
            "new_snapshots": len(all_snaps), "size_mb": size_mb,
            "errors": errors, "elapsed_s": elapsed}


# ── Main ──────────────────────────────────────────────────────────────────────

def main(series_list: list[str], rps: float, resume: bool):
    global _interval, _next_call, _client
    _interval  = 1.0 / rps
    _next_call = 0.0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _client = httpx.Client(headers=HEADERS, timeout=30)

    print(f"Predexon weather orderbook download", flush=True)
    print(f"  series={len(series_list)}  rps={rps}  resume={resume}", flush=True)
    print(f"  skipping markets closed before Jan 7 2026", flush=True)

    t_start = time.time()
    summaries = []
    for series in series_list:
        summaries.append(download_series(series, resume))

    total_elapsed = time.time() - t_start
    print("\n=== SUMMARY ===", flush=True)
    total_snaps = total_mb = 0
    for s in summaries:
        n  = s.get("new_snapshots", 0)
        mb = s.get("size_mb", 0.0)
        total_snaps += n; total_mb += mb
        print(f"  {s['series']:15s}  mkts={s['markets']:4d}  skip={s['skipped']:4d}"
              f"  snaps={n:>8,}  {mb:5.1f} MB", flush=True)
    print(f"\nTotal: {total_snaps:,} snapshots  {total_mb:.1f} MB  "
          f"in {total_elapsed/60:.1f} min", flush=True)
    print(f"Output: {OUT_DIR.resolve()}/", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(epilog="""
Plans: Free $0=0.9rps  Dev $49=20rps  Pro $249=100rps
Use --resume to safely continue an interrupted run.""")
    parser.add_argument("--series", nargs="+", default=WEATHER_SERIES)
    parser.add_argument("--rps", type=float, default=RATE_LIMIT_RPS,
                        help=f"Requests/sec (default {RATE_LIMIT_RPS})")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    main(args.series, args.rps, args.resume)
