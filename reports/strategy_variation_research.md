# Strategy Variation Research

Generated: 2026-04-27 00:59:47

This is research-only. It does not change `config.py`, live thresholds, paper trader behavior, `main.py`, LaunchAgent, or execution code.

## Scope And Limits

- Uses cached KXHIGHNY API/backtest data from `data/kxhighny_*.csv`, `data/open_meteo_historical.csv`, and `data/backtest_results.csv`.
- Uses Kalshi settlement labels as payoff truth.
- Forecast vintage remains limited because cached Open-Meteo rows do not store cycle timestamps.
- Exit replay has two versions:
  - checkpoint replay using open/9AM/11AM/1PM/3PM API prices.
  - Becker observed-trade replay using trade prints only, not full orderbook/queue data.
- Becker replay can prove observed touches but cannot prove a passive maker order would have filled.

## Current Baseline

{
  "git_sha": "ae7dcac",
  "candidate_rows": 16610,
  "date_min": "2024-10-07",
  "date_max": "2026-04-24",
  "current_core": {
    "trades": 460,
    "trading_days": 323,
    "win_rate": 0.5760869565217391,
    "profitable_days": 171,
    "profitable_day_rate": 0.5294117647058824,
    "net_pnl": 17.37999999999999,
    "gross_pnl": 26.58,
    "sharpe": 0.08138412192841706,
    "max_drawdown": -17.04000000000001,
    "avg_entry_price": 0.5183043478260869,
    "median_entry_price": 0.53,
    "avg_return": 0.06922821269349648
  }
}

## Top Core Variants By Net P&L

| timing | gate_profile | gap_threshold | dead_zone_enabled | price_band | directions | family | trades | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| open | no_gate1 | 5 | False | 15_85 | both | all | 1439 | 0.665 | 143.57 | 0.2301 | -12.45 | 0.5466 |
| open | no_gate1 | 15 | False | 15_85 | both | all | 1165 | 0.6721 | 143.01 | 0.2868 | -12.29 | 0.5303 |
| open | no_gate1 | 10 | False | 15_85 | both | all | 1345 | 0.6706 | 142.26 | 0.2462 | -12.1 | 0.5462 |
| open | no_gate1 | 5 | True | 15_85 | both | all | 1320 | 0.6727 | 133.2 | 0.2327 | -12.64 | 0.5533 |
| open | no_gate1 | 15 | True | 15_85 | both | all | 1046 | 0.6826 | 132.64 | 0.2968 | -12.71 | 0.5368 |
| open | no_gate1 | 10 | True | 15_85 | both | all | 1226 | 0.6794 | 131.89 | 0.2506 | -12.79 | 0.5533 |
| open | loose_3f_between | 5 | False | 15_85 | both | all | 1240 | 0.6645 | 127.24 | 0.2376 | -11.65 | 0.5432 |
| open | loose_3f_between | 15 | False | 15_85 | both | all | 1015 | 0.6709 | 126.88 | 0.2927 | -12.21 | 0.5269 |
| open | loose_3f_between | 10 | False | 15_85 | both | all | 1158 | 0.6701 | 125.85 | 0.2535 | -12.02 | 0.5428 |
| open | no_gate1 | 15 | False | 15_85 | both | central | 1028 | 0.6683 | 124.49 | 0.287 | -5.6 | 0.5278 |
| open | no_gate1 | 10 | False | 15_85 | both | central | 1179 | 0.6616 | 121.82 | 0.2415 | -9.06 | 0.5392 |
| open | no_gate1 | 5 | False | 15_85 | both | central | 1267 | 0.6551 | 121.78 | 0.2221 | -12.04 | 0.5399 |
| open | loose_3f_between | 5 | True | 15_85 | both | all | 1138 | 0.6731 | 119.13 | 0.2424 | -11.25 | 0.5499 |
| open | loose_3f_between | 15 | True | 15_85 | both | all | 913 | 0.6824 | 118.77 | 0.3052 | -12.27 | 0.5333 |
| open | no_gate1 | 15 | False | 20_80 | both | all | 1008 | 0.6657 | 118.64 | 0.2671 | -12.12 | 0.528 |

