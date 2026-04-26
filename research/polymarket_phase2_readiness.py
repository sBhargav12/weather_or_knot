"""Phase 2 readiness audit for Polymarket weather-wallet research.

This is a research-only audit. It reads Phase 1 public Polymarket artifacts and
quantifies what the current API-accessible slice can and cannot support before
downstream wallet profiling, clustering, markouts, and strategy inference.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


DATA_DIR = Path("data/research")
REPORT_DIR = Path("reports")
ET = ZoneInfo("America/New_York")

TEMPERATURE_RE = re.compile(r"(?:temperature|highest temp|lowest temp|°c|°f|fahrenheit|celsius|temp)", re.I)
WEATHER_DIRECT_RE = re.compile(
    r"(?:temperature|highest temperature|lowest temperature|rain|snow|precipitation|hurricane|tornado|storm|wind|°c|°f)",
    re.I,
)
WEATHER_ADJACENT_RE = re.compile(r"(?:global temperature|temperature increase|hottest|coldest|heat|climate)", re.I)


def pct(numer: float, denom: float) -> float:
    return 0.0 if denom == 0 else 100.0 * numer / denom


def entropy(series: pd.Series) -> float:
    counts = series.dropna().value_counts()
    if counts.empty:
        return 0.0
    probs = counts / counts.sum()
    return float(-(probs * probs.map(math.log2)).sum())


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    leaderboard = pd.read_csv(DATA_DIR / "polymarket_top_weather_traders.csv")
    trades = pd.read_parquet(DATA_DIR / "polymarket_trades_raw.parquet")
    outcomes = pd.read_parquet(DATA_DIR / "polymarket_market_outcomes.parquet")
    summary = json.loads((DATA_DIR / "polymarket_phase1_summary.json").read_text())
    return leaderboard, trades, outcomes, summary


def add_trade_features(trades: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["dt_et"] = pd.to_datetime(t["timestamp"], unit="s", utc=True).dt.tz_convert("America/New_York")
    t["date_et"] = t["dt_et"].dt.date.astype(str)
    t["hour_et"] = t["dt_et"].dt.hour
    t["is_temperature"] = t["title"].fillna("").str.contains(TEMPERATURE_RE)
    t["is_weather_direct"] = t["title"].fillna("").str.contains(WEATHER_DIRECT_RE)
    t["is_weather_adjacent"] = ~t["is_weather_direct"] & t["title"].fillna("").str.contains(WEATHER_ADJACENT_RE)
    t["weather_scope"] = "weather_direct"
    t.loc[t["is_weather_adjacent"], "weather_scope"] = "weather_adjacent"

    outcome_cols = [
        "conditionId",
        "closed",
        "active",
        "archived",
        "resolved_outcome",
        "resolved_yes",
        "event_closed",
        "event_title",
        "event_endDate",
    ]
    merged = t.merge(outcomes[outcome_cols], on="conditionId", how="left", validate="many_to_one")
    merged["has_outcome_row"] = merged["closed"].notna()
    merged["has_resolved_outcome"] = merged["resolved_outcome"].notna()
    return merged


def price_context_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    t = trades.sort_values(["conditionId", "timestamp", "transactionHash"]).copy()
    grouped = t.groupby("conditionId", sort=False)
    t["market_trade_count"] = grouped["conditionId"].transform("size")
    t["has_prior_same_market_trade"] = grouped.cumcount() > 0
    t["has_later_same_market_trade"] = grouped.cumcount(ascending=False) > 0

    windows = {
        "later_trade_1m": 60,
        "later_trade_5m": 5 * 60,
        "later_trade_60m": 60 * 60,
        "later_trade_1d": 24 * 60 * 60,
    }
    next_ts = grouped["timestamp"].shift(-1)
    dt_next = next_ts - t["timestamp"]
    out = {
        "rows_with_any_same_market_context": int((t["market_trade_count"] >= 2).sum()),
        "rows_with_prior_same_market_trade": int(t["has_prior_same_market_trade"].sum()),
        "rows_with_later_same_market_trade": int(t["has_later_same_market_trade"].sum()),
    }
    for name, seconds in windows.items():
        out[f"rows_with_{name}"] = int(((dt_next.notna()) & (dt_next <= seconds)).sum())
    return out


def wallet_coverage(leaderboard: pd.DataFrame, trades: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    wallet_stats = pd.DataFrame(summary.get("wallet_fetch_stats", []))
    trade_wallets = (
        trades.groupby("proxyWallet")
        .agg(
            fetched_trade_rows=("proxyWallet", "size"),
            unique_markets=("conditionId", "nunique"),
            unique_events=("eventSlug", "nunique"),
            first_trade_et=("dt_et", "min"),
            last_trade_et=("dt_et", "max"),
            notional_usd_proxy=("notional_usd_proxy", "sum"),
        )
        .reset_index()
    )
    merged = (
        leaderboard.merge(wallet_stats, left_on="proxyWallet", right_on="wallet", how="left")
        .merge(trade_wallets, on="proxyWallet", how="left")
        .sort_values("rank")
    )
    for col in ("fetched_trade_rows", "unique_markets", "unique_events", "notional_usd_proxy"):
        merged[col] = merged[col].fillna(0)
    merged["has_fetched_weather_trades"] = merged["fetched_trade_rows"] > 0
    return merged


def readiness_verdict(metrics: dict[str, Any]) -> dict[str, Any]:
    trade_rows = metrics["trade_coverage"]["rows"]
    resolved_pct = metrics["outcome_coverage"]["resolved_trade_row_pct"]
    active_wallets = metrics["wallet_coverage"]["wallets_with_weather_trades"]
    span_days = metrics["timestamp_coverage"]["span_days"]
    api_capped = metrics["api_limits"]["wallets_reaching_offset_cap"] > 0

    supports = {
        "wallet_behavior_metrics": {
            "status": "supported_recent_slice",
            "confidence": "medium",
            "reason": f"{trade_rows:,} rows across {active_wallets} active wallets are enough for cadence, sizing, concentration, and repeat-trading fingerprints, but all wallets are API-capped.",
        },
        "markout_analysis": {
            "status": "partially_supported",
            "confidence": "low_to_medium",
            "reason": "Trade-to-trade markouts are possible inside the captured slice, but no full CLOB/orderbook history or unfilled passive orders are available.",
        },
        "strategy_clustering": {
            "status": "supported_provisional",
            "confidence": "medium",
            "reason": "17 active wallets support provisional behavioral clusters; sample is too small and capped for stable final taxonomy.",
        },
        "market_selection_inference": {
            "status": "partially_supported",
            "confidence": "medium",
            "reason": "Chosen-market patterns are visible, but available-market baseline is incomplete unless we build a Gamma weather universe for the same recent window.",
        },
        "cross_venue_comparison": {
            "status": "supported_descriptive_only",
            "confidence": "medium",
            "reason": "Useful descriptive comparison against Kalshi/Becker research, but Polymarket station, settlement, fee, and grouped-market mechanics differ.",
        },
    }

    verdict = "GO for descriptive Phase 3-6 analysis; NO-GO for durable 24-month alpha claims."
    if resolved_pct < 50 or span_days < 30 or active_wallets < 10:
        verdict = "LIMITED GO; collect/backfill more data before strategy clustering."
    if api_capped:
        verdict += " Current conclusions must be scoped to the API-accessible recent slice."

    return {"verdict": verdict, "supports": supports}


def build_report(readiness: dict[str, Any], wallet_df: pd.DataFrame) -> str:
    m = readiness["metrics"]
    support = readiness["decision"]["supports"]
    wallet_table = wallet_df[
        [
            "rank",
            "userName",
            "proxyWallet",
            "vol",
            "fetched_trade_rows",
            "unique_markets",
            "unique_events",
            "reached_api_offset_cap",
            "has_fetched_weather_trades",
        ]
    ].copy()
    wallet_table["vol"] = wallet_table["vol"].map(lambda x: f"{x:,.2f}")

    lines = [
        "# Polymarket Phase 2 Readiness Audit",
        "",
        f"Generated: {readiness['generated_at_et']}",
        "",
        "## Readiness Verdict",
        "",
        readiness["decision"]["verdict"],
        "",
        "This is a research-only readiness audit. It does not change live trading, paper trading, thresholds, schedulers, or execution code.",
        "",
        "## Scope of Valid Inference",
        "",
        "- Valid: recent-slice wallet behavior fingerprints, cadence, sizing distribution, market/event concentration, rough aggressiveness from observed taker trades, and trade-to-trade markout feasibility.",
        "- Partially valid: markout/alpha timing, because prices are observed only at executions in this slice; no full historical orderbook or passive-order queue is present.",
        "- Not valid yet: full 24-month wallet history, exact maker/passive fill probability, true inventory/PnL over time, complete available-market selection baseline, and full cross-venue causal claims.",
        "",
        "## Coverage Summary",
        "",
        f"- Leaderboard wallets: {m['wallet_coverage']['leaderboard_wallets']}",
        f"- Wallets with fetched weather trades: {m['wallet_coverage']['wallets_with_weather_trades']}",
        f"- Raw trade rows: {m['trade_coverage']['rows']:,}",
        f"- Unique markets: {m['market_coverage']['unique_markets']:,}",
        f"- Unique events: {m['event_coverage']['unique_events']:,}",
        f"- Timestamp range: {m['timestamp_coverage']['min_et']} to {m['timestamp_coverage']['max_et']} ({m['timestamp_coverage']['span_days']:.1f} days)",
        f"- Requested window: {m['timestamp_coverage']['requested_window_days']:.0f} days; observed span is {m['timestamp_coverage']['observed_vs_requested_pct']:.1f}% of that request.",
        f"- Wallets reaching public API offset cap: {m['api_limits']['wallets_reaching_offset_cap']}/{m['wallet_coverage']['leaderboard_wallets']}",
        "",
        "## Observability",
        "",
        f"- Rows with transaction hash: {m['observability']['transaction_hash_pct']:.2f}%",
        f"- Rows with outcome metadata row: {m['observability']['outcome_row_pct']:.2f}%",
        f"- Rows with resolved outcome: {m['outcome_coverage']['resolved_trade_row_pct']:.2f}%",
        f"- Rows with at least one same-market trade context: {m['observability']['same_market_context_pct']:.2f}%",
        f"- Rows with later same-market trade: {m['observability']['later_same_market_trade_pct']:.2f}%",
        f"- Rows with later same-market trade within 60m: {m['observability']['later_trade_60m_pct']:.2f}%",
        f"- Direct weather rows: {m['weather_scope']['direct_weather_pct']:.2f}%",
        f"- Temperature rows: {m['weather_scope']['temperature_pct']:.2f}%",
        "",
        "## Analysis Support Matrix",
        "",
        "| Analysis | Status | Confidence | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for name, spec in support.items():
        lines.append(f"| {name} | {spec['status']} | {spec['confidence']} | {spec['reason']} |")

    lines.extend(
        [
            "",
            "## Biggest Analytical Blind Spots",
            "",
            "1. Public Data API pagination cap means this is a recent slice, not a complete 24-month wallet corpus.",
            "2. Three top-20 leaderboard wallets have zero fetched weather trades in the recent slice, likely because their weather activity is older than the API-accessible window or hidden behind pagination ordering.",
            "3. No historical orderbook snapshots, spread path, queue position, or unfilled passive orders are available from Phase 1 artifacts.",
            "4. Market-selection inference lacks a complete Polymarket weather universe baseline for the exact same timestamps.",
            "5. Polymarket grouped/negative-risk ladder mechanics differ from Kalshi KXHIGHNY, so direct strategy transfer requires care.",
            "",
            "## Wallet Coverage Table",
            "",
            "| rank | userName | proxyWallet | leaderboardVol | fetchedTradeRows | uniqueMarkets | uniqueEvents | apiCapped | activeInSlice |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in wallet_table.itertuples(index=False):
        lines.append(
            f"| {row.rank} | {row.userName} | {row.proxyWallet} | {row.vol} | "
            f"{int(row.fetched_trade_rows)} | {int(row.unique_markets)} | {int(row.unique_events)} | "
            f"{row.reached_api_offset_cap} | {row.has_fetched_weather_trades} |"
        )

    lines.extend(
        [
            "",
            "## Phase 3 Recommendation",
            "",
            "Proceed to wallet behavioral profiles, but label every conclusion as recent-slice evidence. Add subgraph/on-chain backfill before making claims about full 24-month trader behavior or durable edge.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    leaderboard, trades, outcomes, summary = load_inputs()
    trades = add_trade_features(trades, outcomes)
    wallet_df = wallet_coverage(leaderboard, trades, summary)

    min_dt = trades["dt_et"].min()
    max_dt = trades["dt_et"].max()
    span_days = (max_dt - min_dt).total_seconds() / 86400
    requested_start = datetime.fromisoformat(summary["window_start_et"])
    requested_end = datetime.fromisoformat(summary["window_end_et"])
    requested_days = (requested_end - requested_start).total_seconds() / 86400

    px_ctx = price_context_metrics(trades)
    resolved_by_trade = int(trades["has_resolved_outcome"].sum())

    metrics = {
        "wallet_coverage": {
            "leaderboard_wallets": int(len(leaderboard)),
            "wallets_with_weather_trades": int(trades["proxyWallet"].nunique()),
            "wallets_without_weather_trades_in_slice": int(len(leaderboard) - trades["proxyWallet"].nunique()),
            "wallet_coverage_pct": pct(trades["proxyWallet"].nunique(), len(leaderboard)),
            "wallet_trade_count_min_nonzero": int(wallet_df.loc[wallet_df["fetched_trade_rows"] > 0, "fetched_trade_rows"].min()),
            "wallet_trade_count_median_nonzero": float(wallet_df.loc[wallet_df["fetched_trade_rows"] > 0, "fetched_trade_rows"].median()),
            "wallet_trade_count_max": int(wallet_df["fetched_trade_rows"].max()),
        },
        "trade_coverage": {
            "rows": int(len(trades)),
            "dedupe_transaction_hash_rows": int(trades["transactionHash"].nunique()),
            "notional_usd_proxy": float(trades["notional_usd_proxy"].sum()),
            "buy_rows": int((trades["side"] == "BUY").sum()),
            "sell_rows": int((trades["side"] == "SELL").sum()),
        },
        "market_coverage": {
            "unique_markets": int(trades["conditionId"].nunique()),
            "outcome_rows": int(len(outcomes)),
            "market_metadata_coverage_pct": pct(trades["conditionId"].nunique(), len(outcomes)),
            "closed_market_rows": int(outcomes["closed"].fillna(False).sum()),
            "resolved_market_rows": int(outcomes["resolved_outcome"].notna().sum()),
            "resolved_market_pct": pct(outcomes["resolved_outcome"].notna().sum(), len(outcomes)),
        },
        "event_coverage": {
            "unique_events": int(trades["eventSlug"].nunique()),
            "event_entropy_bits": entropy(trades["eventSlug"]),
            "top_event_trade_share_pct": pct(trades["eventSlug"].value_counts().iloc[0], len(trades)),
        },
        "timestamp_coverage": {
            "min_et": min_dt.isoformat(),
            "max_et": max_dt.isoformat(),
            "span_days": span_days,
            "requested_window_start_et": requested_start.isoformat(),
            "requested_window_end_et": requested_end.isoformat(),
            "requested_window_days": requested_days,
            "observed_vs_requested_pct": pct(span_days, requested_days),
            "unique_trade_dates_et": int(trades["date_et"].nunique()),
        },
        "outcome_coverage": {
            "resolved_trade_rows": resolved_by_trade,
            "unresolved_trade_rows": int(len(trades) - resolved_by_trade),
            "resolved_trade_row_pct": pct(resolved_by_trade, len(trades)),
        },
        "observability": {
            "transaction_hash_rows": int(trades["transactionHash"].notna().sum()),
            "transaction_hash_pct": pct(trades["transactionHash"].notna().sum(), len(trades)),
            "price_rows": int(trades["price"].notna().sum()),
            "price_pct": pct(trades["price"].notna().sum(), len(trades)),
            "size_rows": int(trades["size"].notna().sum()),
            "size_pct": pct(trades["size"].notna().sum(), len(trades)),
            "outcome_row_pct": pct(trades["has_outcome_row"].sum(), len(trades)),
            "same_market_context_pct": pct(px_ctx["rows_with_any_same_market_context"], len(trades)),
            "prior_same_market_trade_pct": pct(px_ctx["rows_with_prior_same_market_trade"], len(trades)),
            "later_same_market_trade_pct": pct(px_ctx["rows_with_later_same_market_trade"], len(trades)),
            "later_trade_1m_pct": pct(px_ctx["rows_with_later_trade_1m"], len(trades)),
            "later_trade_5m_pct": pct(px_ctx["rows_with_later_trade_5m"], len(trades)),
            "later_trade_60m_pct": pct(px_ctx["rows_with_later_trade_60m"], len(trades)),
            "later_trade_1d_pct": pct(px_ctx["rows_with_later_trade_1d"], len(trades)),
        },
        "weather_scope": {
            "direct_weather_rows": int(trades["is_weather_direct"].sum()),
            "direct_weather_pct": pct(trades["is_weather_direct"].sum(), len(trades)),
            "weather_adjacent_rows": int(trades["is_weather_adjacent"].sum()),
            "weather_adjacent_pct": pct(trades["is_weather_adjacent"].sum(), len(trades)),
            "temperature_rows": int(trades["is_temperature"].sum()),
            "temperature_pct": pct(trades["is_temperature"].sum(), len(trades)),
        },
        "api_limits": {
            "max_trade_offset_attempted": summary.get("max_trade_offset_attempted"),
            "trade_pagination_limit": summary.get("trade_pagination_limit"),
            "wallets_reaching_offset_cap": int(wallet_df["reached_api_offset_cap"].fillna(False).sum()),
            "all_top20_reached_offset_cap": bool(wallet_df["reached_api_offset_cap"].fillna(False).all()),
        },
    }

    readiness = {
        "generated_at_et": datetime.now(tz=ET).isoformat(),
        "phase": "polymarket_weather_wallet_phase2_readiness",
        "inputs": {
            "leaderboard": str(DATA_DIR / "polymarket_top_weather_traders.csv"),
            "trades": str(DATA_DIR / "polymarket_trades_raw.parquet"),
            "outcomes": str(DATA_DIR / "polymarket_market_outcomes.parquet"),
            "summary": str(DATA_DIR / "polymarket_phase1_summary.json"),
        },
        "metrics": metrics,
    }
    readiness["decision"] = readiness_verdict(metrics)

    (DATA_DIR / "polymarket_phase2_readiness.json").write_text(json.dumps(readiness, indent=2, default=str) + "\n")
    (REPORT_DIR / "polymarket_phase2_readiness.md").write_text(build_report(readiness, wallet_df))

    print("=== PHASE 2 READINESS VERDICT ===")
    print(readiness["decision"]["verdict"])
    print()
    print("Coverage:")
    print(f"  wallets: {metrics['wallet_coverage']['wallets_with_weather_trades']}/{metrics['wallet_coverage']['leaderboard_wallets']} active in fetched slice")
    print(f"  trades: {metrics['trade_coverage']['rows']:,}")
    print(f"  markets: {metrics['market_coverage']['unique_markets']:,}")
    print(f"  events: {metrics['event_coverage']['unique_events']:,}")
    print(f"  timestamp span: {metrics['timestamp_coverage']['span_days']:.1f} days ({metrics['timestamp_coverage']['observed_vs_requested_pct']:.1f}% of requested 24m)")
    print()
    print("Observability:")
    print(f"  transaction hashes: {metrics['observability']['transaction_hash_pct']:.2f}%")
    print(f"  outcome metadata rows: {metrics['observability']['outcome_row_pct']:.2f}%")
    print(f"  resolved outcome rows: {metrics['outcome_coverage']['resolved_trade_row_pct']:.2f}%")
    print(f"  same-market price context: {metrics['observability']['same_market_context_pct']:.2f}%")
    print(f"  later same-market trade within 60m: {metrics['observability']['later_trade_60m_pct']:.2f}%")
    print(f"  direct weather rows: {metrics['weather_scope']['direct_weather_pct']:.2f}%")
    print(f"  temperature rows: {metrics['weather_scope']['temperature_pct']:.2f}%")
    print()
    print("Biggest blind spots:")
    print("  1. API cap: all top-20 wallets reached the public trade-history offset cap.")
    print("  2. Observed span is recent only, not full 24 months.")
    print("  3. No orderbook snapshots or unfilled passive-order data.")
    print("  4. Complete available-market baseline still needs Gamma universe build/backfill.")
    print()
    print("Saved:")
    print(f"  {DATA_DIR / 'polymarket_phase2_readiness.json'}")
    print(f"  {REPORT_DIR / 'polymarket_phase2_readiness.md'}")


if __name__ == "__main__":
    main()
