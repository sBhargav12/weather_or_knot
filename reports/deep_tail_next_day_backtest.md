# DEEP_TAIL_NO Next-Day 10:15 Backtest

This tests the live-code update that the early deep-tail scan should only evaluate tomorrow's newly opened markets.

Entry price source: latest traded YES price at or before the scenario timestamp in the full Becker/Kalshi trade tape.

## Coverage

- `next_day_1015`: 620 tradable of 781 priced candidates, 2024-10-09 00:00:00 to 2025-11-23 00:00:00
- `same_day_1015`: 942 tradable of 4013 priced candidates, 2024-10-01 00:00:00 to 2025-11-24 00:00:00
- `same_day_1100`: 898 tradable of 4021 priced candidates, 2024-10-01 00:00:00 to 2025-11-24 00:00:00

## Results

| model_name | scenario | trades | target_days | win_rate | net_pnl | sharpe_daily | max_drawdown | stop_rate | settlement_net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS | next_day_1015 | 114 | 94 | 81.6% | 73.18 | 2.93 | -60.34 | 18.4% | 129.53 |
| EMOS | same_day_1015 | 161 | 129 | 72.7% | 135.18 | 1.82 | -89.17 | 18.6% | 172.71 |
| EMOS | same_day_1100 | 155 | 124 | 70.3% | 104.76 | 1.44 | -66.05 | 20.6% | 113.06 |
| EMOS_GUMBEL | next_day_1015 | 148 | 119 | 75.0% | 219.09 | 2.19 | -73.27 | 25.0% | 507.37 |
| EMOS_GUMBEL | same_day_1015 | 190 | 152 | 72.1% | 143.16 | 1.69 | -100.50 | 21.6% | 367.11 |
| EMOS_GUMBEL | same_day_1100 | 182 | 146 | 73.1% | 222.30 | 2.70 | -57.01 | 20.3% | 354.62 |
| EMOS_GUMBEL_HETERO | next_day_1015 | 175 | 138 | 74.3% | 529.69 | 2.03 | -86.17 | 25.7% | 1084.32 |
| EMOS_GUMBEL_HETERO | same_day_1015 | 285 | 218 | 67.0% | 142.75 | 1.32 | -114.58 | 27.0% | 566.01 |
| EMOS_GUMBEL_HETERO | same_day_1100 | 270 | 207 | 64.8% | 160.93 | 1.51 | -63.75 | 29.3% | 543.36 |
| GUMBEL | next_day_1015 | 183 | 145 | 74.3% | 118.72 | 2.32 | -58.28 | 24.6% | 500.26 |
| GUMBEL | same_day_1015 | 306 | 241 | 73.2% | 301.27 | 2.39 | -87.25 | 20.9% | 777.18 |
| GUMBEL | same_day_1100 | 291 | 234 | 70.1% | 243.86 | 2.07 | -52.81 | 23.7% | 688.10 |

## Notes

- The primary PnL uses live-style stop and 11 PM time exit over observed trade prints.
- `settlement_net_pnl` is included as a diagnostic only; live rules do not intentionally hold to settlement.
- Historical order-book bid/ask was unavailable in the Becker trade tape, so entries use last trade as the price proxy.
