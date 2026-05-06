"""Phase 1 collector for public Polymarket weather-trader research.

This script intentionally uses only public Polymarket endpoints:
- Data API leaderboard: top weather traders by volume.
- Data API trades: public trade history by proxy wallet.
- Gamma API markets: market metadata and coarse settlement status.

The Data API currently caps historical trade pagination around offset 3000.
The output records this cap explicitly so downstream research does not mistake
the fetched trade count for a complete lifetime count.
"""

from __future__ import annotations

import json
import re
import time
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests


DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
OUT_DIR = Path("data/research")
REPORT_DIR = Path("reports")
ET = ZoneInfo("America/New_York")

LEADERBOARD_PARAMS = {
    "category": "WEATHER",
    "timePeriod": "ALL",
    "orderBy": "VOL",
    "limit": 20,
    "offset": 0,
}

TRADE_LIMIT = 500
MAX_TRADE_OFFSET = 3000
REQUEST_SLEEP_SEC = 0.12
MARKET_METADATA_WORKERS = 8

WEATHER_RE = re.compile(
    r"("
    r"weather|temperature|highest temperature|lowest temperature|high temperature|low temperature|"
    r"rain|snow|precipitation|hurricane|tornado|storm|wind|heat|cold|"
    r"celsius|fahrenheit|°c|°f|temp"
    r")",
    re.IGNORECASE,
)


@dataclass
class FetchStats:
    wallet: str
    username: str
    raw_trades_fetched: int
    weather_trades_24m: int
    earliest_trade_et: str | None
    latest_trade_et: str | None
    reached_api_offset_cap: bool


def request_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    for attempt in range(4):
        response = session.get(url, params=params, timeout=30)
        if response.status_code == 429 and attempt < 3:
            time.sleep(2.0 + attempt)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"failed request after retries: {url}")