## Top Checkpoint Exit Variants

| target | stop_diff | trades | win_rate | net_pnl | sharpe | max_drawdown | profitable_day_rate | exit_counts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| none | none | 460 | 0.5761 | 17.38 | 0.0814 | -17.04 | 0.5294 | {"SETTLEMENT": 460} |
| none | 0.25 | 460 | 0.5348 | 11.18 | 0.0546 | -16.12 | 0.5046 | {"SETTLEMENT": 349, "STOP_11AM": 10, "STOP_1PM": 25, "STOP_3PM": 76} |
| none | 0.2 | 460 | 0.5043 | 5.57 | 0.028 | -18.06 | 0.4861 | {"SETTLEMENT": 319, "STOP_11AM": 15, "STOP_1PM": 45, "STOP_3PM": 81} |
| none | 0.15 | 460 | 0.4717 | 3.75 | 0.0199 | -17.38 | 0.4799 | {"SETTLEMENT": 290, "STOP_11AM": 28, "STOP_1PM": 70, "STOP_3PM": 72} |
| none | 0.1 | 460 | 0.4174 | -1.33 | -0.0077 | -17.02 | 0.4582 | {"SETTLEMENT": 249, "STOP_11AM": 61, "STOP_1PM": 83, "STOP_3PM": 67} |
| 0.8 | none | 460 | 0.6065 | -8.0 | -0.0429 | -21.5 | 0.5604 | {"SETTLEMENT": 281, "TARGET_11AM": 38, "TARGET_1PM": 54, "TARGET_3PM": 87} |
| 0.8 | 0.25 | 460 | 0.5674 | -12.26 | -0.0693 | -23.07 | 0.5232 | {"SETTLEMENT": 181, "STOP_11AM": 10, "STOP_1PM": 25, "STOP_3PM": 72, "TARGET_11AM": 38, "TARGET_1PM": 54, "TARGET_3PM": 80} |
| 0.75 | none | 460 | 0.5978 | -13.7 | -0.0782 | -25.47 | 0.5418 | {"SETTLEMENT": 256, "TARGET_11AM": 64, "TARGET_1PM": 56, "TARGET_3PM": 84} |
| 0.75 | 0.25 | 460 | 0.5609 | -16.94 | -0.1028 | -26.38 | 0.5046 | {"SETTLEMENT": 159, "STOP_11AM": 10, "STOP_1PM": 25, "STOP_3PM": 69, "TARGET_11AM": 64, "TARGET_1PM": 56, "TARGET_3PM": 77} |
| 0.7 | none | 460 | 0.5348 | -17.54 | -0.1071 | -27.2 | 0.483 | {"SETTLEMENT": 229, "TARGET_11AM": 95, "TARGET_1PM": 59, "TARGET_3PM": 77} |
| 0.8 | 0.2 | 460 | 0.537 | -17.65 | -0.104 | -28.46 | 0.5015 | {"SETTLEMENT": 152, "STOP_11AM": 15, "STOP_1PM": 45, "STOP_3PM": 77, "TARGET_11AM": 38, "TARGET_1PM": 54, "TARGET_3PM": 79} |
| 0.68 | none | 460 | 0.5304 | -18.22 | -0.1132 | -27.36 | 0.4799 | {"SETTLEMENT": 220, "TARGET_11AM": 101, "TARGET_1PM": 63, "TARGET_3PM": 76} |
| 0.8 | 0.15 | 460 | 0.5065 | -19.29 | -0.1217 | -28.48 | 0.4675 | {"SETTLEMENT": 126, "STOP_11AM": 28, "STOP_1PM": 69, "STOP_3PM": 67, "TARGET_11AM": 38, "TARGET_1PM": 54, "TARGET_3PM": 78} |
| 0.7 | 0.25 | 460 | 0.5 | -20.85 | -0.136 | -28.18 | 0.4458 | {"SETTLEMENT": 139, "STOP_11AM": 10, "STOP_1PM": 25, "STOP_3PM": 62, "TARGET_11AM": 95, "TARGET_1PM": 58, "TARGET_3PM": 71} |
| 0.68 | 0.25 | 460 | 0.4957 | -21.77 | -0.1444 | -28.58 | 0.4396 | {"SETTLEMENT": 132, "STOP_11AM": 10, "STOP_1PM": 25, "STOP_3PM": 60, "TARGET_11AM": 101, "TARGET_1PM": 62, "TARGET_3PM": 70} |

