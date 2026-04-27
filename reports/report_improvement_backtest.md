# Report Improvement Backtest

Generated: 2026-04-27T01:26:25

Git SHA: `f70175e`

Input: `data/backtest_results.csv`

## Scope

This is a research-only backtest overlay inspired by `/Users/bhargavsukhavasi/Downloads/deep-research-report (6).md`.

It compares the current cached tradeable strategy (`CORE` + `DEEP_TAIL_NO`, with `TAIL_NO` suspended) against report-inspired selection improvements that are testable from the saved backtest rows:

- require positive edge after an execution-cost prior,
- split bracket families instead of treating central and wings identically,
- keep `DEEP_TAIL_NO` strict,
- avoid the cold/lower-wing subset that has been loss-making in the current cached data,
- require stronger core confidence before deploying capital.

It does **not** retrain EMOS, quantile forests, or gradient boosting. Those need a separate model-training study and true forecast-vintage features. It also does not touch live config, paper/live execution, `main.py`, `event_triggers.py`, or LaunchAgent files.

## Policy Comparison

| Policy | Trades | Days | Win Rate | Δ Win Rate | Saved Net | Maker Net | Stress +3c Net | Avg Entry | Avg Net Edge |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| current_strategy | 973 | 460 | 74.5% | +0.0pp | $49.24 | $55.77 | $-2.61 | 67.8% | 21.3pp |
| cost_gate_only | 862 | 441 | 71.8% | -2.7pp | $49.91 | $56.44 | $4.72 | 64.3% | 23.7pp |
| drop_cold_wing | 873 | 435 | 76.5% | +2.0pp | $60.68 | $66.61 | $14.23 | 67.9% | 20.6pp |
| core_confidence_60 | 797 | 416 | 79.7% | +5.2pp | $58.37 | $63.14 | $15.32 | 70.8% | 21.4pp |
| report_combined_policy | 602 | 353 | 80.4% | +5.9pp | $68.54 | $72.75 | $36.63 | 67.3% | 23.5pp |

## Combined Report Policy By Sleeve

| sleeve | trades | win_rate | saved_net_pnl | stress_net_pnl | avg_entry_price |
| --- | --- | --- | --- | --- | --- |
| CORE | 253 | 0.6363636363636364 | 29.29 | 16.639999999999993 | 0.5005928853754941 |
| DEEP_TAIL_NO | 349 | 0.9255014326647565 | 39.249999999999986 | 19.989999999999984 | 0.7982234957020057 |

## Combined Report Policy By Bracket Type

| bracket_type | trades | win_rate | saved_net_pnl | avg_entry_price |
| --- | --- | --- | --- | --- |
| central | 527 | 0.7836812144212524 | 56.66999999999998 | 0.658899430740038 |
| wing_high | 75 | 0.9466666666666667 | 11.869999999999997 | 0.7731999999999999 |

## Main Result

The current cached tradeable strategy has a win rate of **74.5%**.

The combined report-policy overlay has a win rate of **80.4%**, a change of **+5.9 percentage points**.

Saved-net P&L changes from **$49.24** to **$68.54** at $1 contract sizing.

Under the simple `+3c` stress scenario, net P&L changes from **$-2.61** to **$36.63**.

## Interpretation

The improvement comes mostly from better selection, not a better temperature forecast. The largest rejected subset is the lower/cold wing family, which is negative in both `CORE` and `DEEP_TAIL_NO` in the cached results. The second major improvement is requiring `CORE` confidence >= 60 and enough estimated net edge after execution cost.

Treat this as in-sample research. It is useful evidence for a paper-only policy candidate, not live approval.