def fetch_leaderboard(session: requests.Session) -> pd.DataFrame:
    rows = request_json(session, f"{DATA_API}/v1/leaderboard", LEADERBOARD_PARAMS)
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("Polymarket weather leaderboard returned no rows")
    df["rank"] = df["rank"].astype(int)
    df["vol"] = pd.to_numeric(df["vol"], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    return df.sort_values("rank")


def is_weather_trade(trade: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(trade.get(key) or "")
        for key in ("title", "slug", "eventSlug", "outcome")
    )
    return bool(WEATHER_RE.search(haystack))


def fetch_wallet_trades(
    session: requests.Session,
    wallet: str,
    username: str,
    start_ts: int,
    end_ts: int,
) -> tuple[list[dict[str, Any]], FetchStats]:
    all_rows: list[dict[str, Any]] = []
    raw_count = 0
    reached_cap = False

    for offset in range(0, MAX_TRADE_OFFSET + 1, TRADE_LIMIT):
        params = {
            "user": wallet,
            "limit": TRADE_LIMIT,
            "offset": offset,
            "takerOnly": "false",
        }
        try:
            batch = request_json(session, f"{DATA_API}/trades", params)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 400 and offset > 0:
                reached_cap = True
                break
            raise

        if not isinstance(batch, list) or not batch:
            break

        raw_count += len(batch)
        for row in batch:
            ts = int(row.get("timestamp") or 0)
            if start_ts <= ts <= end_ts and is_weather_trade(row):
                row = dict(row)
                row["leaderboard_wallet"] = wallet
                row["leaderboard_username"] = username
                row["timestamp_et"] = datetime.fromtimestamp(ts, tz=ET).isoformat()
                row["notional_usd_proxy"] = float(row.get("size") or 0.0) * float(row.get("price") or 0.0)
                all_rows.append(row)

        if len(batch) < TRADE_LIMIT:
            break
        if offset >= MAX_TRADE_OFFSET:
            reached_cap = True
        time.sleep(REQUEST_SLEEP_SEC)

    timestamps = [int(r["timestamp"]) for r in all_rows if r.get("timestamp")]
    stats = FetchStats(
        wallet=wallet,
        username=username,
        raw_trades_fetched=raw_count,
        weather_trades_24m=len(all_rows),
        earliest_trade_et=datetime.fromtimestamp(min(timestamps), tz=ET).isoformat() if timestamps else None,
        latest_trade_et=datetime.fromtimestamp(max(timestamps), tz=ET).isoformat() if timestamps else None,
        reached_api_offset_cap=reached_cap,
    )
    return all_rows, stats


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def infer_resolution(market: dict[str, Any]) -> dict[str, Any]:
    outcomes = parse_json_list(market.get("outcomes"))
    prices = parse_json_list(market.get("outcomePrices"))
    numeric_prices = []
    for price in prices:
        try:
            numeric_prices.append(float(price))
        except (TypeError, ValueError):
            numeric_prices.append(None)

    resolved_outcome = None
    resolved_yes = None
    if market.get("closed") and outcomes and numeric_prices and any(p is not None for p in numeric_prices):
        best_idx = max(
            range(len(numeric_prices)),
            key=lambda idx: numeric_prices[idx] if numeric_prices[idx] is not None else -1,
        )
        best_price = numeric_prices[best_idx]
        if best_price is not None and best_price >= 0.95:
            resolved_outcome = outcomes[best_idx] if best_idx < len(outcomes) else None
            if isinstance(resolved_outcome, str):
                resolved_yes = resolved_outcome.strip().lower() == "yes"

    return {
        "market_id": market.get("id"),
        "conditionId": market.get("conditionId"),
        "question": market.get("question"),
        "slug": market.get("slug"),
        "endDate": market.get("endDate") or market.get("endDateIso"),
        "closed": bool(market.get("closed")),
        "active": bool(market.get("active")),
        "archived": bool(market.get("archived")),
        "outcomes": json.dumps(outcomes),
        "outcomePrices": json.dumps(numeric_prices),
        "resolved_outcome": resolved_outcome,
        "resolved_yes": resolved_yes,
        "volumeNum": market.get("volumeNum"),
        "liquidityNum": market.get("liquidityNum"),
        "lastTradePrice": market.get("lastTradePrice"),
    }


def fetch_one_market(condition_id: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "weather-or-knot-research/phase1 public-data collection",
            "Accept": "application/json",
        }
    )
    markets = request_json(session, f"{GAMMA_API}/markets", {"condition_ids": condition_id})
    if isinstance(markets, list) and markets:
        return infer_resolution(markets[0])
    return {"conditionId": condition_id, "fetch_missing": True}


def fetch_one_event(event_slug: str) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "weather-or-knot-research/phase1 public-data collection",
            "Accept": "application/json",
        }
    )
    events = request_json(session, f"{GAMMA_API}/events", {"slug": event_slug})
    if not isinstance(events, list) or not events:
        return [{"eventSlug": event_slug, "fetch_missing": True}]
    rows = []
    for market in events[0].get("markets") or []:
        row = infer_resolution(market)
        row["eventSlug"] = event_slug
        row["event_closed"] = bool(events[0].get("closed"))
        row["event_title"] = events[0].get("title")
        row["event_endDate"] = events[0].get("endDate")
        rows.append(row)
    return rows or [{"eventSlug": event_slug, "fetch_missing": True}]


def fetch_market_outcomes_from_events(trades_df: pd.DataFrame) -> pd.DataFrame:
    event_slugs = sorted(str(x) for x in trades_df["eventSlug"].dropna().unique())
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MARKET_METADATA_WORKERS) as executor:
        future_to_slug = {executor.submit(fetch_one_event, event_slug): event_slug for event_slug in event_slugs}
        for idx, future in enumerate(as_completed(future_to_slug), start=1):
            event_slug = future_to_slug[future]
            try:
                rows.extend(future.result())
            except Exception as exc:
                rows.append({"eventSlug": event_slug, "fetch_error": str(exc)})
            if idx % 100 == 0 or idx == len(event_slugs):
                print(f"  fetched event metadata {idx}/{len(event_slugs)}", flush=True)

    outcomes = pd.DataFrame(rows)
    wanted = set(str(x) for x in trades_df["conditionId"].dropna().unique())
    if "conditionId" in outcomes.columns:
        outcomes = outcomes[outcomes["conditionId"].astype(str).isin(wanted) | outcomes["conditionId"].isna()]
    return outcomes.drop_duplicates(subset=["conditionId"], keep="first")