## Top Becker Trade-Print Exit Variants

| target | stop_diff | trades | path_available_rate | win_rate | net_pnl | sharpe | max_drawdown | exit_counts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| none | none | 460 | 0.7283 | 0.5761 | 17.38 | 0.0814 | -17.04 | {"SETTLEMENT": 460} |
| 0.8 | none | 460 | 0.7283 | 0.6848 | 10.4 | 0.0628 | -17.04 | {"SETTLEMENT": 201, "TARGET": 259} |
| 0.75 | none | 460 | 0.7283 | 0.6935 | 7.67 | 0.0493 | -17.04 | {"SETTLEMENT": 187, "TARGET": 273} |
| 0.7 | none | 460 | 0.7283 | 0.6326 | -0.54 | -0.0037 | -17.04 | {"SETTLEMENT": 179, "TARGET": 281} |
| 0.68 | none | 460 | 0.7283 | 0.6217 | -4.18 | -0.029 | -17.04 | {"SETTLEMENT": 176, "TARGET": 284} |
| 0.8 | 0.25 | 460 | 0.7283 | 0.5804 | -6.05 | -0.0385 | -17.21 | {"SETTLEMENT": 132, "STOP": 117, "TARGET": 211} |
| 0.75 | 0.25 | 460 | 0.7283 | 0.5978 | -6.89 | -0.0461 | -17.04 | {"SETTLEMENT": 130, "STOP": 101, "TARGET": 229} |
| none | 0.25 | 460 | 0.7283 | 0.4413 | -9.24 | -0.0489 | -17.04 | {"SETTLEMENT": 280, "STOP": 180} |
| 0.65 | none | 460 | 0.7283 | 0.5804 | -9.55 | -0.0685 | -17.33 | {"SETTLEMENT": 171, "TARGET": 289} |
| 0.7 | 0.25 | 460 | 0.7283 | 0.5391 | -14.57 | -0.1018 | -20.26 | {"SETTLEMENT": 130, "STOP": 93, "TARGET": 237} |
| 0.68 | 0.25 | 460 | 0.7283 | 0.5391 | -15.44 | -0.1104 | -21.38 | {"SETTLEMENT": 130, "STOP": 84, "TARGET": 246} |
| 0.65 | 0.25 | 460 | 0.7283 | 0.5174 | -17.55 | -0.1297 | -22.92 | {"SETTLEMENT": 130, "STOP": 71, "TARGET": 259} |
| 0.75 | 0.2 | 460 | 0.7283 | 0.5391 | -17.86 | -0.1246 | -24.1 | {"SETTLEMENT": 125, "STOP": 133, "TARGET": 202} |
| 0.8 | 0.2 | 460 | 0.7283 | 0.5152 | -18.51 | -0.1236 | -24.0 | {"SETTLEMENT": 125, "STOP": 154, "TARGET": 181} |
| 0.75 | 0.15 | 460 | 0.7283 | 0.5 | -20.07 | -0.1472 | -25.59 | {"SETTLEMENT": 125, "STOP": 151, "TARGET": 184} |

## Top Sleeve Variants

