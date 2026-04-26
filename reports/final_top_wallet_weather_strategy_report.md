# Final Top-Wallet Weather Strategy Report

Generated: 2026-04-26T15:08:35.409666-04:00

## Executive Summary

The recent public Polymarket slice shows top weather wallets behaving very differently from the current KXHIGHNY core bot: they are heavily concentrated in daily temperature ladders, extreme-price contracts, repeated same-event trading, and near-resolution/tail-like behavior. This is useful research signal, but not durable 24-month alpha proof because the public Data API caps history and maker/passive execution is not observable.

## Wallet Profile Table

| leaderboard_rank | user_name | provisional_archetype | trade_count | active_days | market_count | event_count | extreme_price_trade_pct | repeat_market_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | largeleeks888 | expiry / resolution specialist | 3197 | 20 | 752 | 383 | 98.78010634970285 | 62.101063829787236 |
| 2 | planktonXD | mixed / unclear | 76 | 4 | 23 | 12 | 32.89473684210526 | 56.52173913043478 |
| 4 | IsabelaEstrellaPaz | ladder optimizer | 2016 | 2 | 66 | 17 | 100.0 | 92.42424242424242 |
| 5 | ColdMath | ladder optimizer | 3141 | 3 | 111 | 52 | 94.14199299586119 | 66.66666666666667 |
| 6 | dpnd | ladder optimizer | 3483 | 1 | 514 | 99 | 69.25064599483204 | 79.76653696498055 |
| 7 | KingZeManel | ladder optimizer | 3410 | 8 | 550 | 227 | 100.0 | 75.81818181818181 |
| 8 | VibeTrader | ladder optimizer | 3499 | 7 | 136 | 54 | 59.6741926264647 | 78.67647058823529 |
| 9 | TENETENET | ladder optimizer | 2159 | 2 | 442 | 134 | 100.0 | 52.036199095022624 |
| 10 | Hans323 | ladder optimizer | 1930 | 71 | 277 | 143 | 92.90155440414507 | 81.5884476534296 |
| 11 | meropi | expiry / resolution specialist | 1641 | 10 | 138 | 49 | 97.50152346130409 | 91.30434782608695 |
| 12 | HondaCivic | expiry / resolution specialist | 3412 | 18 | 636 | 299 | 96.42438452520516 | 68.71069182389937 |
| 13 | Poligarch | mixed / unclear | 3426 | 1 | 301 | 77 | 17.775831873905428 | 80.39867109634551 |
| 16 | OraculumNobius | expiry / resolution specialist | 1477 | 9 | 257 | 157 | 99.8645903859174 | 68.09338521400778 |
| 17 | oVyg7f | ladder optimizer | 2363 | 4 | 789 | 100 | 76.42826914938637 | 53.48542458808618 |
| 18 | cry.eth2 | mixed / unclear | 141 | 1 | 28 | 10 | 88.65248226950355 | 42.857142857142854 |
| 19 | NoonienSoong | expiry / resolution specialist | 3298 | 62 | 830 | 495 | 97.66525166767738 | 53.25301204819277 |
| 20 | Dreamer3bcbcd6c | expiry / resolution specialist | 3040 | 10 | 586 | 268 | 99.70394736842105 | 76.27986348122867 |

## Wallet Cluster Table

| user_name | cluster_label | cluster_confidence | trade_count | extreme_price_trade_pct | repeat_market_rate_pct |
| --- | --- | --- | --- | --- | --- |
| largeleeks888 | extreme-price NO / expiry specialists | low | 3197 | 98.78010634970285 | 62.101063829787236 |
| OraculumNobius | extreme-price NO / expiry specialists | low | 1477 | 99.8645903859174 | 68.09338521400778 |
| HondaCivic | extreme-price NO / expiry specialists | low | 3412 | 96.42438452520516 | 68.71069182389937 |
| meropi | extreme-price NO / expiry specialists | low | 1641 | 97.50152346130409 | 91.30434782608695 |
| NoonienSoong | extreme-price NO / expiry specialists | low | 3298 | 97.66525166767738 | 53.25301204819277 |
| Hans323 | extreme-price NO / expiry specialists | low | 1930 | 92.90155440414507 | 81.5884476534296 |
| KingZeManel | extreme-price NO / expiry specialists | low | 3410 | 100.0 | 75.81818181818181 |
| Dreamer3bcbcd6c | extreme-price NO / expiry specialists | low | 3040 | 99.70394736842105 | 76.27986348122867 |
| VibeTrader | temperature ladder optimizers | low | 3499 | 59.6741926264647 | 78.67647058823529 |
| TENETENET | temperature ladder optimizers | low | 2159 | 100.0 | 52.036199095022624 |
| dpnd | temperature ladder optimizers | low | 3483 | 69.25064599483204 | 79.76653696498055 |
| ColdMath | temperature ladder optimizers | low | 3141 | 94.14199299586119 | 66.66666666666667 |
| IsabelaEstrellaPaz | temperature ladder optimizers | low | 2016 | 100.0 | 92.42424242424242 |
| Poligarch | temperature ladder optimizers | low | 3426 | 17.775831873905428 | 80.39867109634551 |
| oVyg7f | temperature ladder optimizers | low | 2363 | 76.42826914938637 | 53.48542458808618 |
| planktonXD | thin recent-slice / unclear | medium | 76 | 32.89473684210526 | 56.52173913043478 |
| cry.eth2 | thin recent-slice / unclear | medium | 141 | 88.65248226950355 | 42.857142857142854 |