def fetch_market_outcomes(session: requests.Session, condition_ids: list[str]) -> pd.DataFrame:
    del session  # metadata fetch is parallelized with per-thread sessions
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MARKET_METADATA_WORKERS) as executor:
        future_to_id = {executor.submit(fetch_one_market, condition_id): condition_id for condition_id in condition_ids}
        for idx, future in enumerate(as_completed(future_to_id), start=1):
            condition_id = future_to_id[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({"conditionId": condition_id, "fetch_error": str(exc)})
            if idx % 250 == 0 or idx == len(condition_ids):
                print(f"  fetched market metadata {idx}/{len(condition_ids)}", flush=True)
    return pd.DataFrame(rows)


def write_report(
    leaderboard: pd.DataFrame,
    trades: pd.DataFrame,
    outcomes: pd.DataFrame,
    stats: list[FetchStats],
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    stats_df = pd.DataFrame([asdict(s) for s in stats])
    merged = leaderboard.merge(
        stats_df,
        left_on="proxyWallet",
        right_on="wallet",
        how="left",
    )

    table_df = merged[
        [
            "rank",
            "userName",
            "proxyWallet",
            "vol",
            "pnl",
            "weather_trades_24m",
            "raw_trades_fetched",
            "reached_api_offset_cap",
        ]
    ]
    table_header = "| " + " | ".join(table_df.columns) + " |"
    table_sep = "| " + " | ".join(["---"] * len(table_df.columns)) + " |"
    table_rows = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in table_df.itertuples(index=False, name=None)
    ]

    lines = [
        "# Polymarket Weather Trader Phase 1 Collection",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        f"Window: {start_dt.isoformat()} to {end_dt.isoformat()}",
        "",
        "## APIs Used",
        "",
        f"- Leaderboard: `{DATA_API}/v1/leaderboard` with `{LEADERBOARD_PARAMS}`",
        f"- Trades: `{DATA_API}/trades` with `user`, `limit={TRADE_LIMIT}`, `offset`, `takerOnly=false`",
        f"- Market metadata: `{GAMMA_API}/markets?condition_ids=<conditionId>`",
        "",
        "## Important Limitations",
        "",
        "- The leaderboard supports `DAY`, `WEEK`, `MONTH`, and `ALL`, but not an exact 24-month ranking window. Phase 1 seeds from all-time weather volume, then filters fetched trades to the last 24 months.",
        f"- The public Data API currently caps historical trade pagination around offset {MAX_TRADE_OFFSET}; wallets marked `reached_api_offset_cap=True` may have additional older trades not collected here.",
        "- Settlement inference uses Gamma `closed` plus near-1.0 `outcomePrices`; unresolved/open markets remain null.",
        "",
        "## Top 20 Weather Traders by Polymarket Leaderboard Volume",
        "",
        "\n".join([table_header, table_sep, *table_rows]),
        "",
        "## Output Files",
        "",
        "- `data/research/polymarket_top_weather_traders.csv`",
        "- `data/research/polymarket_trades_raw.parquet`",
        "- `data/research/polymarket_market_outcomes.parquet`",
        "- `data/research/polymarket_phase1_summary.json`",
    ]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "polymarket_weather_trader_phase1.md").write_text("\n".join(lines) + "\n")


