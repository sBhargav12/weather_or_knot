# Strategy 3 BRACKET_LOCK Backtest

Strategy 3 buys YES on the central KXHIGHNY bracket implied by the 3 PM ET observed running high.

Rule: enter only when upper margin is at least 1.0F. PnL assumes 100 maker contracts and the real Kalshi maker fee formula.

## Summary

```text
                 source  trades  days  win_rate  avg_entry_price  total_pnl  ev_per_trade   sharpe  max_drawdown
historical_3pm_snapshot     222   222  0.783784         0.643378    3058.60     13.777477 0.435706       -246.86
 predexon_3pm_orderbook      15    15  0.666667         0.621333      63.73      4.248667 0.142504        -63.41
```

## historical_3pm_snapshot

- Date range: 2024-10-01 to 2026-04-23
- Trades: 222
- Win rate: 78.4%
- Avg entry: 0.643
- Total PnL: $3058.60
- EV/trade: $13.78
- Max drawdown: $-246.86

Worst trades:

```text
                 source       date                 ticker  entry_price  running_max_3pm  cli_high  predicted_mid  winning_mid  upper_margin_f   won    pnl  bid_depth  ask_depth
historical_3pm_snapshot 2024-12-15 KXHIGHNY-24DEC15-B39.5         0.88             39.0      41.0           39.5         41.5             1.0 False -88.19        NaN        NaN
historical_3pm_snapshot 2025-04-26 KXHIGHNY-25APR26-B71.5         0.86             71.0      74.0           71.5         73.5             1.0 False -86.22        NaN        NaN
historical_3pm_snapshot 2026-01-05 KXHIGHNY-26JAN05-B35.5         0.85             35.0      39.0           35.5         39.5             1.0 False -85.23        NaN        NaN
historical_3pm_snapshot 2025-07-15 KXHIGHNY-25JUL15-B84.5         0.73             84.0      86.0           84.5         86.5             1.0 False -73.35        NaN        NaN
historical_3pm_snapshot 2026-02-01 KXHIGHNY-26FEB01-B22.5         0.71             22.0      24.0           22.5         24.5             1.0 False -71.37        NaN        NaN
historical_3pm_snapshot 2025-01-25 KXHIGHNY-25JAN25-B30.5         0.70             30.0      33.0           30.5         32.5             1.0 False -70.37        NaN        NaN
historical_3pm_snapshot 2025-05-24 KXHIGHNY-25MAY24-B62.5         0.68             62.0      64.0           62.5         64.5             1.0 False -68.39        NaN        NaN
historical_3pm_snapshot 2025-02-12 KXHIGHNY-25FEB12-B34.5         0.68             34.0      36.0           34.5         36.5             1.0 False -68.39        NaN        NaN
```

## predexon_3pm_orderbook

- Date range: 2026-01-09 to 2026-04-23
- Trades: 15
- Win rate: 66.7%
- Avg entry: 0.621
- Total PnL: $63.73
- EV/trade: $4.25
- Max drawdown: $-63.41

Worst trades:

```text
                source       date                 ticker  entry_price  running_max_3pm  cli_high  predicted_mid  winning_mid  upper_margin_f   won    pnl  bid_depth  ask_depth
predexon_3pm_orderbook 2026-02-01 KXHIGHNY-26FEB01-B22.5         0.63             22.0       NaN            NaN          NaN             1.0 False -63.41     1805.0     2934.0
predexon_3pm_orderbook 2026-03-29 KXHIGHNY-26MAR29-B52.5         0.42             52.0       NaN            NaN          NaN             1.0 False -42.43     1652.0     3974.0
predexon_3pm_orderbook 2026-04-15 KXHIGHNY-26APR15-B87.5         0.17             87.0       NaN            NaN          NaN             1.0 False -17.25     3125.0     3553.0
predexon_3pm_orderbook 2026-01-09 KXHIGHNY-26JAN09-B49.5         0.16             49.0       NaN            NaN          NaN             1.0 False -16.24     3634.0    15552.0
predexon_3pm_orderbook 2026-01-23 KXHIGHNY-26JAN23-B36.5         0.11             36.0       NaN            NaN          NaN             1.0 False -11.18     6572.0    22370.0
predexon_3pm_orderbook 2026-01-13 KXHIGHNY-26JAN13-B47.5         0.97             47.0       NaN            NaN          NaN             1.0  True   2.94    11540.0     1081.0
predexon_3pm_orderbook 2026-02-15 KXHIGHNY-26FEB15-B40.5         0.93             40.0       NaN            NaN          NaN             1.0  True   6.88     8690.0     7849.0
predexon_3pm_orderbook 2026-04-18 KXHIGHNY-26APR18-B65.5         0.88             65.0       NaN            NaN          NaN             1.0  True  11.81     3418.0     2437.0
```

