"""Write Phase 9-11 strategy implication reports from completed wallet research."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

from polymarket_research_common import DATA_DIR, ET, REPORT_DIR, md_table


def git_diff_stat() -> str:
    try:
        return subprocess.check_output(["git", "diff", "--stat", "HEAD"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return "git diff unavailable"


def main() -> None:
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    timing = pd.read_parquet(DATA_DIR / "polymarket_alpha_timing_wallet_summary.parquet")
    selection = pd.read_parquet(DATA_DIR / "polymarket_market_selection_wallet.parquet")
    risk = pd.read_parquet(DATA_DIR / "polymarket_risk_efficiency.parquet")
    clusters = pd.read_parquet(DATA_DIR / "polymarket_wallet_clusters.parquet")
    readiness = json.loads((DATA_DIR / "polymarket_phase2_readiness.json").read_text())
    generated = datetime.now(tz=ET).isoformat()

    recommendations = [
        {
            "rank": 1,
            "bucket": "Feature engineering",
            "description": "Add event-level ladder state features: number of adjacent brackets touched, total ladder cost, max payoff, net event exposure, and uncovered gap distance.",
            "evidence": "Top wallets are dominated by exact-temp/range grouped ladders; median extreme-price share is 96.4%, and repeated-market rates are high.",
            "repo_mapping": "Extend research mart/features before live use; eventually add paper candidate diagnostics.",
            "expected_impact": "Win rate neutral-to-positive; Sharpe positive through better exposure selection; fill quality unchanged directly.",
            "difficulty": "medium",
            "evidence_strength": "medium_recent_slice",
        },
        {
            "rank": 2,
            "bucket": "Execution logic",
            "description": "Keep execution-margin filters paper-only and expand logging for proposed, unfilled, cancelled, and filled orders.",
            "evidence": "Becker/Kalshi stress tests show core edge can vanish under +3c; Polymarket public data cannot reveal passive fills.",
            "repo_mapping": "paper_trader policy/reporting plus future order lifecycle log table.",
            "expected_impact": "Sharpe and drawdown improvement; win rate may fall from fewer trades.",
            "difficulty": "medium",
            "evidence_strength": "high_for_logging",
        },
        {
            "rank": 3,
            "bucket": "Market selection",
            "description": "Split central, range, exact-temp/tail, lower-tail, and upper-tail policy instead of using one bracket-family threshold.",
            "evidence": "Profiles and selection show bracket family dominates behavior; prior KXHIGH research also showed wings easier than central.",
            "repo_mapping": "features/bracket_targets.py, config_paper.py, paper_trader/policy.py.",
            "expected_impact": "Win rate positive if central trades are tightened; EV positive if tail sleeves are isolated.",
            "difficulty": "low_to_medium",
            "evidence_strength": "medium_high",
        },
        {
            "rank": 4,
            "bucket": "Risk sizing",
            "description": "Represent event-level correlated exposure before scaling any sleeve.",
            "evidence": "Same-event ladder p95 market counts are high for several wallets; our bot currently reasons mostly per market.",
            "repo_mapping": "new research exposure table; future paper-trader event exposure cap.",
            "expected_impact": "Drawdown reduction; Sharpe positive; raw win rate unchanged.",
            "difficulty": "medium",
            "evidence_strength": "medium",
        },
        {
            "rank": 5,
            "bucket": "Pipeline / workflow",
            "description": "Backfill Polymarket subgraph/on-chain trades before making 24-month claims.",
            "evidence": "Phase 2 observed only 138.8 days and all wallets hit the Data API cap.",
            "repo_mapping": "new research ingestion module, not live code.",
            "expected_impact": "Research reliability improvement, not immediate trading PnL.",
            "difficulty": "medium_high",
            "evidence_strength": "high",
        },
        {
            "rank": 6,
            "bucket": "Execution logic",
            "description": "Study selective taker behavior only after orderbook or own-order logs exist.",
            "evidence": "Polymarket side field is wallet action, not maker/taker truth.",
            "repo_mapping": "do not alter live maker-only assumption yet.",
            "expected_impact": "Avoids false execution conclusions.",
            "difficulty": "low",
            "evidence_strength": "high_constraint",
        },
        {
            "rank": 7,
            "bucket": "Feature engineering",
            "description": "Add recent same-market flow and burst pressure features.",
            "evidence": "96.5% of rows have same-market trade context and 79.5% have later same-market trade within 60m.",
            "repo_mapping": "weather_mart / Kalshi price_history features.",
            "expected_impact": "Potential win-rate and timing improvement; needs forward validation.",
            "difficulty": "medium",
            "evidence_strength": "medium",
        },
        {
            "rank": 8,
            "bucket": "Market selection",
            "description": "Do not directly port Polymarket NYC behavior to KXHIGHNY without station/settlement conversion.",
            "evidence": "Polymarket grouped weather often uses airport/Wunderground-like sources; Kalshi KXHIGHNY uses KNYC CLI.",
            "repo_mapping": "cross-venue guardrails in research docs and feature maps.",
            "expected_impact": "Reduces false signals and cross-venue overfitting.",
            "difficulty": "low",
            "evidence_strength": "high",
        },
    ]

    imp_lines = [
        "# Polymarket Wallet Strategy Implications",
        "",
        f"Generated: {generated}",
        "",
        "## Scope",
        "",
        "Research-only. Recommendations are based on the recent API-accessible Polymarket slice plus existing weather_or_knot research. They are not live approvals.",
        "",
        "## Ranked Recommendations",
        "",
        md_table(pd.DataFrame(recommendations), 20),
    ]
    (REPORT_DIR / "polymarket_wallet_strategy_implications.md").write_text("\n".join(imp_lines) + "\n")

    playbook = [
        "# Win-Rate Improvement Playbook",
        "",
        f"Generated: {generated}",
        "",
        "## Immediate",
        "",
        "1. Keep live threshold frozen; do not promote wallet-derived changes directly to live.",
        "2. Add research/paper diagnostics for event-level ladder state and bracket-family split.",
        "3. Keep TAIL_NO suspended in paper until stricter evidence exists; continue logging candidates.",
        "4. Preserve execution-margin paper filters; core is fragile under fill stress.",
        "",
        "## Next Sprint",
        "",
        "1. Add Polymarket subgraph/on-chain backfill to escape the public API cap.",
        "2. Build available-market universe baseline for true selection edge.",
        "3. Add Kalshi paper logs for proposed/unfilled/cancelled orders.",
        "4. Add recent same-market flow features to research mart.",
        "",
        "## Medium-Term",
        "",
        "1. Build event-level exposure accounting for grouped/ladder-like structures.",
        "2. Split calibration/policy for central vs wing/exact/tail structures.",
        "3. Validate whether extreme-price behavior improves EV on Kalshi after fees and fill stress.",
        "",
        "## Future Paper/Live Candidate",
        "",
        "1. A ladder-aware deep-tail/wing sleeve may be a paper candidate after backfilled evidence and own fill logs.",
        "2. Selective central tightening may improve win rate if forward paper confirms central underperformance.",
        "",
        "## What NOT To Change Yet",
        "",
        "- Do not change live threshold.",
        "- Do not touch live execution or scheduler.",
        "- Do not claim exact maker/taker patterns from Polymarket public trades.",
        "- Do not copy Polymarket station-specific behavior into KXHIGHNY without station conversion.",
    ]
    (REPORT_DIR / "win_rate_improvement_playbook.md").write_text("\n".join(playbook) + "\n")

    top_insights = [
        "Recent top-wallet activity is dominated by daily temperature ladders, not broad weather.",
        "Extreme-price trades are the strongest descriptive fingerprint.",
        "Repeat-market concentration suggests ladder management or scale-in/out behavior.",
        "Maker/taker truth is not recoverable from the public side field.",
        "The current slice is only 138.8 days, not 24 months.",
        "Several leaderboard wallets have no recent weather trades in the fetched slice.",
        "Exact-temp Polymarket structures do not map directly to Kalshi six-bracket KXHIGH markets.",
        "Execution stress remains the largest transfer risk for our bot.",
        "Event-level exposure is a missing abstraction in our pipeline.",
        "Own order lifecycle logs are the key missing execution dataset.",
        "Wallet clusters separate into extreme-price NO/expiry specialists, ladder optimizers, and thin/unclear wallets.",
        "Phase 4 markouts are useful but contaminated by near-resolution extreme-price dynamics.",
        "Wings/exact/tails likely need different policies than central ranges.",
        "Market-selection claims need a Gamma universe baseline.",
        "Cross-venue comparisons are descriptive, not arbitrage signals.",
        "Deep-tail behavior remains promising but fill-sensitive.",
        "Core forecast-gate strategy is structurally different from top Polymarket wallet behavior.",
        "Polymarket grouped-market mechanics may explain much of the ladder behavior.",
        "Large notional-per-day wallets are not necessarily the same as best timing wallets.",
        "Research should proceed toward backfill, event exposure, and execution logs before live changes.",
    ]

    repo_changes = [
        "Add event-level exposure and ladder-state feature builder.",
        "Add available-market universe collector for Polymarket weather.",
        "Add own-order lifecycle logging for paper/live proposed orders.",
        "Split bracket-family policy and reporting further.",
        "Add recent same-market flow features to Kalshi weather mart.",
        "Build station-mapping guardrails for Polymarket-vs-Kalshi transfer.",
        "Keep execution margin filters paper-only until forward validation.",
        "Backfill Polymarket history through subgraph/on-chain sources.",
        "Add cluster/archetype labels as research features only.",
        "Create promotion checklist from descriptive wallet evidence to paper candidate.",
    ]

    final = {
        "generated_at_et": generated,
        "scope": readiness["decision"]["verdict"],
        "wallet_profile_rows": int(len(profiles)),
        "cluster_rows": int(len(clusters)),
        "top_20_actionable_insights": top_insights,
        "top_10_repo_pipeline_changes": repo_changes,
        "top_5_win_rate_candidates": [
            "Tighten/segment central bracket policy separately from wings/tails.",
            "Add event-level ladder exposure so overlapping bracket risk is explicit.",
            "Use recent flow/burst features to avoid crowded or stale entries.",
            "Require execution-margin survival before paper entries.",
            "Backfill and validate extreme-price sleeve behavior before promotion.",
        ],
        "top_5_sharpe_execution_candidates": [
            "Log proposed/unfilled/cancelled order lifecycle.",
            "Keep maker-first but measure real fill probability.",
            "Use event exposure caps to reduce correlated drawdown.",
            "Stress-test every sleeve by bracket family and price bucket.",
            "Avoid direct cross-venue transfer without settlement/station adjustment.",
        ],
        "biggest_unknowns": [
            "Complete 24-month wallet history.",
            "Exact maker/passive fill status.",
            "Unfilled order and queue-position behavior.",
            "Full available-market universe baseline.",
            "Whether Polymarket ladder behavior survives Kalshi fee/fill/bracket differences.",
        ],
        "evidence_quality": {
            "observed": ["public trades, prices, sizes, timestamps, transaction hashes, market outcomes for closed markets"],
            "inferred": ["archetypes, ladder usage proxies, capital recycling proxies, trade-to-trade markouts"],
            "unobservable": ["passive fill probability, queue position, full inventory path, complete 24-month behavior"],
        },
        "files_created": [
            "research/polymarket_research_common.py",
            "research/polymarket_alpha_timing.py",
            "research/polymarket_market_selection_edge.py",
            "research/polymarket_risk_efficiency.py",
            "research/polymarket_wallet_clustering.py",
            "research/cross_venue_compare_wallets_vs_bot.py",
            "research/polymarket_write_strategy_reports.py",
            "reports/polymarket_alpha_timing.md",
            "reports/polymarket_market_selection_edge.md",
            "reports/polymarket_risk_efficiency.md",
            "reports/polymarket_wallet_clusters.md",
            "reports/cross_venue_compare_wallets_vs_bot.md",
            "reports/polymarket_wallet_strategy_implications.md",
            "reports/win_rate_improvement_playbook.md",
            "reports/final_top_wallet_weather_strategy_report.md",
            "reports/final_top_wallet_weather_strategy_report.json",
        ],
        "git_diff_stat": git_diff_stat(),
    }
    (REPORT_DIR / "final_top_wallet_weather_strategy_report.json").write_text(json.dumps(final, indent=2) + "\n")

    final_md = [
        "# Final Top-Wallet Weather Strategy Report",
        "",
        f"Generated: {generated}",
        "",
        "## Executive Summary",
        "",
        "The recent public Polymarket slice shows top weather wallets behaving very differently from the current KXHIGHNY core bot: they are heavily concentrated in daily temperature ladders, extreme-price contracts, repeated same-event trading, and near-resolution/tail-like behavior. This is useful research signal, but not durable 24-month alpha proof because the public Data API caps history and maker/passive execution is not observable.",
        "",
        "## Wallet Profile Table",
        "",
        md_table(profiles[["leaderboard_rank", "user_name", "provisional_archetype", "trade_count", "active_days", "market_count", "event_count", "extreme_price_trade_pct", "repeat_market_rate_pct"]].sort_values("leaderboard_rank"), 30),
        "",
        "## Wallet Cluster Table",
        "",
        md_table(clusters[["user_name", "cluster_label", "cluster_confidence", "trade_count", "extreme_price_trade_pct", "repeat_market_rate_pct"]].sort_values("cluster_label"), 30),
        "",
        "## Top 20 Actionable Insights",
        "",
        *[f"{i}. {x}" for i, x in enumerate(top_insights, 1)],
        "",
        "## Top 10 Repo/Pipeline Changes",
        "",
        *[f"{i}. {x}" for i, x in enumerate(repo_changes, 1)],
        "",
        "## Top 5 Changes Most Likely To Improve Win Rate",
        "",
        *[f"{i}. {x}" for i, x in enumerate(final["top_5_win_rate_candidates"], 1)],
        "",
        "## Top 5 Changes Most Likely To Improve Sharpe / Execution Quality",
        "",
        *[f"{i}. {x}" for i, x in enumerate(final["top_5_sharpe_execution_candidates"], 1)],
        "",
        "## Biggest Unknowns / Blind Spots",
        "",
        *[f"- {x}" for x in final["biggest_unknowns"]],
        "",
        "## Evidence Quality Notes",
        "",
        "- Observed: public trades, prices, sizes, timestamps, transaction hashes, and closed-market outcomes.",
        "- Inferred: wallet archetypes, ladder usage, capital recycling, and trade-to-trade markout style.",
        "- Not recoverable from this slice: true passive maker fills, unfilled orders, queue position, complete inventory path, and complete 24-month behavior.",
        "",
        "## Exact Files Created",
        "",
        *[f"- `{x}`" for x in final["files_created"]],
        "",
        "## git diff --stat HEAD",
        "",
        "```text",
        final["git_diff_stat"],
        "```",
    ]
    (REPORT_DIR / "final_top_wallet_weather_strategy_report.md").write_text("\n".join(final_md) + "\n")

    print("=== PHASE 9 STRATEGY IMPLICATIONS ===")
    print(pd.DataFrame(recommendations)[["rank", "bucket", "description", "evidence_strength"]].to_string(index=False))
    print("\n=== PHASE 10 WIN-RATE PLAYBOOK ===")
    print("\n".join(playbook[:32]))
    print("\n=== PHASE 11 FINAL REPORT ===")
    print("Top 5 win-rate candidates:")
    for x in final["top_5_win_rate_candidates"]:
        print(f"  - {x}")
    print("Top 5 Sharpe/execution candidates:")
    for x in final["top_5_sharpe_execution_candidates"]:
        print(f"  - {x}")
    print("\nSaved:")
    print(f"  {REPORT_DIR / 'polymarket_wallet_strategy_implications.md'}")
    print(f"  {REPORT_DIR / 'win_rate_improvement_playbook.md'}")
    print(f"  {REPORT_DIR / 'final_top_wallet_weather_strategy_report.md'}")
    print(f"  {REPORT_DIR / 'final_top_wallet_weather_strategy_report.json'}")


if __name__ == "__main__":
    main()