def load_cache_and_report() -> None:
    leaderboard = pd.read_csv(OUT_DIR / "polymarket_top_weather_traders.csv")
    trades_df = pd.read_parquet(OUT_DIR / "polymarket_trades_raw.parquet")
    outcomes_df = pd.read_parquet(OUT_DIR / "polymarket_market_outcomes.parquet")
    summary = json.loads((OUT_DIR / "polymarket_phase1_summary.json").read_text())
    stats = [FetchStats(**row) for row in summary["wallet_fetch_stats"]]
    start_et = datetime.fromisoformat(summary["window_start_et"])
    end_et = datetime.fromisoformat(summary["window_end_et"])
    write_report(leaderboard, trades_df, outcomes_df, stats, start_et, end_et)
    print_display_table(leaderboard, stats)
    print_saved_paths(trades_df, outcomes_df)


def refresh_outcomes_from_cache() -> None:
    trades_df = pd.read_parquet(OUT_DIR / "polymarket_trades_raw.parquet")
    print(
        f"Refreshing outcomes from {trades_df['eventSlug'].nunique()} unique Gamma event slugs...",
        flush=True,
    )
    outcomes_df = fetch_market_outcomes_from_events(trades_df)

    missing_ids = sorted(
        set(str(x) for x in trades_df["conditionId"].dropna().unique())
        - set(str(x) for x in outcomes_df.get("conditionId", pd.Series(dtype=str)).dropna().unique())
    )
    if missing_ids:
        print(f"  falling back to condition_ids for {len(missing_ids)} unresolved metadata rows", flush=True)
        fallback_df = fetch_market_outcomes(requests.Session(), missing_ids)
        outcomes_df = pd.concat([outcomes_df, fallback_df], ignore_index=True).drop_duplicates(
            subset=["conditionId"], keep="first"
        )

    outcomes_df.to_parquet(OUT_DIR / "polymarket_market_outcomes.parquet", index=False)

    summary_path = OUT_DIR / "polymarket_phase1_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["unique_weather_markets"] = int(trades_df["conditionId"].nunique())
    summary["market_outcome_rows"] = int(len(outcomes_df))
    summary["closed_markets_with_inferred_resolution"] = int(outcomes_df["resolved_outcome"].notna().sum())
    summary["gamma_event_slug_outcome_refresh"] = True
    summary["gamma_event_slugs"] = int(trades_df["eventSlug"].nunique())
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    load_cache_and_report()


def print_display_table(leaderboard: pd.DataFrame, stats: list[FetchStats]) -> None:
    stats_df = pd.DataFrame([asdict(s) for s in stats])
    display = leaderboard.merge(stats_df, left_on="proxyWallet", right_on="wallet", how="left")
    display = display.rename(
        columns={
            "rank": "Rank",
            "proxyWallet": "Wallet",
            "vol": "TotalVolumeUSD",
            "weather_trades_24m": "TradeCount",
        }
    )
    print("\n=== TOP-20 POLYMARKET WEATHER TRADERS BY LEADERBOARD VOLUME ===")
    print(
        display[["Rank", "userName", "Wallet", "TotalVolumeUSD", "TradeCount", "reached_api_offset_cap"]]
        .to_string(index=False, formatters={"TotalVolumeUSD": "{:,.2f}".format})
    )


