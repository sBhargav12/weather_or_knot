# Cross-Venue Comparison: Polymarket Wallets vs weather_or_knot

Generated: 2026-04-26T15:07:06.844912-04:00

## Scope

Research-only. Polymarket and Kalshi differ in station, settlement, fees, bracket topology, and grouped/negative-risk mechanics. This compares behavior patterns, not direct arbitrage or production-ready live changes.

## Comparison Table

| dimension | polymarket_wallet_pattern | our_bot_current | gap | actionability |
| --- | --- | --- | --- | --- |
| entry timing | many trades cluster near extreme prices and short event windows; peak hours differ by wallet | KXHIGH core uses scheduled 9/11AM style checks and 20pp edge gate | wallets appear more event/ladder/reactive; bot is forecast-gate driven | medium |
| price bucket preference | median extreme-price share across profiled wallets 96.4% | core price band avoids <25c and >75c; deep-tail NO sleeve exists separately | top wallets emphasize extreme/ladder behavior more than core bot | high for research, medium for paper |
| wings vs central | exact-temp/tail ladder behavior dominates recent slice | six Kalshi brackets with separate core, TAIL_NO research, DEEP_TAIL_NO paper | need ladder-aware and bracket-family-aware feature policy | high |
| maker/taker tendency | not directly observable from API side field | maker-only assumption; fill model research shows edge sensitive to cents | need own unfilled/cancelled order logs for real passive fill model | high for logging, low for inference |
| market concentration | several wallets highly concentrated in city/event ladders | NYC-first, some multi-city config, no grouped ladder optimizer | bot lacks event-level ladder/net exposure representation | medium |
| fill sensitivity | public slice cannot reveal missed passive fills | backtest stress +3c can destroy core economics | execution margin should stay paper-only until forward logs validate | high |

## Strongest Differences vs Our Bot

1. Top Polymarket weather wallets in the recent slice are far more extreme-price / ladder oriented than our core KXHIGH forecast-gate strategy.
2. Their behavior appears event-level and grouped-market aware; our bot mostly evaluates brackets independently, even with coherent probability research.
3. Public wallet data does not prove maker/passive execution, while our own Kalshi research says execution quality is decisive.
4. Their repeated same-market activity suggests scale-in/out or ladder adjustment; our paper bot currently logs simpler single-signal entries.
5. Several wallets specialize by city/event; our strategy should keep city and bracket-family separation rather than global policy blending.

## Top Missing Features

- Event-level ladder state: total cost, max payoff, covered adjacent buckets, and net exposure by event.
- Extreme-price sleeve diagnostics split into lower tail, upper tail, exact temp, and range.
- Recent same-market flow: repeated buys/sells, wallet-like burst pressure, and local price crowding.
- Proposed/unfilled/cancelled order logs for true maker fill modeling.
- City/station-specific transfer filters for Polymarket patterns before applying to Kalshi.
