# KXLOWT Daily Low Temperature Backtest

Generated: 2026-05-05T15:53:06+00:00
Model: EMOS_GUMBEL_HETERO on daily TMIN forecasts
Training: 2024-07-01 – 2026-01-28 (pre-market IEM actuals + Single Runs API)
Eval: 2026-01-28+ (actual KXLOWT markets)  |  YES filter: 30–35pp gap

## Per-City Results (unit-sized, leakage-safe)

| City | Trades | Win% | Net PnL | Sharpe | YES | NO | Train days | Eval days |
|------|--------|------|---------|--------|-----|----|-----------|-----------|
| KXLOWTNYC | 15 | 66.7% | $0.41 | 0.057 | 0 (0%) | 15 (67%) | 168 | 90 |

## Capital Simulation ($500 quarter-Kelly, all cities combined)

- Starting: $500  →  Final: $516.33  (+$16.33)
- Total trades: 15
- Win rate: 66.7%
- Net P&L: $16.33
- Sharpe: 0.053
- Max drawdown: $-43.00

## Monthly Breakdown

| Month | Trades | Cities | Win% | Net P&L | Bankroll End |
|---|---|---|---|---|---|
| 2026-02 | 6 | 1 | 66.7% | $0.62 | $500.62 |
| 2026-03 | 4 | 1 | 75.0% | $34.20 | $534.82 |
| 2026-04 | 5 | 1 | 60.0% | $-18.49 | $516.33 |
