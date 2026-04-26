# Polymarket Phase 2 Readiness Audit

Generated: 2026-04-26T14:52:13.043069-04:00

## Readiness Verdict

GO for descriptive Phase 3-6 analysis; NO-GO for durable 24-month alpha claims. Current conclusions must be scoped to the API-accessible recent slice.

This is a research-only readiness audit. It does not change live trading, paper trading, thresholds, schedulers, or execution code.

## Scope of Valid Inference

- Valid: recent-slice wallet behavior fingerprints, cadence, sizing distribution, market/event concentration, rough aggressiveness from observed taker trades, and trade-to-trade markout feasibility.
- Partially valid: markout/alpha timing, because prices are observed only at executions in this slice; no full historical orderbook or passive-order queue is present.
- Not valid yet: full 24-month wallet history, exact maker/passive fill probability, true inventory/PnL over time, complete available-market selection baseline, and full cross-venue causal claims.

## Coverage Summary

- Leaderboard wallets: 20
- Wallets with fetched weather trades: 17
- Raw trade rows: 41,709
- Unique markets: 5,327
- Unique events: 1,448
- Timestamp range: 2025-12-08T17:05:53-05:00 to 2026-04-26T13:57:24-04:00 (138.8 days)
- Requested window: 730 days; observed span is 19.0% of that request.
- Wallets reaching public API offset cap: 20/20

## Observability

- Rows with transaction hash: 100.00%
- Rows with outcome metadata row: 100.00%
- Rows with resolved outcome: 69.76%
- Rows with at least one same-market trade context: 96.46%
- Rows with later same-market trade: 87.23%
- Rows with later same-market trade within 60m: 79.52%
- Direct weather rows: 99.97%
- Temperature rows: 99.43%

## Analysis Support Matrix

| Analysis | Status | Confidence | Reason |
| --- | --- | --- | --- |
| wallet_behavior_metrics | supported_recent_slice | medium | 41,709 rows across 17 active wallets are enough for cadence, sizing, concentration, and repeat-trading fingerprints, but all wallets are API-capped. |
| markout_analysis | partially_supported | low_to_medium | Trade-to-trade markouts are possible inside the captured slice, but no full CLOB/orderbook history or unfilled passive orders are available. |
| strategy_clustering | supported_provisional | medium | 17 active wallets support provisional behavioral clusters; sample is too small and capped for stable final taxonomy. |
| market_selection_inference | partially_supported | medium | Chosen-market patterns are visible, but available-market baseline is incomplete unless we build a Gamma weather universe for the same recent window. |
| cross_venue_comparison | supported_descriptive_only | medium | Useful descriptive comparison against Kalshi/Becker research, but Polymarket station, settlement, fee, and grouped-market mechanics differ. |

## Biggest Analytical Blind Spots

1. Public Data API pagination cap means this is a recent slice, not a complete 24-month wallet corpus.
2. Three top-20 leaderboard wallets have zero fetched weather trades in the recent slice, likely because their weather activity is older than the API-accessible window or hidden behind pagination ordering.
3. No historical orderbook snapshots, spread path, queue position, or unfilled passive orders are available from Phase 1 artifacts.
4. Market-selection inference lacks a complete Polymarket weather universe baseline for the exact same timestamps.
5. Polymarket grouped/negative-risk ladder mechanics differ from Kalshi KXHIGHNY, so direct strategy transfer requires care.

## Wallet Coverage Table

| rank | userName | proxyWallet | leaderboardVol | fetchedTradeRows | uniqueMarkets | uniqueEvents | apiCapped | activeInSlice |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | largeleeks888 | 0x57dedd62596dd4f85c7ebe5317e07d22795ecd90 | 12,283,841.02 | 3197 | 752 | 383 | True | True |
| 2 | planktonXD | 0x4ffe49ba2a4cae123536a8af4fda48faeb609f71 | 10,704,532.67 | 76 | 23 | 12 | True | True |
| 3 | aenews2 | 0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1 | 9,972,308.56 | 0 | 0 | 0 | True | False |
| 4 | IsabelaEstrellaPaz | 0x8b761995bbde7278a2f536b415fb5f60815fc036 | 8,976,660.85 | 2016 | 66 | 17 | True | True |
| 5 | ColdMath | 0x594edb9112f526fa6a80b8f858a6379c8a2c1c11 | 8,909,540.13 | 3141 | 111 | 52 | True | True |
| 6 | dpnd | 0x5f211a24da4c005d9438a1ea269673b85ed0b376 | 8,397,979.08 | 3483 | 514 | 99 | True | True |
| 7 | KingZeManel | 0x7bff96579b20fe3530e140d6a3c223c9f2127cd6 | 7,395,578.02 | 3410 | 550 | 227 | True | True |
| 8 | VibeTrader | 0xcbbc5e035504421b084ad9248b660f6e9618b5d0 | 7,073,022.66 | 3499 | 136 | 54 | True | True |
| 9 | TENETENET | 0x3329cfc2b8d8ceb8d198f081bdf4262f421f43a6 | 7,019,431.89 | 2159 | 442 | 134 | True | True |
| 10 | Hans323 | 0x0f37cb80dee49d55b5f6d9e595d52591d6371410 | 6,971,546.61 | 1930 | 277 | 143 | True | True |
| 11 | meropi | 0x9977760c6bd6f824cac834d1a36ee99478d63020 | 6,509,549.77 | 1641 | 138 | 49 | True | True |
| 12 | HondaCivic | 0x15ceffed7bf820cd2d90f90ea24ae9909f5cd5fa | 6,456,192.12 | 3412 | 636 | 299 | True | True |
| 13 | Poligarch | 0xb40e89677d59665d5188541ad860450a6e2a7cc9 | 6,193,817.16 | 3426 | 301 | 77 | True | True |
| 14 | 0x3d3869cf51cf429b5f7f00f5a299f69edb3ce6ed | 0x3d3869cf51cf429b5f7f00f5a299f69edb3ce6ed | 5,949,260.94 | 0 | 0 | 0 | True | False |
| 15 | 0x04011eeb35d62f9cc002b600c5ad83378c6d2bbc | 0x04011eeb35d62f9cc002b600c5ad83378c6d2bbc | 5,949,047.29 | 0 | 0 | 0 | True | False |
| 16 | OraculumNobius | 0xd25b8718f61fb64a754356ad8cf16b5579f59f3d | 5,712,895.60 | 1477 | 257 | 157 | True | True |
| 17 | oVyg7f | 0x5f390e4b7d6f06d6756a6c92afdbf7b3176aa78c | 5,697,984.91 | 2363 | 789 | 100 | True | True |
| 18 | cry.eth2 | 0xe3726a1b9c6ba2f06585d1c9e01d00afaedaeb38 | 5,673,606.61 | 141 | 28 | 10 | True | True |
| 19 | NoonienSoong | 0x38cc1d1f95d12039324809d8bb6ca6da6cbef88e | 5,515,280.27 | 3298 | 830 | 495 | True | True |
| 20 | Dreamer3bcbcd6c | 0xd28021317c1be36239e8d930dee7d6c3a40082b3 | 5,251,340.72 | 3040 | 586 | 268 | True | True |

## Phase 3 Recommendation

Proceed to wallet behavioral profiles, but label every conclusion as recent-slice evidence. Add subgraph/on-chain backfill before making claims about full 24-month trader behavior or durable edge.
