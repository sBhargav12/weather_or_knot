# Polymarket Wallet Strategy Implications

Generated: 2026-04-26T15:08:35.409666-04:00

## Scope

Research-only. Recommendations are based on the recent API-accessible Polymarket slice plus existing weather_or_knot research. They are not live approvals.

## Ranked Recommendations

| rank | bucket | description | evidence | repo_mapping | expected_impact | difficulty | evidence_strength |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Feature engineering | Add event-level ladder state features: number of adjacent brackets touched, total ladder cost, max payoff, net event exposure, and uncovered gap distance. | Top wallets are dominated by exact-temp/range grouped ladders; median extreme-price share is 96.4%, and repeated-market rates are high. | Extend research mart/features before live use; eventually add paper candidate diagnostics. | Win rate neutral-to-positive; Sharpe positive through better exposure selection; fill quality unchanged directly. | medium | medium_recent_slice |
| 2 | Execution logic | Keep execution-margin filters paper-only and expand logging for proposed, unfilled, cancelled, and filled orders. | Becker/Kalshi stress tests show core edge can vanish under +3c; Polymarket public data cannot reveal passive fills. | paper_trader policy/reporting plus future order lifecycle log table. | Sharpe and drawdown improvement; win rate may fall from fewer trades. | medium | high_for_logging |
| 3 | Market selection | Split central, range, exact-temp/tail, lower-tail, and upper-tail policy instead of using one bracket-family threshold. | Profiles and selection show bracket family dominates behavior; prior KXHIGH research also showed wings easier than central. | features/bracket_targets.py, config_paper.py, paper_trader/policy.py. | Win rate positive if central trades are tightened; EV positive if tail sleeves are isolated. | low_to_medium | medium_high |
| 4 | Risk sizing | Represent event-level correlated exposure before scaling any sleeve. | Same-event ladder p95 market counts are high for several wallets; our bot currently reasons mostly per market. | new research exposure table; future paper-trader event exposure cap. | Drawdown reduction; Sharpe positive; raw win rate unchanged. | medium | medium |
| 5 | Pipeline / workflow | Backfill Polymarket subgraph/on-chain trades before making 24-month claims. | Phase 2 observed only 138.8 days and all wallets hit the Data API cap. | new research ingestion module, not live code. | Research reliability improvement, not immediate trading PnL. | medium_high | high |
| 6 | Execution logic | Study selective taker behavior only after orderbook or own-order logs exist. | Polymarket side field is wallet action, not maker/taker truth. | do not alter live maker-only assumption yet. | Avoids false execution conclusions. | low | high_constraint |
| 7 | Feature engineering | Add recent same-market flow and burst pressure features. | 96.5% of rows have same-market trade context and 79.5% have later same-market trade within 60m. | weather_mart / Kalshi price_history features. | Potential win-rate and timing improvement; needs forward validation. | medium | medium |
| 8 | Market selection | Do not directly port Polymarket NYC behavior to KXHIGHNY without station/settlement conversion. | Polymarket grouped weather often uses airport/Wunderground-like sources; Kalshi KXHIGHNY uses KNYC CLI. | cross-venue guardrails in research docs and feature maps. | Reduces false signals and cross-venue overfitting. | low | high |