def print_saved_paths(trades_df: pd.DataFrame, outcomes_df: pd.DataFrame) -> None:
    print("\nSaved:")
    print(f"  {OUT_DIR / 'polymarket_top_weather_traders.csv'}")
    print(f"  {OUT_DIR / 'polymarket_trades_raw.parquet'} ({len(trades_df):,} rows)")
    print(f"  {OUT_DIR / 'polymarket_market_outcomes.parquet'} ({len(outcomes_df):,} rows)")
    print(f"  {OUT_DIR / 'polymarket_phase1_summary.json'}")
    print(f"  {REPORT_DIR / 'polymarket_weather_trader_phase1.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Regenerate the markdown report and console table from existing Phase 1 artifacts.",
    )
    parser.add_argument(
        "--refresh-outcomes-from-cache",
        action="store_true",
        help="Rebuild market outcome metadata from cached raw trades using Gamma event slugs.",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.from_cache:
        load_cache_and_report()
        return
    if args.refresh_outcomes_from_cache:
        refresh_outcomes_from_cache()
        return

    now_et = datetime.now(tz=ET)
    start_et = now_et - timedelta(days=730)
    start_ts = int(start_et.timestamp())
    end_ts = int(now_et.timestamp())

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "weather-or-knot-research/phase1 public-data collection",
            "Accept": "application/json",
        }
    )

    print("Fetching top-20 Polymarket weather leaderboard by all-time volume...", flush=True)
    leaderboard = fetch_leaderboard(session)
    leaderboard.to_csv(OUT_DIR / "polymarket_top_weather_traders.csv", index=False)

    all_trades: list[dict[str, Any]] = []
    stats: list[FetchStats] = []
    for row in leaderboard.itertuples(index=False):
        wallet = getattr(row, "proxyWallet")
        username = getattr(row, "userName")
        rank = getattr(row, "rank")
        print(f"Fetching trades for rank {rank}: {username} ({wallet})", flush=True)
        trades, wallet_stats = fetch_wallet_trades(session, wallet, username, start_ts, end_ts)
        all_trades.extend(trades)
        stats.append(wallet_stats)
        print(
            f"  raw={wallet_stats.raw_trades_fetched}, weather_24m={wallet_stats.weather_trades_24m}, "
            f"cap={wallet_stats.reached_api_offset_cap}",
            flush=True,
        )

    trades_df = pd.DataFrame(all_trades)
    if trades_df.empty:
        raise RuntimeError("No weather trades collected")
    trades_df = trades_df.drop_duplicates(
        subset=["proxyWallet", "transactionHash", "asset", "timestamp", "side", "price", "size"],
        keep="first",
    )
    trades_df.to_parquet(OUT_DIR / "polymarket_trades_raw.parquet", index=False)

    condition_ids = sorted(str(x) for x in trades_df["conditionId"].dropna().unique())
    print(
        f"Fetching Gamma event metadata/outcomes for {trades_df['eventSlug'].nunique()} unique events...",
        flush=True,
    )
    outcomes_df = fetch_market_outcomes_from_events(trades_df)
    missing_ids = sorted(
        set(condition_ids)
        - set(str(x) for x in outcomes_df.get("conditionId", pd.Series(dtype=str)).dropna().unique())
    )
    if missing_ids:
        print(f"  falling back to condition_ids for {len(missing_ids)} unresolved metadata rows", flush=True)
        fallback_df = fetch_market_outcomes(session, missing_ids)
        outcomes_df = pd.concat([outcomes_df, fallback_df], ignore_index=True).drop_duplicates(
            subset=["conditionId"], keep="first"
        )
    outcomes_df.to_parquet(OUT_DIR / "polymarket_market_outcomes.parquet", index=False)

    stats_df = pd.DataFrame([asdict(s) for s in stats])
    summary = {
        "generated_at_et": now_et.isoformat(),
        "window_start_et": start_et.isoformat(),
        "window_end_et": now_et.isoformat(),
        "leaderboard_endpoint": f"{DATA_API}/v1/leaderboard",
        "leaderboard_params": LEADERBOARD_PARAMS,
        "trades_endpoint": f"{DATA_API}/trades",
        "gamma_market_endpoint": f"{GAMMA_API}/markets?condition_ids=<conditionId>",
        "trade_pagination_limit": TRADE_LIMIT,
        "max_trade_offset_attempted": MAX_TRADE_OFFSET,
        "top_wallets": len(leaderboard),
        "raw_weather_trade_rows_saved": int(len(trades_df)),
        "unique_weather_markets": int(len(condition_ids)),
        "closed_markets_with_inferred_resolution": int(outcomes_df["resolved_outcome"].notna().sum()),
        "wallet_fetch_stats": [asdict(s) for s in stats],
    }
    (OUT_DIR / "polymarket_phase1_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_report(leaderboard, trades_df, outcomes_df, stats, start_et, now_et)

    print_display_table(leaderboard, stats)
    print_saved_paths(trades_df, outcomes_df)


if __name__ == "__main__":
    main()