| strategy | timing | p_yes_max | yes_price_min | yes_price_max | trades | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEEP_TAIL_NO | open | 0.1 | 0.05 | nan | 1016 | 0.9173 | 92.85 | 0.3135 | -10.38 | 0.8122 |
| DEEP_TAIL_NO | open | 0.1 | 0.03 | nan | 1244 | 0.9277 | 90.49 | 0.2645 | -11.13 | 0.8418 |
| DEEP_TAIL_NO | open | 0.05 | 0.05 | nan | 895 | 0.9318 | 89.06 | 0.3628 | -10.61 | 0.8189 |
| DEEP_TAIL_NO | open | 0.05 | 0.03 | nan | 1117 | 0.94 | 86.61 | 0.2985 | -11.36 | 0.8497 |
| DEEP_TAIL_NO | open | 0.03 | 0.05 | nan | 799 | 0.9462 | 85.88 | 0.4259 | -11.69 | 0.8255 |
| DEEP_TAIL_NO | open | 0.1 | 0.1 | nan | 717 | 0.894 | 85.3 | 0.3638 | -9.94 | 0.7597 |
| DEEP_TAIL_NO | open | 0.02 | 0.05 | nan | 743 | 0.9529 | 84.43 | 0.4754 | -12.45 | 0.8261 |
| DEEP_TAIL_NO | open | 0.03 | 0.03 | nan | 1012 | 0.9526 | 84.28 | 0.3479 | -12.44 | 0.8568 |
| DEEP_TAIL_NO | open | 0.02 | 0.03 | nan | 952 | 0.959 | 83.78 | 0.3896 | -13.2 | 0.8586 |
| DEEP_TAIL_NO | open | 0.1 | 0.01 | nan | 1467 | 0.9332 | 82.49 | 0.2112 | -12.13 | 0.8644 |
| DEEP_TAIL_NO | open | 0.05 | 0.01 | nan | 1332 | 0.9452 | 80.61 | 0.2422 | -12.36 | 0.8724 |
| DEEP_TAIL_NO | open | 0.05 | 0.1 | nan | 614 | 0.9104 | 80.49 | 0.4211 | -10.04 | 0.7643 |
| DEEP_TAIL_NO | open | 0.03 | 0.01 | nan | 1219 | 0.9573 | 80.28 | 0.2881 | -13.44 | 0.8794 |
| DEEP_TAIL_NO | open | 0.02 | 0.01 | nan | 1154 | 0.9627 | 79.78 | 0.3183 | -14.2 | 0.8816 |
| DEEP_TAIL_NO | open | 0.1 | 0.15 | nan | 479 | 0.8747 | 77.95 | 0.4641 | -8.19 | 0.6941 |
| DEEP_TAIL_NO | open | 0.03 | 0.1 | nan | 534 | 0.927 | 76.11 | 0.4916 | -11.12 | 0.7697 |
| DEEP_TAIL_NO | open | 0.02 | 0.1 | nan | 490 | 0.9327 | 73.38 | 0.5339 | -11.88 | 0.7681 |
| DEEP_TAIL_NO | open | 0.05 | 0.15 | nan | 395 | 0.8962 | 73.01 | 0.5594 | -8.19 | 0.6936 |
| DEEP_TAIL_NO | open | 0.01 | 0.05 | nan | 629 | 0.9555 | 71.0 | 0.4739 | -12.94 | 0.8297 |
| DEEP_TAIL_NO | open | 0.01 | 0.03 | nan | 830 | 0.9614 | 70.22 | 0.3776 | -13.69 | 0.8646 |

## Main Research Takeaways

1. The highest-P&L core variants are research candidates only. They often trade more or loosen constraints, so they must be judged under walk-forward and stress, not raw in-sample P&L alone.
2. Exit targets are not automatically beneficial. A low target can raise hit rate while capping winners and adding exit fees.
3. Stop-loss variants are especially dangerous in trade-print replay because many eventual winners wobble intraday before settlement.
4. NO-side and wing behavior should continue to be analyzed separately from central YES-style trades.
5. Near-confirmed NO harvest can show extremely high win rate but weak net P&L when entry is near 99c; fees and one rare loss dominate.

## Output Files

- `data/research/strategy_variation_core_grid.csv`
- `data/research/strategy_variation_exit_grid.csv`
- `data/research/strategy_variation_becker_exit_grid.csv`
- `data/research/strategy_variation_sleeve_grid.csv`
- `data/research/strategy_variation_top_trades.csv`
- `data/research/strategy_variation_summary.json`
