"""Phase 8 cross-venue comparison: Polymarket top wallets vs weather_or_knot."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from polymarket_research_common import DATA_DIR, ET, REPORT_DIR, md_table


def main() -> None:
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    clusters = pd.read_parquet(DATA_DIR / "polymarket_wallet_clusters.parquet")
    selection = pd.read_parquet(DATA_DIR / "polymarket_market_selection_wallet.parquet")
    micro = json.loads((DATA_DIR / "microstructure_atlas_summary.json").read_text()) if (DATA_DIR / "microstructure_atlas_summary.json").exists() else {}
    backtest = json.loads(open("data/backtest_summary.json").read()) if __import__("pathlib").Path("data/backtest_summary.json").exists() else {}

    comparison_rows = [
        {
            "dimension": "entry timing",
            "polymarket_wallet_pattern": "many trades cluster near extreme prices and short event windows; peak hours differ by wallet",
            "our_bot_current": "KXHIGH core uses scheduled 9/11AM style checks and 20pp edge gate",
            "gap": "wallets appear more event/ladder/reactive; bot is forecast-gate driven",
            "actionability": "medium",
        },
        {
            "dimension": "price bucket preference",
            "polymarket_wallet_pattern": f"median extreme-price share across profiled wallets {profiles['extreme_price_trade_pct'].median():.1f}%",
            "our_bot_current": "core price band avoids <25c and >75c; deep-tail NO sleeve exists separately",
            "gap": "top wallets emphasize extreme/ladder behavior more than core bot",
            "actionability": "high for research, medium for paper",
        },
        {
            "dimension": "wings vs central",
            "polymarket_wallet_pattern": "exact-temp/tail ladder behavior dominates recent slice",
            "our_bot_current": "six Kalshi brackets with separate core, TAIL_NO research, DEEP_TAIL_NO paper",
            "gap": "need ladder-aware and bracket-family-aware feature policy",
            "actionability": "high",
        },
        {
            "dimension": "maker/taker tendency",
            "polymarket_wallet_pattern": "not directly observable from API side field",
            "our_bot_current": "maker-only assumption; fill model research shows edge sensitive to cents",
            "gap": "need own unfilled/cancelled order logs for real passive fill model",
            "actionability": "high for logging, low for inference",
        },
        {
            "dimension": "market concentration",
            "polymarket_wallet_pattern": "several wallets highly concentrated in city/event ladders",
            "our_bot_current": "NYC-first, some multi-city config, no grouped ladder optimizer",
            "gap": "bot lacks event-level ladder/net exposure representation",
            "actionability": "medium",
        },
        {
            "dimension": "fill sensitivity",
            "polymarket_wallet_pattern": "public slice cannot reveal missed passive fills",
            "our_bot_current": "backtest stress +3c can destroy core economics",
            "gap": "execution margin should stay paper-only until forward logs validate",
            "actionability": "high",
        },
    ]
    out = pd.DataFrame(comparison_rows)
    out.to_parquet(DATA_DIR / "cross_venue_compare_wallets_vs_bot.parquet", index=False)

    report = [
        "# Cross-Venue Comparison: Polymarket Wallets vs weather_or_knot",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "Research-only. Polymarket and Kalshi differ in station, settlement, fees, bracket topology, and grouped/negative-risk mechanics. This compares behavior patterns, not direct arbitrage or production-ready live changes.",
        "",
        "## Comparison Table",
        "",
        md_table(out, 20),
        "",
        "## Strongest Differences vs Our Bot",
        "",
        "1. Top Polymarket weather wallets in the recent slice are far more extreme-price / ladder oriented than our core KXHIGH forecast-gate strategy.",
        "2. Their behavior appears event-level and grouped-market aware; our bot mostly evaluates brackets independently, even with coherent probability research.",
        "3. Public wallet data does not prove maker/passive execution, while our own Kalshi research says execution quality is decisive.",
        "4. Their repeated same-market activity suggests scale-in/out or ladder adjustment; our paper bot currently logs simpler single-signal entries.",
        "5. Several wallets specialize by city/event; our strategy should keep city and bracket-family separation rather than global policy blending.",
        "",
        "## Top Missing Features",
        "",
        "- Event-level ladder state: total cost, max payoff, covered adjacent buckets, and net exposure by event.",
        "- Extreme-price sleeve diagnostics split into lower tail, upper tail, exact temp, and range.",
        "- Recent same-market flow: repeated buys/sells, wallet-like burst pressure, and local price crowding.",
        "- Proposed/unfilled/cancelled order logs for true maker fill modeling.",
        "- City/station-specific transfer filters for Polymarket patterns before applying to Kalshi.",
    ]
    (REPORT_DIR / "cross_venue_compare_wallets_vs_bot.md").write_text("\n".join(report) + "\n")

    print("=== PHASE 8 CROSS-VENUE COMPARISON ===")
    print(out.to_string(index=False))
    print("\nTop missing features:")
    for item in report[report.index("## Top Missing Features") + 2 :]:
        if item.startswith("- "):
            print(f"  {item}")
    print("\nSaved:")
    print(f"  {DATA_DIR / 'cross_venue_compare_wallets_vs_bot.parquet'}")
    print(f"  {REPORT_DIR / 'cross_venue_compare_wallets_vs_bot.md'}")


if __name__ == "__main__":
    main()

