"""Phase 6 risk and capital-efficiency proxies for Polymarket weather wallets."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from polymarket_research_common import DATA_DIR, ET, REPORT_DIR, enriched_trades, md_table, pct


def gini(values: pd.Series) -> float:
    x = np.sort(values.dropna().to_numpy(dtype=float))
    if len(x) == 0 or x.sum() == 0:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) @ x) / (n * x.sum()) - (n + 1) / n)


def wallet_risk(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wallet, g in df.groupby("proxyWallet"):
        event_notional = g.groupby("eventSlug")["notional_usd_proxy"].sum()
        market_notional = g.groupby("conditionId")["notional_usd_proxy"].sum()
        daily_notional = g.groupby("date_et")["notional_usd_proxy"].sum()
        concurrent_proxy = g.groupby("date_et")["conditionId"].nunique().max()
        same_event_ladder = g.groupby("eventSlug")["conditionId"].nunique()
        repeated = g.groupby("conditionId").size()
        rows.append(
            {
                "wallet": wallet,
                "user_name": g["leaderboard_username"].iloc[0],
                "trades": len(g),
                "active_days": g["date_et"].nunique(),
                "turnover_notional_proxy": g["notional_usd_proxy"].sum(),
                "notional_per_active_day": g["notional_usd_proxy"].sum() / max(g["date_et"].nunique(), 1),
                "median_trade_notional": g["notional_usd_proxy"].median(),
                "p95_trade_notional": g["notional_usd_proxy"].quantile(0.95),
                "trade_notional_gini": gini(g["notional_usd_proxy"]),
                "event_notional_gini": gini(event_notional),
                "market_notional_gini": gini(market_notional),
                "top_event_notional_share_pct": pct(event_notional.max(), event_notional.sum()),
                "top_market_notional_share_pct": pct(market_notional.max(), market_notional.sum()),
                "max_concurrent_market_count_proxy": int(concurrent_proxy),
                "same_event_ladder_median_markets": float(same_event_ladder.median()),
                "same_event_ladder_p95_markets": float(same_event_ladder.quantile(0.95)),
                "repeat_trade_market_share_pct": pct(repeated.gt(1).sum(), repeated.count()),
                "scale_in_out_proxy_pct": pct(
                    g.groupby("conditionId").apply(lambda x: x["side"].nunique() > 1, include_groups=False).sum(),
                    g["conditionId"].nunique(),
                ),
                "resolved_avg_return_pp": g["settlement_return_pp"].mean(),
                "resolved_pnl_proxy": g["settlement_pnl_proxy"].sum(),
                "observability_note": "inventory/concurrency estimated from observed trades only",
            }
        )
    return pd.DataFrame(rows).sort_values("turnover_notional_proxy", ascending=False)


def main() -> None:
    t = enriched_trades()
    risk = wallet_risk(t)
    risk.to_parquet(DATA_DIR / "polymarket_risk_efficiency.parquet", index=False)

    capital = risk.sort_values("notional_per_active_day", ascending=False).head(8)
    concentration = risk.sort_values("top_event_notional_share_pct", ascending=False).head(8)
    ladder = risk.sort_values("same_event_ladder_p95_markets", ascending=False).head(8)

    report = [
        "# Polymarket Risk and Capital Efficiency",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "Research-only. Capital efficiency is inferred from observed public executions only. True inventory, collateral usage, unfilled orders, netting, split/merge/redeem, and drawdown are partially or fully unobservable.",
        "",
        "## Strongest Capital Recycling Proxies",
        "",
        md_table(capital[["user_name", "trades", "active_days", "turnover_notional_proxy", "notional_per_active_day", "max_concurrent_market_count_proxy"]]),
        "",
        "## Concentration Proxies",
        "",
        md_table(concentration[["user_name", "top_event_notional_share_pct", "top_market_notional_share_pct", "event_notional_gini", "market_notional_gini"]]),
        "",
        "## Ladder Usage Proxies",
        "",
        md_table(ladder[["user_name", "same_event_ladder_median_markets", "same_event_ladder_p95_markets", "repeat_trade_market_share_pct", "scale_in_out_proxy_pct"]]),
        "",
        "## Observed / Estimated / Unobservable",
        "",
        "- Observed: trade size, trade price, event/market concentration, repeated market activity, same-event multi-market usage.",
        "- Estimated: capital recycling speed, max concurrent market count, scale-in/scale-out behavior, ladder intensity.",
        "- Unobservable: true wallet inventory path, passive order miss rate, queue position, collateral usage, complete PnL path, redeem/split behavior if not exposed by this API slice.",
    ]
    (REPORT_DIR / "polymarket_risk_efficiency.md").write_text("\n".join(report) + "\n")

    print("=== PHASE 6 RISK / CAPITAL EFFICIENCY ===")
    print("Strongest capital-efficiency wallets by notional per active day:")
    print(capital[["user_name", "trades", "active_days", "turnover_notional_proxy", "notional_per_active_day", "max_concurrent_market_count_proxy"]].to_string(index=False))
    print("\nLadder usage proxy leaders:")
    print(ladder[["user_name", "same_event_ladder_median_markets", "same_event_ladder_p95_markets", "repeat_trade_market_share_pct", "scale_in_out_proxy_pct"]].to_string(index=False))
    print("\nSaved:")
    print(f"  {DATA_DIR / 'polymarket_risk_efficiency.parquet'}")
    print(f"  {REPORT_DIR / 'polymarket_risk_efficiency.md'}")


if __name__ == "__main__":
    main()

