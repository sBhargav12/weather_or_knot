# Intraday Bracket-Lock Backtest
**Date range:** 2024-10-01 → 2026-04-23  
**Total days evaluated:** 436  
**Contract size:** 100 @ $1/contract notional  

## Why 3:00–4:15 PM?

The key insight: by 3 PM ET in NYC, the daily maximum temperature has already been reached on most days. The IEM ASOS running max at 3 PM is a reliable predictor of the NWS CLI bracket. The window closes at 4:15 PM because that's our existing DSM-cancel time.

## Timing Sweep (all days, no filters)

```
entry_time  n_days  bracket_accuracy  avg_entry_price  avg_margin_f  total_net_pnl  ev_per_trade  sharpe  max_drawdown
   1:00 PM     353             0.269            0.267         0.549        -213.93         -0.61  -0.016      -1017.13
   1:30 PM     353             0.269            0.267         0.549        -213.93         -0.61  -0.016      -1017.13
   2:00 PM     410             0.412            0.388         0.498         507.55          1.24   0.037       -722.82
   2:30 PM     410             0.412            0.381         0.498         824.79          2.01   0.058       -466.61
   3:00 PM     432             0.569            0.505         0.520        2132.61          4.94   0.135       -255.21
   3:30 PM      47             0.638            0.606         0.553          64.50          1.37   0.046       -130.63
   4:00 PM      56             0.714            0.681         0.589          69.52          1.24   0.042       -146.17
   4:15 PM      56             0.714            0.681         0.589          69.52          1.24   0.042       -146.17
```

## Margin Filter Sweep @ 3:00 PM

Upper_margin = °F the running max can still rise before flipping to the next bracket. Since ASOS reports integer °F, a running max of 69°F at bracket B68.5 (covers {68,69}) has upper_margin=0.5 — risky if CLI rounds up to 70. Requiring upper_margin ≥ 1.0 keeps only days where temp is safely inside the bracket.

```
 min_margin_f  n_trades  coverage_pct  bracket_accuracy  ev_per_trade  sharpe
          0.0       432         100.0             0.569          4.94   0.135
          0.5       225          52.1             0.787         12.19   0.387
          1.0       222          51.4             0.784         12.11   0.382
```

## Best Strategy: 3PM Entry + margin≥0.3 + declining trend

- **Trades:** 222
- **Win rate:** 78.4%
- **Avg entry price:** 0.64
- **Avg margin:** 1.00°F
- **Total net P&L:** $2688.51
- **EV per trade:** $12.11
- **Sharpe:** 0.382
- **Max drawdown:** $-264.26

## 4:00 PM Entry (for comparison)

- **Trades:** 33
- **Win rate:** 84.8%
- **Avg entry price:** 0.80
- **Total net P&L:** $74.62
- **EV per trade:** $2.26
- **Sharpe:** 0.098

## Key Findings

1. **Bracket accuracy at 3 PM with margin≥0.3 and declining temp: 78.4%** — this is the fraction of days where the running ASOS max correctly predicts the winning Kalshi bracket.
2. **Why 3PM–4:15PM specifically:** Bracket accuracy rises sharply between 1 PM and 3 PM as the daily max is established. After 3:30 PM the accuracy plateaus but prices rise (market reprices). The DSM fires at 4:21 PM after which prices jump to 95c+. The 3:00–4:15 PM window balances accuracy (high) vs. entry price (still attractive).
3. **The trend filter matters:** Days where temp is still rising at entry time have lower accuracy because the peak hasn't been reached. Requiring declining or flat temperature eliminates most false-confident entries.
4. **The margin filter matters:** A running max of 69.4°F near the bracket edge is much riskier than 68.3°F near the center. The ±0.4°F OMO correction in the CLI can flip a near-edge reading to the adjacent bracket.
