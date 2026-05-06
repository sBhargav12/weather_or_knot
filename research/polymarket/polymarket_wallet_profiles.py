"""Phase 3 wallet behavioral profiles for Polymarket weather traders.

Research-only. This uses the Phase 1/2 API-accessible recent slice and inherits
the Phase 2 limitation: it is descriptive/provisional, not a complete 24-month
alpha study and not exact maker/passive fill truth.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


DATA_DIR = Path("data/research")
REPORT_DIR = Path("reports")
ET = ZoneInfo("America/New_York")

CITY_RE = re.compile(r"highest temperature in ([A-Za-z .'-]+?) (?:be|on)", re.I)
BETWEEN_RE = re.compile(r"between\s+(-?\d+(?:\.\d+)?)\s*(?:-|and)\s*(-?\d+(?:\.\d+)?)", re.I)
OR_BELOW_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°?[CF])?\s*or below", re.I)
OR_ABOVE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°?[CF])?\s*or above", re.I)
EXACT_TEMP_RE = re.compile(r"be\s+(-?\d+(?:\.\d+)?)\s*°?[CF]\b", re.I)


def pct(numer: float, denom: float) -> float:
    return 0.0 if denom == 0 else 100.0 * numer / denom


def safe_div(numer: float, denom: float) -> float:
    return 0.0 if denom == 0 else float(numer / denom)


def entropy(series: pd.Series) -> float:
    counts = series.dropna().value_counts()
    if counts.empty:
        return 0.0
    probs = counts / counts.sum()
    return float(-(probs * np.log2(probs)).sum())


def normalized_entropy(series: pd.Series) -> float:
    n = series.dropna().nunique()
    if n <= 1:
        return 0.0
    return entropy(series) / math.log2(n)


def bucket_price(price: float | None) -> str:
    if price is None or pd.isna(price):
        return "unknown"
    p = float(price)
    if p < 0.05:
        return "00-05"
    if p < 0.10:
        return "05-10"
    if p < 0.20:
        return "10-20"
    if p < 0.40:
        return "20-40"
    if p < 0.60:
        return "40-60"
    if p < 0.80:
        return "60-80"
    if p < 0.95:
        return "80-95"
    return "95-100"


def bucket_hours(hours: float | None) -> str:
    if hours is None or pd.isna(hours):
        return "unknown"
    h = float(hours)
    if h < 0:
        return "after_close_or_resolved"
    if h <= 1:
        return "0-1h"
    if h <= 6:
        return "1-6h"
    if h <= 24:
        return "6-24h"
    if h <= 72:
        return "1-3d"
    if h <= 168:
        return "3-7d"
    return "7d+"


def parse_city(title: str) -> str:
    match = CITY_RE.search(title or "")
    if match:
        return match.group(1).strip()
    if "global temperature" in (title or "").lower() or "temperature increase" in (title or "").lower():
        return "Global"
    return "Unknown"


def market_family(title: str) -> str:
    s = (title or "").lower()
    if "highest temperature" in s or "lowest temperature" in s or "temperature" in s or "°c" in s or "°f" in s:
        if "global temperature" in s or "temperature increase" in s:
            return "macro_temperature"
        return "daily_temperature"
    if "rain" in s or "precipitation" in s:
        return "precipitation"
    if "snow" in s:
        return "snow"
    if "hurricane" in s or "storm" in s or "tornado" in s:
        return "storm"
    return "other_weather"


def bracket_family(title: str) -> str:
    s = title or ""
    if OR_BELOW_RE.search(s):
        return "lower_tail"
    if OR_ABOVE_RE.search(s):
        return "upper_tail"
    if BETWEEN_RE.search(s):
        return "range"
    if EXACT_TEMP_RE.search(s):
        return "exact_temp"
    return "non_temperature_or_unknown"


def favorite_longshot(price: float, outcome: str) -> str:
    p = float(price)
    # For BUY NO at high NO price this is favorite-NO, but from a YES-market
    # transfer perspective it is often tail fading. Keep outcome explicit.
    if p >= 0.95:
        return f"deep_favorite_{str(outcome).lower()}"
    if p >= 0.80:
        return f"favorite_{str(outcome).lower()}"
    if p <= 0.05:
        return f"deep_longshot_{str(outcome).lower()}"
    if p <= 0.20:
        return f"longshot_{str(outcome).lower()}"
    return "mid_price"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    leaderboard = pd.read_csv(DATA_DIR / "polymarket_top_weather_traders.csv")
    trades = pd.read_parquet(DATA_DIR / "polymarket_trades_raw.parquet")
    outcomes = pd.read_parquet(DATA_DIR / "polymarket_market_outcomes.parquet")
    phase1 = json.loads((DATA_DIR / "polymarket_phase1_summary.json").read_text())
    phase2 = json.loads((DATA_DIR / "polymarket_phase2_readiness.json").read_text())
    return leaderboard, trades, outcomes, phase1, phase2


def enrich_trades(trades: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["dt_et"] = pd.to_datetime(t["timestamp"], unit="s", utc=True).dt.tz_convert("America/New_York")
    t["date_et"] = t["dt_et"].dt.date.astype(str)
    t["hour_et"] = t["dt_et"].dt.hour
    t["weekday_et"] = t["dt_et"].dt.day_name()
    t["price_bucket"] = t["price"].map(bucket_price)
    t["city"] = t["title"].fillna("").map(parse_city)
    t["market_family"] = t["title"].fillna("").map(market_family)
    t["bracket_family"] = t["title"].fillna("").map(bracket_family)
    t["fav_longshot_bucket"] = [favorite_longshot(p, o) for p, o in zip(t["price"], t["outcome"], strict=False)]

    keep = [
        "conditionId",
        "endDate",
        "closed",
        "resolved_outcome",
        "resolved_yes",
        "event_closed",
        "event_title",
        "event_endDate",
    ]
    t = t.merge(outcomes[keep], on="conditionId", how="left", validate="many_to_one")
    end = pd.to_datetime(t["endDate"], utc=True, errors="coerce").dt.tz_convert("America/New_York")
    t["end_dt_et"] = end
    t["hours_to_close"] = (end - t["dt_et"]).dt.total_seconds() / 3600
    t["time_to_close_bucket"] = t["hours_to_close"].map(bucket_hours)
    t["is_buy"] = t["side"].eq("BUY")
    t["is_sell"] = t["side"].eq("SELL")
    t["is_yes"] = t["outcome"].astype(str).str.lower().eq("yes")
    t["is_no"] = t["outcome"].astype(str).str.lower().eq("no")
    t["is_extreme_price"] = (t["price"] <= 0.10) | (t["price"] >= 0.90)
    t["is_mid_price"] = (t["price"] >= 0.35) & (t["price"] <= 0.65)
    t["notional_usd_proxy"] = pd.to_numeric(t["notional_usd_proxy"], errors="coerce").fillna(
        t["size"].fillna(0) * t["price"].fillna(0)
    )
    return t


def median_inter_trade_seconds(wallet_trades: pd.DataFrame) -> float | None:
    times = wallet_trades.sort_values("timestamp")["timestamp"].drop_duplicates()
    if len(times) < 2:
        return None
    return float(times.diff().dropna().median())


def burstiness(wallet_trades: pd.DataFrame) -> float:
    times = wallet_trades.sort_values("timestamp")["timestamp"].drop_duplicates()
    if len(times) < 3:
        return 0.0
    intervals = times.diff().dropna().astype(float)
    mean = intervals.mean()
    std = intervals.std(ddof=0)
    if mean + std == 0:
        return 0.0
    # Goh-Barabasi burstiness index, range roughly [-1,1].
    return float((std - mean) / (std + mean))


def same_day_exit_proxy(wallet_trades: pd.DataFrame) -> float:
    grouped = wallet_trades.groupby(["conditionId", "date_et"])
    has_both = grouped.apply(lambda x: x["is_buy"].any() and x["is_sell"].any(), include_groups=False)
    return pct(int(has_both.sum()), wallet_trades["conditionId"].nunique())


def scale_proxy(wallet_trades: pd.DataFrame) -> tuple[float, float]:
    grouped = wallet_trades.groupby("conditionId")
    repeated_markets = grouped.size().gt(1).sum()
    both_sides = grouped.apply(lambda x: x["side"].nunique() > 1, include_groups=False).sum()
    market_count = wallet_trades["conditionId"].nunique()
    return pct(repeated_markets, market_count), pct(both_sides, market_count)


def top_share(series: pd.Series) -> float:
    counts = series.dropna().value_counts()
    if counts.empty:
        return 0.0
    return pct(counts.iloc[0], counts.sum())


def profile_wallet(wallet: str, wallet_trades: pd.DataFrame, leaderboard_row: pd.Series | None) -> dict[str, Any]:
    wt = wallet_trades.sort_values("timestamp").copy()
    trade_count = len(wt)
    active_days = wt["date_et"].nunique()
    market_count = wt["conditionId"].nunique()
    event_count = wt["eventSlug"].nunique()
    repeated_market_rate, scale_out_rate = scale_proxy(wt)

    hour_counts = wt["hour_et"].value_counts()
    peak_hour = int(hour_counts.idxmax()) if not hour_counts.empty else None
    peak_hour_share = pct(hour_counts.max(), trade_count) if not hour_counts.empty else 0.0

    ttc_counts = wt["time_to_close_bucket"].value_counts()
    top_ttc_bucket = str(ttc_counts.idxmax()) if not ttc_counts.empty else "unknown"
    price_counts = wt["price_bucket"].value_counts()
    top_price_bucket = str(price_counts.idxmax()) if not price_counts.empty else "unknown"

    side_buy_pct = pct(wt["is_buy"].sum(), trade_count)
    no_outcome_pct = pct(wt["is_no"].sum(), trade_count)
    extreme_price_pct = pct(wt["is_extreme_price"].sum(), trade_count)
    mid_price_pct = pct(wt["is_mid_price"].sum(), trade_count)
    same_day_exit = same_day_exit_proxy(wt)
    median_gap = median_inter_trade_seconds(wt)

    observed_aggressiveness = 50.0
    observed_aggressiveness += min(20.0, peak_hour_share / 2)
    observed_aggressiveness += min(15.0, pct((wt.groupby("conditionId").cumcount() > 0).sum(), trade_count) / 5)
    observed_aggressiveness += 10.0 if median_gap is not None and median_gap < 30 else 0.0
    observed_aggressiveness = min(100.0, observed_aggressiveness)

    archetype, archetype_reason = assign_archetype(
        trade_count=trade_count,
        event_count=event_count,
        market_count=market_count,
        extreme_price_pct=extreme_price_pct,
        mid_price_pct=mid_price_pct,
        no_outcome_pct=no_outcome_pct,
        repeated_market_rate=repeated_market_rate,
        same_day_exit=same_day_exit,
        peak_hour_share=peak_hour_share,
        burst=burstiness(wt),
    )

    confidence = 35.0
    confidence += min(25.0, trade_count / 100)
    confidence += min(15.0, active_days / 3)
    confidence += 10.0 if event_count >= 20 else 0.0
    confidence += 10.0 if repeated_market_rate > 20 else 0.0
    confidence = min(90.0, confidence)
    if trade_count < 200:
        confidence = min(confidence, 45.0)

    top_city = wt["city"].value_counts().idxmax() if wt["city"].notna().any() else "Unknown"
    top_family = wt["market_family"].value_counts().idxmax() if wt["market_family"].notna().any() else "unknown"
    top_bracket = wt["bracket_family"].value_counts().idxmax() if wt["bracket_family"].notna().any() else "unknown"

    return {
        "wallet": wallet,
        "user_name": str(wt["leaderboard_username"].iloc[0]),
        "leaderboard_rank": int(leaderboard_row["rank"]) if leaderboard_row is not None else None,
        "leaderboard_volume_usd": float(leaderboard_row["vol"]) if leaderboard_row is not None else None,
        "trade_count": int(trade_count),
        "active_days": int(active_days),
        "trades_per_active_day": safe_div(trade_count, active_days),
        "market_count": int(market_count),
        "event_count": int(event_count),
        "median_inter_trade_seconds": median_gap,
        "burstiness_score": burstiness(wt),
        "peak_hour_et": peak_hour,
        "peak_hour_share_pct": peak_hour_share,
        "top_time_to_close_bucket": top_ttc_bucket,
        "top_price_bucket": top_price_bucket,
        "mean_trade_size": float(wt["size"].mean()),
        "median_trade_size": float(wt["size"].median()),
        "trade_size_std": float(wt["size"].std(ddof=0)),
        "mean_notional_usd_proxy": float(wt["notional_usd_proxy"].mean()),
        "median_notional_usd_proxy": float(wt["notional_usd_proxy"].median()),
        "notional_usd_proxy_total": float(wt["notional_usd_proxy"].sum()),
        "buy_trade_pct": side_buy_pct,
        "sell_trade_pct": 100 - side_buy_pct,
        "no_outcome_trade_pct": no_outcome_pct,
        "yes_outcome_trade_pct": 100 - no_outcome_pct,
        "extreme_price_trade_pct": extreme_price_pct,
        "mid_price_trade_pct": mid_price_pct,
        "city_entropy_norm": normalized_entropy(wt["city"]),
        "market_family_entropy_norm": normalized_entropy(wt["market_family"]),
        "bracket_family_entropy_norm": normalized_entropy(wt["bracket_family"]),
        "event_entropy_norm": normalized_entropy(wt["eventSlug"]),
        "top_city": top_city,
        "top_city_share_pct": top_share(wt["city"]),
        "top_market_family": top_family,
        "top_market_family_share_pct": top_share(wt["market_family"]),
        "top_bracket_family": top_bracket,
        "top_bracket_family_share_pct": top_share(wt["bracket_family"]),
        "repeat_market_rate_pct": repeated_market_rate,
        "scale_in_out_proxy_pct": scale_out_rate,
        "same_day_exit_proxy_pct": same_day_exit,
        "hold_to_resolution_proxy_pct": pct((wt["hours_to_close"] <= 24).sum(), trade_count),
        "taker_only_observed_ratio": None,
        "maker_rebate_evidence_ratio": None,
        "maker_taker_ambiguity_share_pct": 100.0,
        "estimated_aggressiveness_score": observed_aggressiveness,
        "provisional_archetype": archetype,
        "archetype_reason": archetype_reason,
        "archetype_confidence_score": confidence,
        "evidence_scope": "recent_api_slice",
    }


def assign_archetype(
    *,
    trade_count: int,
    event_count: int,
    market_count: int,
    extreme_price_pct: float,
    mid_price_pct: float,
    no_outcome_pct: float,
    repeated_market_rate: float,
    same_day_exit: float,
    peak_hour_share: float,
    burst: float,
) -> tuple[str, str]:
    if trade_count < 200:
        return "mixed / unclear", "Too few fetched recent-slice trades for a stable archetype."
    if repeated_market_rate > 70 and event_count < max(20, market_count / 5):
        return "ladder optimizer", "High repeat-market rate with concentrated event count suggests grouped ladder management."
    if extreme_price_pct > 65 and no_outcome_pct > 60:
        return "expiry / resolution specialist", "Large share of extreme-price NO/YES trades suggests tail or near-resolution harvesting."
    if extreme_price_pct > 55:
        return "ladder optimizer", "Dominant extreme-price activity suggests ladder/tail construction rather than mid-price directional trading."
    if mid_price_pct > 45 and same_day_exit > 25:
        return "mean reverter", "Mid-price activity plus same-day buy/sell proxy suggests active reversion or inventory cycling."
    if peak_hour_share > 35 and burst > 0.25:
        return "aggressive taker", "Trades are temporally clustered in bursts; maker/passive status is still unobserved."
    if event_count > 200 and market_count > 500:
        return "broad exploration", "Very broad market/event coverage, less specialized than ladder/event-focused wallets."
    return "mixed / unclear", "Metrics do not cleanly identify one dominant public-data archetype."


def defining_metrics(row: pd.Series) -> list[str]:
    metrics = [
        f"{int(row.trade_count):,} trades over {int(row.active_days)} active days",
        f"{row.extreme_price_trade_pct:.1f}% extreme-price trades",
        f"{row.no_outcome_trade_pct:.1f}% NO-outcome trades",
        f"{row.repeat_market_rate_pct:.1f}% repeat-market rate",
        f"top city {row.top_city} ({row.top_city_share_pct:.1f}%)",
    ]
    return metrics


def write_report(profiles: pd.DataFrame, phase2: dict[str, Any]) -> None:
    lines = [
        "# Polymarket Weather Wallet Profiles",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "This is Phase 3 research-only output. It inherits the Phase 2 scope: recent API-accessible slice, descriptive inference only, no complete 24-month alpha claims, and no exact maker/passive fill truth.",
        "",
        "## Phase 2 Readiness Context",
        "",
        f"- Readiness verdict: {phase2['decision']['verdict']}",
        f"- Trade rows: {phase2['metrics']['trade_coverage']['rows']:,}",
        f"- Active wallets in fetched slice: {phase2['metrics']['wallet_coverage']['wallets_with_weather_trades']}/{phase2['metrics']['wallet_coverage']['leaderboard_wallets']}",
        f"- Resolved trade rows: {phase2['metrics']['outcome_coverage']['resolved_trade_row_pct']:.2f}%",
        "",
        "## Wallet Profile Table",
        "",
        "| rank | user | archetype | confidence | trades | active days | markets | events | top family | top bracket | extreme % | repeat-market % | peak hour ET |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for row in profiles.sort_values("leaderboard_rank").itertuples(index=False):
        lines.append(
            f"| {row.leaderboard_rank} | {row.user_name} | {row.provisional_archetype} | "
            f"{row.archetype_confidence_score:.0f} | {row.trade_count} | {row.active_days} | "
            f"{row.market_count} | {row.event_count} | {row.top_market_family} | {row.top_bracket_family} | "
            f"{row.extreme_price_trade_pct:.1f} | {row.repeat_market_rate_pct:.1f} | {row.peak_hour_et} |"
        )

    lines.extend(["", "## Profile Cards", ""])
    for row in profiles.sort_values("leaderboard_rank").itertuples(index=False):
        r = pd.Series(row._asdict())
        lines.extend(
            [
                f"### {row.leaderboard_rank}. {row.user_name}",
                "",
                f"- Wallet: `{row.wallet}`",
                f"- Archetype: **{row.provisional_archetype}** (confidence {row.archetype_confidence_score:.0f}/100)",
                f"- Reason: {row.archetype_reason}",
                f"- Activity: {row.trade_count:,} trades, {row.active_days} active days, {row.trades_per_active_day:.1f} trades/active day.",
                f"- Selection: {row.market_count:,} markets, {row.event_count:,} events, top city `{row.top_city}` ({row.top_city_share_pct:.1f}%).",
                f"- Sizing: median size {row.median_trade_size:.2f}, median notional proxy ${row.median_notional_usd_proxy:.2f}.",
                f"- Execution observability: maker/taker role is ambiguous from this public slice; `side` is wallet action, not passive/aggressive proof.",
                "- Defining metrics: " + "; ".join(defining_metrics(r)) + ".",
                "",
            ]
        )

    lines.extend(
        [
            "## Biggest Behavioral Differences",
            "",
            "- Some wallets are broad explorers with hundreds of markets/events; others are concentrated event/ladder managers.",
            "- Extreme-price activity is a first-order separator and likely captures tail-NO / ladder / near-resolution behavior.",
            "- Repeat-market rate is a stronger archetype clue than raw volume because many top wallets have similar API-capped trade counts.",
            "- Maker/taker style remains unobservable from Phase 1 alone; do not treat these profiles as execution-role truth.",
            "",
            "## Next Phase Readiness",
            "",
            "Proceed to Phase 4 markout analysis using trade-to-trade price context. Keep markout claims scoped to observed executions, not full orderbook paths.",
        ]
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "polymarket_wallet_profiles.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    leaderboard, trades, outcomes, _phase1, phase2 = load_data()
    enriched = enrich_trades(trades, outcomes)

    profiles = []
    by_wallet = enriched.groupby("proxyWallet", sort=False)
    leaderboard_index = {row.proxyWallet: row for row in leaderboard.itertuples(index=False)}
    for wallet, wallet_trades in by_wallet:
        lb_row = leaderboard_index.get(wallet)
        lb_series = pd.Series(lb_row._asdict()) if lb_row is not None else None
        profiles.append(profile_wallet(wallet, wallet_trades, lb_series))

    profile_df = pd.DataFrame(profiles).sort_values("leaderboard_rank")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    profile_df.to_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet", index=False)
    write_report(profile_df, phase2)

    print("=== PHASE 3 WALLET BEHAVIORAL PROFILES ===")
    print("Scope: recent API-accessible slice; descriptive/provisional archetypes only.")
    print(f"Wallets profiled: {len(profile_df)}")
    print(f"Trade rows represented: {int(profile_df['trade_count'].sum()):,}")
    print()
    display_cols = [
        "leaderboard_rank",
        "user_name",
        "provisional_archetype",
        "archetype_confidence_score",
        "trade_count",
        "active_days",
        "market_count",
        "event_count",
        "top_market_family",
        "top_bracket_family",
        "extreme_price_trade_pct",
        "repeat_market_rate_pct",
    ]
    print(
        profile_df[display_cols].to_string(
            index=False,
            formatters={
                "archetype_confidence_score": "{:.0f}".format,
                "extreme_price_trade_pct": "{:.1f}".format,
                "repeat_market_rate_pct": "{:.1f}".format,
            },
        )
    )
    print()
    print("Archetype counts:")
    print(profile_df["provisional_archetype"].value_counts().to_string())
    print()
    print("Biggest behavioral differences:")
    print("  1. Extreme-price activity separates tail/ladder specialists from mid-price traders.")
    print("  2. Repeat-market/event concentration separates ladder optimizers from broad explorers.")
    print("  3. Several high-volume wallets are active almost entirely in daily temperature markets.")
    print("  4. Maker/taker role remains ambiguous; public Data API side is wallet action, not passive/aggressive proof.")
    print()
    print("Saved:")
    print(f"  {DATA_DIR / 'polymarket_wallet_profiles.parquet'}")
    print(f"  {REPORT_DIR / 'polymarket_wallet_profiles.md'}")


if __name__ == "__main__":
    main()
