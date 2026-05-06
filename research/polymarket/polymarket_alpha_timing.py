"""Phase 4 alpha timing / markout analysis for Polymarket weather wallets."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from polymarket_research_common import (
    DATA_DIR,
    ET,
    REPORT_DIR,
    compute_trade_markouts,
    enriched_trades,
    md_table,
    pct,
)


def agg_markouts(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)
        .agg(
            trades=("transactionHash", "count"),
            wallets=("proxyWallet", "nunique"),
            markets=("conditionId", "nunique"),
            avg_1m_pp=("signed_markout_pp_1m", "mean"),
            avg_5m_pp=("signed_markout_pp_5m", "mean"),
            avg_60m_pp=("signed_markout_pp_60m", "mean"),
            avg_1d_pp=("signed_markout_pp_1d", "mean"),
            avg_to_last_pp=("signed_markout_pp_to_last_observed", "mean"),
            coverage_60m=("signed_markout_pp_60m", lambda s: pct(s.notna().sum(), len(s))),
            settlement_avg_pp=("settlement_return_pp", "mean"),
            settlement_win_rate=("settlement_return_pp", lambda s: float((s > 0).mean() * 100) if s.notna().any() else None),
        )
        .reset_index()
        .sort_values(["trades"], ascending=False)
    )


def main() -> None:
    trades = enriched_trades()
    markouts = compute_trade_markouts(trades)
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    markouts = markouts.merge(
        profiles[["wallet", "user_name", "provisional_archetype"]],
        left_on="proxyWallet",
        right_on="wallet",
        how="left",
    )

    wallet = agg_markouts(markouts, ["user_name", "proxyWallet", "provisional_archetype"]).sort_values(
        "avg_60m_pp", ascending=False
    )
    hour = agg_markouts(markouts, ["hour_et"]).sort_values("avg_60m_pp", ascending=False)
    price = agg_markouts(markouts, ["price_bucket"]).sort_values("avg_60m_pp", ascending=False)
    family = agg_markouts(markouts, ["market_family", "bracket_family"]).sort_values("avg_60m_pp", ascending=False)
    city = agg_markouts(markouts, ["city"]).sort_values("avg_60m_pp", ascending=False)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    markouts.to_parquet(DATA_DIR / "polymarket_alpha_timing.parquet", index=False)
    wallet.to_parquet(DATA_DIR / "polymarket_alpha_timing_wallet_summary.parquet", index=False)

    best = wallet[wallet["trades"] >= 200].head(5)
    worst = wallet[wallet["trades"] >= 200].sort_values("avg_60m_pp").head(5)

    report = [
        "# Polymarket Alpha Timing / Markout Analysis",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "Research-only. Markouts are trade-to-trade within the recent public Data API slice. They are not full orderbook paths, not passive fill truth, and not complete 24-month alpha proof.",
        "",
        "## Data Coverage",
        "",
        f"- Trades analyzed: {len(markouts):,}",
        f"- 60m markout coverage: {pct(markouts['signed_markout_pp_60m'].notna().sum(), len(markouts)):.2f}%",
        f"- 1d markout coverage: {pct(markouts['signed_markout_pp_1d'].notna().sum(), len(markouts)):.2f}%",
        f"- Settlement outcome coverage: {pct(markouts['settlement_return_pp'].notna().sum(), len(markouts)):.2f}%",
        "",
        "## Best Timing Wallets by 60m Signed Markout",
        "",
        md_table(best[["user_name", "provisional_archetype", "trades", "avg_1m_pp", "avg_5m_pp", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]]),
        "",
        "## Worst Timing Wallets by 60m Signed Markout",
        "",
        md_table(worst[["user_name", "provisional_archetype", "trades", "avg_1m_pp", "avg_5m_pp", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]]),
        "",
        "## Timing by ET Hour",
        "",
        md_table(hour[["hour_et", "trades", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]].head(12)),
        "",
        "## Timing by Price Bucket",
        "",
        md_table(price[["price_bucket", "trades", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]]),
        "",
        "## Timing by Market/Bracket Family",
        "",
        md_table(family[["market_family", "bracket_family", "trades", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]].head(20)),
        "",
        "## Interpretation",
        "",
        "- Positive 60m markout means the next observed same-asset trade moved in the wallet's direction.",
        "- Very high activity at extreme prices often produces small markouts but can still matter economically through settlement or ladder netting.",
        "- Wallets with strong 60m markout but weak settlement are likely reactive/tactical rather than pure forecast-alpha traders.",
        "- To distinguish true early alpha from price impact, Phase 4 needs eventual orderbook or subgraph backfill; current results are descriptive.",
    ]
    (REPORT_DIR / "polymarket_alpha_timing.md").write_text("\n".join(report) + "\n")

    print("=== PHASE 4 ALPHA TIMING / MARKOUT ===")
    print(f"Trades analyzed: {len(markouts):,}")
    print(f"60m markout coverage: {pct(markouts['signed_markout_pp_60m'].notna().sum(), len(markouts)):.2f}%")
    print("Best timing wallets by 60m signed markout, min 200 trades:")
    print(best[["user_name", "provisional_archetype", "trades", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]].to_string(index=False))
    print("\nWorst timing wallets by 60m signed markout, min 200 trades:")
    print(worst[["user_name", "provisional_archetype", "trades", "avg_60m_pp", "avg_1d_pp", "settlement_avg_pp"]].to_string(index=False))
    print("\nSaved:")
    print(f"  {DATA_DIR / 'polymarket_alpha_timing.parquet'}")
    print(f"  {DATA_DIR / 'polymarket_alpha_timing_wallet_summary.parquet'}")
    print(f"  {REPORT_DIR / 'polymarket_alpha_timing.md'}")


if __name__ == "__main__":
    main()

