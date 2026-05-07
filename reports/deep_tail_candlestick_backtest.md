# DEEP_TAIL_NO Candlestick Bid/Ask Backtest

Uses official Kalshi 1-minute candlestick bid/ask data, not trade prints.

- Candidate rows: 6161
- Candidate tickers: 2144
- Candle rows cached: 2135083
- Candle tickers cached: 2144

Entry is conservative buy-NO pricing: `NO ask = 1 - yes_bid_close`.
Exit is conservative sell-NO pricing: `NO bid = 1 - yes_ask_close`.

## Results

| model_name | scenario | stop_policy | trades | target_days | win_rate | net_pnl | sharpe_daily | max_drawdown | stop_rate | target_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS | next_day_1015 | current_20c_stop | 428 | 290 | 55.1% | -450.24 | -4.73 | -555.27 | 44.4% | 6.8% |
| EMOS | next_day_1015 | no_stop | 428 | 290 | 94.9% | 595.63 | 7.20 | -170.47 | 0.0% | 8.6% |
| EMOS | same_day_1015 | current_20c_stop | 177 | 150 | 68.9% | -93.89 | -1.86 | -203.75 | 29.9% | 8.5% |
| EMOS | same_day_1015 | no_stop | 177 | 150 | 85.3% | 19.73 | 0.35 | -217.00 | 0.0% | 11.9% |
| EMOS | same_day_1100 | current_20c_stop | 144 | 121 | 62.5% | -166.22 | -3.83 | -209.40 | 36.1% | 6.9% |
| EMOS | same_day_1100 | no_stop | 144 | 121 | 82.6% | -58.42 | -1.14 | -232.16 | 0.0% | 11.1% |
| EMOS_GUMBEL | next_day_1015 | current_20c_stop | 523 | 344 | 53.2% | -626.40 | -5.20 | -722.91 | 46.5% | 8.0% |
| EMOS_GUMBEL | next_day_1015 | no_stop | 523 | 344 | 94.8% | 737.08 | 7.31 | -164.23 | 0.0% | 9.6% |
| EMOS_GUMBEL | same_day_1015 | current_20c_stop | 222 | 184 | 66.2% | -156.38 | -2.48 | -266.98 | 33.3% | 9.9% |
| EMOS_GUMBEL | same_day_1015 | no_stop | 222 | 184 | 86.5% | 79.22 | 1.13 | -216.38 | 0.0% | 14.9% |
| EMOS_GUMBEL | same_day_1100 | current_20c_stop | 191 | 161 | 63.9% | -159.05 | -2.88 | -222.08 | 34.6% | 11.5% |
| EMOS_GUMBEL | same_day_1100 | no_stop | 191 | 161 | 83.8% | 4.50 | 0.07 | -216.78 | 0.0% | 16.8% |
| EMOS_GUMBEL_HETERO | next_day_1015 | current_20c_stop | 658 | 411 | 49.7% | -949.07 | -6.39 | -1049.55 | 49.8% | 8.1% |
| EMOS_GUMBEL_HETERO | next_day_1015 | no_stop | 658 | 411 | 93.9% | 888.90 | 6.71 | -186.48 | 0.0% | 10.5% |
| EMOS_GUMBEL_HETERO | same_day_1015 | current_20c_stop | 335 | 277 | 58.8% | -382.11 | -4.02 | -456.86 | 40.3% | 9.6% |
| EMOS_GUMBEL_HETERO | same_day_1015 | no_stop | 335 | 277 | 85.1% | 145.96 | 1.31 | -243.13 | 0.0% | 17.0% |
| EMOS_GUMBEL_HETERO | same_day_1100 | current_20c_stop | 294 | 245 | 57.1% | -385.92 | -4.49 | -400.59 | 41.8% | 11.6% |
| EMOS_GUMBEL_HETERO | same_day_1100 | no_stop | 294 | 245 | 84.0% | 31.86 | 0.31 | -248.10 | 0.0% | 18.4% |
| GUMBEL | next_day_1015 | current_20c_stop | 617 | 414 | 50.9% | -819.27 | -6.02 | -888.87 | 48.5% | 6.8% |
| GUMBEL | next_day_1015 | no_stop | 617 | 414 | 94.2% | 752.00 | 6.04 | -175.13 | 0.0% | 8.9% |
| GUMBEL | same_day_1015 | current_20c_stop | 382 | 302 | 65.4% | -77.81 | -0.65 | -248.26 | 33.0% | 9.9% |
| GUMBEL | same_day_1015 | no_stop | 382 | 302 | 86.4% | 305.35 | 2.29 | -204.77 | 0.0% | 15.2% |
| GUMBEL | same_day_1100 | current_20c_stop | 346 | 281 | 62.4% | -167.79 | -1.59 | -235.99 | 35.3% | 10.7% |
| GUMBEL | same_day_1100 | no_stop | 346 | 281 | 85.0% | 172.68 | 1.44 | -214.89 | 0.0% | 15.6% |
