# Loss Analysis Report

Generated from `data/backtest_results.csv`.

This is research-only. It does not change live thresholds, paper policy, execution, `main.py`, or `event_triggers.py`.

## Current Tradeable Strategy Summary

Current tradeable set = `CORE + DEEP_TAIL_NO` (`TAIL_NO` is disabled/suspended).

| Metric | Value |
| --- | ---: |
| Trades | 973 |
| Wins | 725 |
| Losses | 248 |
| Win rate | 74.5% |
| Net P&L | $49.24 |
| Loss-side net | $-127.44 |

## Losses By Sleeve

| sleeve | trades | losses | win_rate | net_pnl | loss_net | avg_entry |
| --- | --- | --- | --- | --- | --- | --- |
| CORE | 460 | 195 | 0.5761 | 17.38 | -93.5 | 0.5183 |
| DEEP_TAIL_NO | 513 | 53 | 0.8967 | 31.86 | -33.94 | 0.8208 |

## Why We Lost

### Loss Mode Breakdown

| sleeve | loss_mode | trades | net | avg_entry | avg_error |
| --- | --- | --- | --- | --- | --- |
| CORE | YES_loss_near_model_or_adjacent | 57 | -23.94 | 0.4 | 0.7621 |
| CORE | NO_loss_bracket_hit | 48 | -25.02 | 0.5012 | 1.1474 |
| CORE | NO_loss_actual_hotter_than_model | 40 | -23.43 | 0.5657 | 2.832 |
| CORE | YES_loss_actual_hotter_than_model | 25 | -8.28 | 0.3112 | 2.89 |
| DEEP_TAIL_NO | NO_loss_cold_lower_tail_hit | 25 | -14.26 | 0.5532 | 1.7358 |
| CORE | NO_loss_cold_lower_tail_hit | 13 | -7.11 | 0.5269 | 0.975 |
| DEEP_TAIL_NO | NO_loss_actual_hotter_than_model | 13 | -9.91 | 0.7462 | 4.3685 |
| DEEP_TAIL_NO | NO_loss_bracket_hit | 7 | -3.61 | 0.4986 | nan |
| DEEP_TAIL_NO | NO_loss_actual_colder_than_model | 6 | -4.66 | 0.76 | -2.6458 |
| CORE | YES_loss_lower_tail_missed | 5 | -2.13 | 0.406 | 2.985 |
| CORE | NO_loss_hot_upper_tail_hit | 3 | -1.51 | 0.4833 | 5.1167 |
| CORE | NO_loss_actual_colder_than_model | 2 | -1.3 | 0.63 | -2.4475 |
| CORE | YES_loss_actual_colder_than_model | 2 | -0.78 | 0.37 | -4.345 |
| DEEP_TAIL_NO | NO_loss_hot_upper_tail_hit | 2 | -1.5 | 0.735 | 6.2875 |

### Worst Individual Losing Trades

