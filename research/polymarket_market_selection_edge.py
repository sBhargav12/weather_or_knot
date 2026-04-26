"""Phase 5 market-selection edge analysis for Polymarket weather wallets."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from polymarket_research_common import DATA_DIR, ET, REPORT_DIR, enriched_trades, md_table, normalized_entropy, pct


def segment_table(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(cols, dropna=False)
        .agg(
            trades=("transactionHash", "count"),
            wallets=("proxyWallet", "nunique"),
            markets=("conditionId", "nunique"),
            events=("eventSlug", "nunique"),
            avg_price=("price", "mean"),
            avg_notional=("notional_usd_proxy", "mean"),
            resolved_rows=("settlement_return_pp", lambda s: int(s.notna().sum())),
            avg_settlement_return_pp=("settlement_return_pp", "mean"),
            win_rate=("settlement_return_pp", lambda s: float((s > 0).mean() * 100) if s.notna().any() else None),
        )
        .reset_index()
        .sort_values("trades", ascending=False)
    )


def wallet_selection(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wallet, g in df.groupby("proxyWallet"):
        rows.append(
            {
                "wallet": wallet,
                "user_name": g["leaderboard_username"].iloc[0],
                "trades": len(g),
                "markets": g["conditionId"].nunique(),
                "events": g["eventSlug"].nunique(),
                "cities": g["city"].nunique(),
                "city_entropy_norm": normalized_entropy(g["city"]),
                "event_entropy_norm": normalized_entropy(g["eventSlug"]),
                "bracket_entropy_norm": normalized_entropy(g["bracket_family"]),
                "daily_temperature_share_pct": pct((g["market_family"] == "daily_temperature").sum(), len(g)),
                "extreme_price_share_pct": pct(g["is_extreme_price"].sum(), len(g)),
                "tail_or_exact_share_pct": pct(g["bracket_family"].isin(["lower_tail", "upper_tail", "exact_temp"]).sum(), len(g)),
                "range_share_pct": pct((g["bracket_family"] == "range").sum(), len(g)),
                "avg_settlement_return_pp": g["settlement_return_pp"].mean(),
                "settlement_win_rate": float((g["settlement_return_pp"] > 0).mean() * 100)
                if g["settlement_return_pp"].notna().any()
                else None,
                "top_city": g["city"].value_counts().idxmax(),
                "top_city_share_pct": pct(g["city"].value_counts().iloc[0], len(g)),
                "top_price_bucket": g["price_bucket"].value_counts().idxmax(),
                "top_bracket_family": g["bracket_family"].value_counts().idxmax(),
            }
        )
    return pd.DataFrame(rows).sort_values("trades", ascending=False)


def main() -> None:
    t = enriched_trades()
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    t = t.merge(profiles[["wallet", "provisional_archetype"]], left_on="proxyWallet", right_on="wallet", how="left")

    wallet = wallet_selection(t)
    by_city = segment_table(t, ["city"])
    by_family = segment_table(t, ["market_family", "bracket_family"])
    by_price = segment_table(t, ["price_bucket"])
    by_ttc = segment_table(t, ["time_to_close_bucket"])
    by_archetype = segment_table(t, ["provisional_archetype", "market_family", "bracket_family"])

    out = pd.concat(
        [
            by_city.assign(segment_type="city").rename(columns={"city": "segment"}),
            by_price.assign(segment_type="price_bucket").rename(columns={"price_bucket": "segment"}),
            by_ttc.assign(segment_type="time_to_close").rename(columns={"time_to_close_bucket": "segment"}),
        ],
        ignore_index=True,
    )
    out.to_parquet(DATA_DIR / "polymarket_market_selection_edge.parquet", index=False)
    wallet.to_parquet(DATA_DIR / "polymarket_market_selection_wallet.parquet", index=False)

    report = [
        "# Polymarket Market-Selection Edge",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "Research-only. Selection is measured against the observed traded slice, not the full available Polymarket universe. A true available-market baseline needs Gamma universe backfill.",
        "",
        "## Wallet Selection Summary",
        "",
        md_table(wallet[["user_name", "trades", "markets", "events", "city_entropy_norm", "extreme_price_share_pct", "tail_or_exact_share_pct", "top_city", "top_price_bucket", "avg_settlement_return_pp"]]),
        "",
        "## Selection by City",
        "",
        md_table(by_city[["city", "trades", "wallets", "markets", "avg_settlement_return_pp", "win_rate"]].head(20)),
        "",
        "## Selection by Market / Bracket Family",
        "",
        md_table(by_family[["market_family", "bracket_family", "trades", "wallets", "avg_settlement_return_pp", "win_rate"]].head(20)),
        "",
        "## Selection by Price Bucket",
        "",
        md_table(by_price[["price_bucket", "trades", "wallets", "avg_settlement_return_pp", "win_rate"]]),
        "",
        "## Selection by Time-to-Close",
        "",
        md_table(by_ttc[["time_to_close_bucket", "trades", "wallets", "avg_settlement_return_pp", "win_rate"]]),
        "",
        "## Exploitable Market-Structure Insights",
        "",
        "1. The top wallets in the recent slice overwhelmingly select daily temperature ladders, not broad weather categories.",
        "2. Extreme price buckets dominate several wallets, suggesting tail fading, ladder netting, or near-resolution harvesting.",
        "3. Exact-temperature / grouped-ladder markets are much more common than Kalshi's six-bracket KXHIGH structure, so transfer requires adapting the idea, not copying the contract.",
        "4. Avoid/selection claims are incomplete until we build the available-market universe baseline.",
    ]
    (REPORT_DIR / "polymarket_market_selection_edge.md").write_text("\n".join(report) + "\n")

    print("=== PHASE 5 MARKET-SELECTION EDGE ===")
    print(f"Trades analyzed: {len(t):,}")
    print("Top selection segments by trade count:")
    print(by_family[["market_family", "bracket_family", "trades", "wallets", "avg_settlement_return_pp", "win_rate"]].head(12).to_string(index=False))
    print("\nWallet selection summary:")
    print(wallet[["user_name", "trades", "markets", "events", "extreme_price_share_pct", "tail_or_exact_share_pct", "top_city", "top_price_bucket"]].head(17).to_string(index=False))
    print("\nSaved:")
    print(f"  {DATA_DIR / 'polymarket_market_selection_edge.parquet'}")
    print(f"  {DATA_DIR / 'polymarket_market_selection_wallet.parquet'}")
    print(f"  {REPORT_DIR / 'polymarket_market_selection_edge.md'}")


if __name__ == "__main__":
    main()

