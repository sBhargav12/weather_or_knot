# Strategy 1 + Strategy 3 Predexon 3 PM Backtest

Entry window: 3:00 PM ET, using Predexon top-of-book snapshots.

Strategy 3 buys YES on the BRACKET_LOCK bracket. Strategy 1 is a conservative NO overlay on far-away central brackets after Strategy 3 fires.

## Summary

```text
                 strategy  trades  days  win_rate  avg_entry_price  total_pnl  ev_per_trade   sharpe  max_drawdown
S1_FAR_BRACKET_NO_OVERLAY       7     7  1.000000         0.970000      20.63      2.947143 0.931843          0.00
      S3_BRACKET_LOCK_YES      15    15  0.666667         0.621333      63.73      4.248667 0.142504        -63.41
 COMBINED_EVENT_PORTFOLIO      22    15       NaN              NaN      84.36      5.624000 0.195100        -63.41
```

## Notes

- Prices are maker-style entries at visible best bid: YES uses `yes_bid`; NO uses implied `no_bid = 1 - yes_ask`.
- This does not prove passive fill probability or queue position.
- The Strategy 1 overlay excludes tail markets for now and only trades central brackets at least 4F away from the predicted bracket floor.
- PnL assumes 100 contracts per leg and real Kalshi maker fee formula.

## Worst Event Days

```text
date
2026-02-01   -63.41
2026-03-29   -33.58
2026-04-15   -17.25
2026-01-09   -10.34
2026-01-23   -10.20
2026-01-13     3.92
2026-02-15     6.88
2026-04-18    11.81
```