| date | ticker | sleeve | bracket | bracket_type | direction | entry_price | gap_pp | model_prob | confidence | consensus | settlement_temp | actual_minus_consensus | loss_mode | net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-02-06 00:00:00 | KXHIGHNY-25FEB06-B37.5 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.96 | -6.0 | 0.0 | 54.0 | 37.555 | 38.0 | 0.445 | NO_loss_cold_lower_tail_hit | -0.97 |
| 2026-01-21 00:00:00 | KXHIGHNY-26JAN21-B39.5 | DEEP_TAIL_NO | 39-40F | central | NO | 0.95 | -6.4916 | 0.0051 | 41.0 | 35.085 | 40.0 | 4.915 | NO_loss_actual_hotter_than_model | -0.96 |
| 2025-02-09 00:00:00 | KXHIGHNY-25FEB09-B35.5 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.95 | -7.0 | 0.0 | 39.0 | 34.345 | 36.0 | 1.655 | NO_loss_cold_lower_tail_hit | -0.96 |
| 2026-03-07 00:00:00 | KXHIGHNY-26MAR07-B52.5 | DEEP_TAIL_NO | 52-53F | central | NO | 0.94 | -7.6243 | 0.0038 | 41.67 | 47.86 | 52.0 | 4.14 | NO_loss_actual_hotter_than_model | -0.95 |
| 2025-02-03 00:00:00 | KXHIGHNY-25FEB03-B48.5 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.94 | -8.0 | 0.0 | 33.33 | 43.65 | 49.0 | 5.35 | NO_loss_cold_lower_tail_hit | -0.95 |
| 2026-04-17 00:00:00 | KXHIGHNY-26APR17-B81.5 | DEEP_TAIL_NO | 81-82F | central | NO | 0.93 | -7.1848 | 0.0182 | 26.33 | 78.035 | 81.0 | 2.965 | NO_loss_actual_hotter_than_model | -0.94 |
| 2025-06-11 00:00:00 | KXHIGHNY-25JUN11-T82 | DEEP_TAIL_NO | <=82F | wing_low | NO | 0.91 | -10.9706 | 0.0003 | 42.29 | 83.505 | 81.0 | -2.505 | NO_loss_cold_lower_tail_hit | -0.92 |
| 2026-04-01 00:00:00 | KXHIGHNY-26APR01-T79 | DEEP_TAIL_NO | >79F | wing_high | NO | 0.89 | -12.195 | 0.008 | 30.26 | 76.375 | 80.0 | 3.625 | NO_loss_hot_upper_tail_hit | -0.9 |
| 2025-12-17 00:00:00 | KXHIGHNY-25DEC17-B47.5 | DEEP_TAIL_NO | 47-48F | central | NO | 0.89 | -12.4848 | 0.0052 | 42.31 | 43.095 | nan | nan | NO_loss_bracket_hit | -0.9 |
| 2025-06-05 00:00:00 | KXHIGHNY-25JUN05-B86.5 | DEEP_TAIL_NO | 86-87F | central | NO | 0.86 | -16.0 | 0.0 | 33.5 | 89.96 | 87.0 | -2.96 | NO_loss_actual_colder_than_model | -0.87 |
| 2026-02-25 00:00:00 | KXHIGHNY-26FEB25-B43.5 | DEEP_TAIL_NO | 43-44F | central | NO | 0.86 | -15.8795 | 0.0012 | 46.84 | 38.015 | 44.0 | 5.985 | NO_loss_actual_hotter_than_model | -0.87 |
| 2025-07-18 00:00:00 | KXHIGHNY-25JUL18-B81.5 | DEEP_TAIL_NO | 81-82F | central | NO | 0.85 | -16.9594 | 0.0004 | 45.28 | 84.475 | 82.0 | -2.475 | NO_loss_actual_colder_than_model | -0.86 |
| 2025-11-25 00:00:00 | KXHIGHNY-25NOV25-B58.5 | DEEP_TAIL_NO | 58-59F | central | NO | 0.85 | -15.9437 | 0.0106 | 58.59 | 54.63 | 58.0 | 3.37 | NO_loss_actual_hotter_than_model | -0.86 |
| 2025-01-26 00:00:00 | KXHIGHNY-25JAN26-T42 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.82 | -20.0 | 0.0 | 54.0 | 41.28 | 43.0 | 1.72 | NO_loss_cold_lower_tail_hit | -0.84 |
| 2026-03-11 00:00:00 | KXHIGHNY-26MAR11-B72.5 | DEEP_TAIL_NO | 72-73F | central | NO | 0.8 | -21.7638 | 0.0024 | 31.19 | 67.515 | 72.0 | 4.485 | NO_loss_actual_hotter_than_model | -0.82 |
| 2025-02-04 00:00:00 | KXHIGHNY-25FEB04-B46.5 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.8 | -22.0 | 0.0 | 50.33 | 44.06 | 47.0 | 2.94 | NO_loss_cold_lower_tail_hit | -0.82 |
| 2024-12-23 00:00:00 | KXHIGHNY-24DEC23-B30.5 | DEEP_TAIL_NO | 30-31F | central | NO | 0.79 | -22.5731 | 0.0043 | 59.1 | 25.955 | 31.0 | 5.045 | NO_loss_actual_hotter_than_model | -0.81 |
| 2025-07-06 00:00:00 | KXHIGHNY-25JUL06-B86.5 | DEEP_TAIL_NO | 86-87F | central | NO | 0.78 | -23.9689 | 0.0003 | 45.96 | 89.5 | 87.0 | -2.5 | NO_loss_actual_colder_than_model | -0.8 |
| 2025-02-08 00:00:00 | KXHIGHNY-25FEB08-B34.5 | DEEP_TAIL_NO | <=nanF | wing_low | NO | 0.77 | -25.0 | 0.0 | 72.33 | 34.045 | 35.0 | 0.955 | NO_loss_cold_lower_tail_hit | -0.79 |
| 2026-02-14 00:00:00 | KXHIGHNY-26FEB14-B46.5 | DEEP_TAIL_NO | 46-47F | central | NO | 0.75 | -26.0253 | 0.0097 | 49.03 | 42.57 | 46.0 | 3.43 | NO_loss_actual_hotter_than_model | -0.77 |

## Factor Diagnostics

The table below shows the factor buckets that contributed the most losing P&L.

