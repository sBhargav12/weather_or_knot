# Deep Research Report 7 Policy Stress Backtest

Generated: 2026-04-27T02:03:45

Git SHA: `5348b7a`

Input: `data/backtest_results.csv`

## Scope

This is a research-only validation of the actionable parts of
`/Users/bhargavsukhavasi/Downloads/deep-research-report (7).md`.

The report's paper-only config, TAIL_NO suspension, wing/central split, net-edge
gate, and strategy-health reporting already exist in this repo. This run adds a
dedicated stress comparison with +1c, +3c, and +5c worse execution assumptions
and a soft seasonal/regime sized variant.

Ideas not tested here: market making, straddles, cross-market arbitrage, condor
spreads, reinforcement learning, EMOS/QRF/HGBR retraining. Those need additional
order-book/action data or a separate forecast-vintage-aware model bakeoff.

## Results

| Policy | Trades | Days | Win Rate | Δ Win Rate | Net 0c | Net +1c | Net +3c | Net +5c | Avg Size Mult |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| current_strategy | 973 | 460 | 74.5% | +0.0pp | $55.77 | $36.31 | $-2.61 | $-40.28 | 0.64 |
| paper_net_edge_policy | 842 | 438 | 71.1% | -3.4pp | $55.12 | $38.28 | $4.60 | $-29.08 | 0.63 |
| paper_net_edge_sized | 842 | 438 | 71.1% | -3.4pp | $58.21 | $47.54 | $26.18 | $4.83 | 0.63 |
| report7_lower_tail_caution | 761 | 413 | 73.3% | -1.2pp | $63.91 | $48.69 | $18.25 | $-12.19 | 0.64 |
| report7_strict_selection | 589 | 350 | 80.0% | +5.5pp | $71.89 | $60.11 | $36.55 | $12.99 | 0.63 |

## Strict Policy By Sleeve

| Sleeve | Trades | Win Rate | Net 0c | Net +3c |
|---|---:|---:|---:|---:|
| CORE | 253 | 63.6% | $31.82 | $16.64 |
| DEEP_TAIL_NO | 336 | 92.3% | $40.07 | $19.91 |

## Read

The report's valid improvement is better trade selection under execution stress,
not a new forecasting signal. The best-performing strict selection is smaller
than the current strategy, but it raises win rate and keeps more P&L under +3c
and +5c stress by removing lower-tail/cold-wing exposure and marginal core rows.

Soft seasonal/regime sizing changes capital exposure and drawdown shape, not raw
win rate. It should be evaluated as a bankroll-control layer, not as alpha.