## Top 20 Actionable Insights

1. Recent top-wallet activity is dominated by daily temperature ladders, not broad weather.
2. Extreme-price trades are the strongest descriptive fingerprint.
3. Repeat-market concentration suggests ladder management or scale-in/out behavior.
4. Maker/taker truth is not recoverable from the public side field.
5. The current slice is only 138.8 days, not 24 months.
6. Several leaderboard wallets have no recent weather trades in the fetched slice.
7. Exact-temp Polymarket structures do not map directly to Kalshi six-bracket KXHIGH markets.
8. Execution stress remains the largest transfer risk for our bot.
9. Event-level exposure is a missing abstraction in our pipeline.
10. Own order lifecycle logs are the key missing execution dataset.
11. Wallet clusters separate into extreme-price NO/expiry specialists, ladder optimizers, and thin/unclear wallets.
12. Phase 4 markouts are useful but contaminated by near-resolution extreme-price dynamics.
13. Wings/exact/tails likely need different policies than central ranges.
14. Market-selection claims need a Gamma universe baseline.
15. Cross-venue comparisons are descriptive, not arbitrage signals.
16. Deep-tail behavior remains promising but fill-sensitive.
17. Core forecast-gate strategy is structurally different from top Polymarket wallet behavior.
18. Polymarket grouped-market mechanics may explain much of the ladder behavior.
19. Large notional-per-day wallets are not necessarily the same as best timing wallets.
20. Research should proceed toward backfill, event exposure, and execution logs before live changes.

## Top 10 Repo/Pipeline Changes

1. Add event-level exposure and ladder-state feature builder.
2. Add available-market universe collector for Polymarket weather.
3. Add own-order lifecycle logging for paper/live proposed orders.
4. Split bracket-family policy and reporting further.
5. Add recent same-market flow features to Kalshi weather mart.
6. Build station-mapping guardrails for Polymarket-vs-Kalshi transfer.
7. Keep execution margin filters paper-only until forward validation.
8. Backfill Polymarket history through subgraph/on-chain sources.
9. Add cluster/archetype labels as research features only.
10. Create promotion checklist from descriptive wallet evidence to paper candidate.

## Top 5 Changes Most Likely To Improve Win Rate

1. Tighten/segment central bracket policy separately from wings/tails.
2. Add event-level ladder exposure so overlapping bracket risk is explicit.
3. Use recent flow/burst features to avoid crowded or stale entries.
4. Require execution-margin survival before paper entries.
5. Backfill and validate extreme-price sleeve behavior before promotion.

## Top 5 Changes Most Likely To Improve Sharpe / Execution Quality

1. Log proposed/unfilled/cancelled order lifecycle.
2. Keep maker-first but measure real fill probability.
3. Use event exposure caps to reduce correlated drawdown.
4. Stress-test every sleeve by bracket family and price bucket.
5. Avoid direct cross-venue transfer without settlement/station adjustment.

## Biggest Unknowns / Blind Spots

- Complete 24-month wallet history.
- Exact maker/passive fill status.
- Unfilled order and queue-position behavior.
- Full available-market universe baseline.
- Whether Polymarket ladder behavior survives Kalshi fee/fill/bracket differences.

## Evidence Quality Notes

- Observed: public trades, prices, sizes, timestamps, transaction hashes, and closed-market outcomes.
- Inferred: wallet archetypes, ladder usage, capital recycling, and trade-to-trade markout style.
- Not recoverable from this slice: true passive maker fills, unfilled orders, queue position, complete inventory path, and complete 24-month behavior.

## Exact Files Created

- `research/polymarket_research_common.py`
- `research/polymarket_alpha_timing.py`
- `research/polymarket_market_selection_edge.py`
- `research/polymarket_risk_efficiency.py`
- `research/polymarket_wallet_clustering.py`
- `research/cross_venue_compare_wallets_vs_bot.py`
- `research/polymarket_write_strategy_reports.py`
- `reports/polymarket_alpha_timing.md`
- `reports/polymarket_market_selection_edge.md`
- `reports/polymarket_risk_efficiency.md`
- `reports/polymarket_wallet_clusters.md`
- `reports/cross_venue_compare_wallets_vs_bot.md`
- `reports/polymarket_wallet_strategy_implications.md`
- `reports/win_rate_improvement_playbook.md`
- `reports/final_top_wallet_weather_strategy_report.md`
- `reports/final_top_wallet_weather_strategy_report.json`

## git diff --stat HEAD

```text
 CLAUDE.md            |   77 ++
 logs/launchd.out.log | 2637 ++++++++++++++++++++++++++++++++++++++++++++++++++
 logs/pipeline.log    | 2637 ++++++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 5351 insertions(+)

```