| factor | value | trades | losses | win_rate | net_pnl | loss_net | avg_entry | avg_gap_abs | avg_model_prob | avg_confidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| settlement_mismatch | False | 929 | 210 | 0.774 | 68.8 | -106.57 | 0.6833 | 25.1201 | 0.1501 | 54.9213 |
| bracket_type | central | 764 | 200 | 0.7382 | 47.81 | -100.93 | 0.6584 | 26.1785 | 0.1621 | 55.5785 |
| sleeve | CORE | 460 | 195 | 0.5761 | 17.38 | -93.5 | 0.5183 | 33.2101 | 0.3023 | 63.5234 |
| direction | NO | 818 | 159 | 0.8056 | 46.23 | -92.31 | 0.733 | 24.4293 | 0.0352 | 53.9524 |
| actual_minus_consensus_bucket | +1:+3F | 343 | 109 | 0.6822 | -8.66 | -53.94 | 0.6909 | 25.4522 | 0.1384 | 55.2925 |
| direction | YES | 155 | 89 | 0.4258 | 3.01 | -35.13 | 0.3864 | 34.014 | 0.7265 | 63.9505 |
| entry_bucket | 45-55c | 116 | 66 | 0.431 | -11.63 | -34.82 | 0.5113 | 34.6953 | 0.3072 | 60.2653 |
| sleeve | DEEP_TAIL_NO | 513 | 53 | 0.8967 | 31.86 | -33.94 | 0.8208 | 19.4517 | 0.0047 | 48.3911 |
| loss_mode | NO_loss_actual_hotter_than_model | 53 | 53 | 0.0 | -33.34 | -33.34 | 0.61 | 33.5101 | 0.0598 | 60.8643 |
| model_prob_bucket | 0-0.5% | 364 | 51 | 0.8599 | 9.24 | -31.8 | 0.8208 | 19.6241 | 0.0011 | 47.5052 |
| loss_mode | NO_loss_bracket_hit | 55 | 55 | 0.0 | -28.63 | -28.63 | 0.5009 | 34.1772 | 0.1599 | 60.792 |
| gap_bucket | 20-25 | 156 | 50 | 0.6795 | 2.82 | -27.58 | 0.6414 | 22.7863 | 0.2155 | 51.9712 |
| gap_bucket | 40-50 | 117 | 54 | 0.5385 | 6.18 | -25.88 | 0.4656 | 43.7696 | 0.2533 | 73.3974 |
| gap_bucket | 30-35 | 146 | 46 | 0.6849 | 12.18 | -24.54 | 0.5815 | 32.4281 | 0.1883 | 64.6179 |
| entry_bucket | 55-65c | 124 | 39 | 0.6855 | 7.44 | -24.19 | 0.6055 | 33.8639 | 0.0737 | 62.8214 |
| loss_mode | YES_loss_near_model_or_adjacent | 57 | 57 | 0.0 | -23.94 | -23.94 | 0.4 | 31.2254 | 0.7123 | 59.0033 |
| actual_minus_consensus_bucket | +3:+5F | 91 | 45 | 0.5055 | -15.79 | -23.87 | 0.6623 | 28.7843 | 0.109 | 55.7321 |
| bracket_type | wing_low | 100 | 43 | 0.57 | -11.44 | -23.5 | 0.6684 | 32.5899 | 0.1568 | 60.5443 |
| model_prob_bucket | 10-25% | 92 | 43 | 0.5326 | -2.44 | -23.33 | 0.5391 | 30.4151 | 0.1567 | 59.2685 |
| gap_bucket | 25-30 | 143 | 46 | 0.6783 | 9.03 | -22.79 | 0.5952 | 27.5415 | 0.232 | 58.9726 |
| loss_mode | NO_loss_cold_lower_tail_hit | 38 | 38 | 0.0 | -21.37 | -21.37 | 0.5442 | 45.7764 | 0.0112 | 68.7632 |
| settlement_mismatch | True | 44 | 38 | 0.1364 | -19.56 | -20.87 | 0.5627 | 43.608 | 0.0444 | 68.7164 |
| entry_bucket | 35-45c | 89 | 47 | 0.4719 | 3.63 | -20.33 | 0.4111 | 38.4824 | 0.455 | 64.888 |
| model_prob_bucket | 50-75% | 82 | 50 | 0.3902 | 0.77 | -18.81 | 0.3609 | 29.5585 | 0.6564 | 61.566 |
| month | 2025-01 | 69 | 39 | 0.4348 | -11.99 | -18.76 | 0.5906 | 37.3375 | 0.1353 | 65.053 |
| entry_bucket | >75c | 385 | 19 | 0.9506 | 18.2 | -16.79 | 0.8916 | 12.4215 | 0.0042 | 42.5785 |
| actual_minus_consensus_bucket | nan | 111 | 34 | 0.6937 | 0.22 | -16.44 | 0.675 | 26.669 | 0.1291 | 57.8071 |
| model_prob_bucket | 75-100% | 71 | 38 | 0.4648 | 1.81 | -16.04 | 0.4193 | 39.4956 | 0.8143 | 67.202 |
| actual_minus_consensus_bucket | -1:+1F | 327 | 31 | 0.9052 | 75.32 | -15.23 | 0.6579 | 25.8039 | 0.175 | 56.7576 |
| entry_bucket | 65-75c | 171 | 20 | 0.883 | 26.99 | -14.47 | 0.7052 | 28.2761 | 0.0356 | 61.8205 |

## Improvement Tests

These are simple exclusion tests on the current tradeable set. They are not recommendations by themselves because removing trades can improve historical P&L while overfitting.

| test | trades | trades_removed | win_rate | net_pnl | net_delta_vs_baseline | sharpe | max_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- |
| drop_jan_dec | 732 | 241 | 0.7964 | 69.39 | 20.15 | 0.2599 | -4.59 |
| drop_settlement_mismatch_rows | 929 | 44 | 0.774 | 68.8 | 19.56 | 0.2047 | -12.89 |
| drop_core_conf_lt_60 | 797 | 176 | 0.7967 | 58.37 | 9.13 | 0.2089 | -17.78 |
| drop_core_entry_45_65 | 778 | 195 | 0.7969 | 55.54 | 6.3 | 0.2101 | -12.54 |
| drop_core_wing_low | 938 | 35 | 0.7548 | 51.45 | 2.21 | 0.1478 | -12.5 |
| drop_high_subset_spread_gt_2f | 835 | 138 | 0.7521 | 51.34 | 2.1 | 0.1638 | -16.12 |
| require_core_gap_gt_25 | 866 | 107 | 0.7656 | 50.94 | 1.7 | 0.1611 | -16.03 |
| baseline_current | 973 | 0 | 0.7451 | 49.24 | 0.0 | 0.1345 | -17.83 |
| require_core_gap_gt_30 | 753 | 220 | 0.7888 | 47.24 | -2.0 | 0.1771 | -15.96 |
| drop_core_yes | 818 | 155 | 0.8056 | 46.23 | -3.01 | 0.1615 | -13.08 |
| core_no_only_plus_deep | 818 | 155 | 0.8056 | 46.23 | -3.01 | 0.1615 | -13.08 |
| deep_tail_stricter_p_lt_1pct | 868 | 105 | 0.7235 | 35.85 | -13.39 | 0.1063 | -20.22 |
| drop_high_model_disagreement_gt_2f | 767 | 206 | 0.7223 | 35.06 | -14.18 | 0.1181 | -18.12 |

## Interpretation

1. Core losses are mostly ordinary model misses: the forecast distribution assigned a bracket too much or too little probability, then the official Kalshi settlement landed against that side.
2. Core YES trades remain weaker than core NO trades. The YES side has lower win rate and needs separate calibration before sizing up.
3. Lower-tail/wing-low core trades are a recurring weak spot in the cached backtest.
4. Deep-tail losses are rare but expensive because the NO entry is often high; a single bracket that actually settles YES can wipe out many small wins.
5. Months and regimes matter. January/December and some high-disagreement/high-spread periods account for a large share of avoidable pain.
6. Settlement mismatches against reconstructed IEM temperatures are diagnostic red flags. P&L uses Kalshi labels, but mismatches identify days where station/settlement reconstruction uncertainty is high.

## Practical Improvements To Research Next

1. Split probability calibration by side: YES core, NO core, deep-tail NO.
2. Add a core wing-low penalty or require larger edge for lower-tail brackets.
3. Keep DEEP_TAIL_NO strict at `P_yes < 2%` until fill-stressed forward paper data says otherwise.
4. Add a paper-only flag that logs would-have-skipped results for high model disagreement or high subset spread.
5. Build true forecast-vintage rows so we can identify whether losses came from forecast leakage, late model changes, or price timing.
6. Add post-entry path labels from Becker trade prints for each losing core trade: adverse excursion, favorable excursion, target touched, stop touched.
7. Preserve 20pp live threshold until these filters are walk-forward validated.

## Output Files

- `data/research/loss_analysis_trades.csv`
- `data/research/loss_analysis_factor_summary.csv`
- `data/research/loss_analysis_improvement_tests.csv`
- `data/research/loss_analysis_summary.json`
