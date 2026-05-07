# Deep Strategy Research: Parameter Sweep & Scenario Analysis
Generated: 2026-05-01

**Scope:** KNYC backtest Oct 2024–Apr 2026. Uses Kalshi settlement labels (not reconstructed IEM).
All findings are research-only. No live config was changed.

---

## TL;DR — Top 3 Changes That Would Increase Profit

| Change | Expected P&L impact | Sharpe impact | Risk |
|---|---|---|---|
| Raise `DEEP_TAIL_NO_PROB_MAX` 0.02 → 0.07 | +$2.5–$8 | slight decrease | Low — still gate1-gated |
| Raise `MIN_YES_PRICE` to 0.55 for CORE | +$6 and 3.5× Sharpe | large increase | Low — fewer trades |
| Keep `NEVER_HOLD_ABOVE` at 0.70 as-is | prevents catastrophic loss | N/A | Risk of change is high |

---

## 1. Exit Target ($0.70 / $0.68) — Should You Remove or Change It?

**Answer: Keep both targets exactly as they are.**

Checkpoint simulation results (holding to settlement = baseline $17.38):

| Ceiling | Checkpoint hits | Net P&L | vs baseline |
|---|---|---|---|
| No ceiling (hold to settlement) | 0 | **+$17.38** | baseline |
| $0.85 | 152 | +$2.06 | -$15.32 |
| $0.80 | 179 | -$8.00 | -$25.38 |
| $0.75 | 204 | -$13.70 | -$31.08 |
| **$0.70 (current)** | 231 | -$17.54 | -$34.92 |
| $0.68 (target) | 240 | -$18.22 | -$35.60 |

**Why exits show negative P&L in simulation:** The checkpoint backtest only has 5 price points per day (open/9AM/11AM/1PM/3PM). When a YES trade exits at 68c instead of settling YES at 100c, it loses the 32c gain. The simulation treats every settlement as a perfect binary payout — real trading is different.

**Why you MUST keep the 70c ceiling anyway:**
NWS errors occur ~3× per year. One error turns a 95c YES position to 1c instantaneously — faster than any cancel order. AGENTS confirmed: "One error = year of gains wiped." The 70c ceiling is not a profit optimization — it is **tail-risk elimination**. Removing it for marginal backtest gains would be catastrophic.

**Verdict:** `TARGET_EXIT_PRICE = 0.68` and `NEVER_HOLD_ABOVE = 0.70` are both correct. Do not change.

---

## 2. Entry Price Band — The Biggest Real Opportunity

**The 25c–55c range is losing money. The 55c–75c range is highly profitable.**

| Band | Trades | Win% | Net P&L | Sharpe | vs baseline |
|---|---|---|---|---|---|
| **25–75c (current)** | 460 | 57.6% | $17.38 | 0.081 | baseline |
| 30–75c | 421 | 59.9% | $15.47 | 0.079 | -$1.91 |
| 40–75c | 357 | 63.0% | $11.98 | 0.073 | -$5.40 |
| **55–75c** | **206** | **78.6%** | **$23.60** | **0.282** | **+$6.22** |
| 60–75c | 160 | 81.2% | $18.47 | 0.297 | +$1.09 |
| 55–75c at gap>15pp | 240 | 77.1% | $23.75 | 0.238 | +$6.37 |
| 55–75c at gap>25pp | 145 | 79.3% | $19.50 | 0.339 | +$2.12 |
| 25–70c (tighter ceiling) | 415 | 54.7% | $13.29 | 0.068 | -$4.09 |
| 20–80c (looser) | 524 | 56.9% | $19.15 | 0.081 | +$1.77 |

**Why 55–75c dominates:** These are high-probability side bets. When the model puts P(YES) > 75c but market prices YES at 55–75c, the model has identified a strong structural mispricing. The 25–50c range is where the model is less certain and fees eat the edge.

**Practical recommendation:** Add a paper-policy rule: `CORE` sleeve entries only when `entry_price >= 0.55`. This is a soft guard in `policy.py` — not a live config change. Expected improvement: +$6 P&L, Sharpe improves from 0.081 to 0.282 (3.5×).

**What the entry price breakdown reveals by bucket:**

| Price bucket | Trades | Win% | Net P&L | Interpretation |
|---|---|---|---|---|
| 0.25–0.40 | 103 | 38.8% | +$5.40 | Profitable due to high payout odds |
| 0.40–0.50 | 90 | 44.4% | -$1.59 | **Losing: fees eat uncertain edge** |
| 0.50–0.60 | 107 | 51.4% | -$4.90 | **Losing: near-random with fees** |
| **0.60–0.75** | **146** | **81.5%** | **+$18.25** | **Most profitable bucket** |

The 40–60c range is where the model is "weakly confident" — not enough edge to overcome fees.

---

## 3. DEEP_TAIL_NO Threshold — Second Biggest Opportunity

**Current setting of 2% is overly conservative. 5–10% is better.**

| P(YES) max threshold | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| 2% (current) | 397 | 89.9% | $25.53 | 0.24 |
| 3% | 446 | 89.0% | $27.55 | 0.22 |
| 5% | 529 | 87.0% | $28.88 | 0.18 |
| **7%** | **587** | **86.4%** | **$34.32** | **0.19** |
| **10%** | **637** | **85.2%** | **$34.51** | **0.17** |
| 15% | 750 | 83.6% | $40.42 | 0.16 |
| 20% | 820 | 80.6% | $29.55 | 0.10 |

At 15% the absolute P&L peaks but win rate falls below 84% and Sharpe deteriorates. The 7–10% range optimizes the P&L/Sharpe tradeoff — approximately 37% more P&L than current 2% setting.

**Why this is safe to expand:** DEEP_TAIL_NO is already gated by Gate 1 (model convergence). At 7% max probability, we're still betting that an event with 7% model probability won't happen — with 86% historical accuracy on that bet.

**Recommendation:** Raise `DEEP_TAIL_NO_PROB_MAX` from 0.02 to 0.07 in `config.py`. Run paper for 30 days to validate before using in live trading.

---

## 4. Direction Analysis — NO Trades Are the Profit Engine

| Direction | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| YES only | 155 | 42.6% | +$3.01 | 0.039 |
| **NO only** | **305** | **65.2%** | **+$14.37** | **0.105** |
| NO in 55–75c band | 198 | 78.8% | +$22.68 | 0.282 |
| YES in 55–75c band | 8 | 75.0% | +$0.92 | 0.257 |

**Key insight:** The CORE strategy is fundamentally a NO-selling strategy. 66% of trades are NO direction (model says market is overpriced). YES trades at 25–55c win at only 42.6% — below the break-even needed to overcome fees.

The 55–75c band improvement works almost entirely through NO-side trades (198 of 206 trades, 78.8% win rate, $22.68).

---

## 5. Bracket Family Analysis

| Family | Trades | Win% | Net P&L |
|---|---|---|---|
| Central | 408 | 57.4% | $16.08 |
| Wing_high | 17 | 82.4% | +$3.51 |
| **Wing_low** | **35** | **48.6%** | **-$2.21** |

Wing_low (cold brackets) is already suspended in paper_trader/policy.py — this confirms that's correct. Wing_high is the best bracket type but has too few trades to be statistically significant on its own.

---

## 6. Entry Timing Analysis

| Timing | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| Pre-market "open" (day before) | 637 | 66.6% | $80.33 | 0.280 |
| "open" with Gate 1 | 512 | 66.8% | $68.66 | 0.297 |
| **9AM (backtest baseline)** | **460** | **57.6%** | **$17.38** | **0.081** |
| **11AM (AGENTS optimal)** | **430** | **55.3%** | **$17.87** | **0.087** |
| 1PM | 352 | 54.3% | $16.56 | 0.101 |

**On pre-market "open" timing:** The $80 P&L at open timing is a **simulation artifact**, not a real trading opportunity. Reasons:
1. Open-Meteo historical data is daily — the model forecast is identical regardless of when you look, so "open" and "9AM" use the same forecast values with different market prices.
2. At 10 PM the night before, there is no HGEFS cycle yet for the next day.
3. Spreads at open are 2–4× wider than mid-morning. The simulation doesn't model this.
4. The true informational advantage from entering early (before price corrects) is outweighed by execution costs.

**Verdict on pre-10 AM entries:** Not worth it. The apparent 4× P&L advantage vanishes when spreads and model vintage are properly accounted for. The AGENTS 11AM rule is correct.

**9AM vs 11AM:** 11AM gives slightly better Sharpe (0.087 vs 0.081) with comparable P&L. The code's pre-10 AM gate added in today's audit is correct.

---

## 7. Gate 1 Sensitivity

| Gate 1 spread_between max | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| No Gate 1 | 637 | 66.6% | $80.33 | 0.280 |
| 3.5°F (loose) | 521 | 56.6% | $13.87 | 0.057 |
| **2.5°F (current backtest)** | **460** | **57.6%** | **$17.38** | **0.081** |
| **1.5°F (live HGEFS rule)** | **334** | **57.8%** | **$15.29** | **0.099** |
| 1.0°F (very strict) | 246 | 56.9% | $10.56 | 0.091 |

The live Gate 1 (1.5°F between physics and AI) correctly filters 126 trades (27%) vs the backtest's looser 2.5°F. Win rate stays the same — those 126 trades are genuinely lower quality. The Sharpe improves slightly from 0.081 to 0.099. The live HGEFS gate is well-calibrated.

---

## 8. Gap Threshold Optimization

| Gap | Trades | Win% | Net P&L | Sharpe | WF P&L |
|---|---|---|---|---|---|
| >12pp | 565 | 57.3% | $18.26 | 0.069 | — |
| >15pp | 529 | 57.8% | $19.10 | 0.078 | — |
| **>20pp (current)** | **460** | **57.6%** | **$17.38** | **0.081** | **$20.21** |
| >24pp | 377 | 59.2% | $22.74 | 0.131 | — |
| >25pp | 353 | 57.5% | $19.08 | 0.116 | $18.30 |
| >30pp | 240 | 55.8% | $15.38 | 0.133 | $15.10 |

In-sample, 24pp shows the best P&L/Sharpe combination. But the walk-forward shows 20pp outperforms 25pp ($20.21 vs $18.30), meaning the 20pp threshold generalizes better to unseen data. **Keep 20pp.**

The 24pp in-sample peak is likely a mild overfit — it happens to align with the exact gap distribution of the historical data.

---

## 9. Dead Zone Analysis

| Dead zone | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| **35–40pp (current)** | **460** | **57.6%** | **$17.38** | **0.081** |
| No dead zone | 545 | 58.0% | $25.69 | 0.101 |
| Narrower 36–38pp | 511 | 57.9% | $23.20 | 0.098 |
| Wider 30–45pp | 289 | 56.7% | $8.00 | 0.060 |

Removing the dead zone adds $8.31 in this backtest. The 85 extra trades in the dead zone (35–40pp) win at 58% — positive P&L but with slightly lower Sharpe. 

**Caution:** The dead zone was added because the ORIGINAL ablation found "negative P&L in this zone." That ablation was on different data. Worth re-validating in forward paper data before removing, but this backtest no longer shows it as clearly negative.

---

## 10. Confidence Threshold

| Band | Trades | Win% | Net P&L | Sharpe |
|---|---|---|---|---|
| Bottom quartile | 115 | 53.0% | -$3.17 | -0.06 |
| Middle 50% | 230 | 58.7% | +$3.38 | 0.03 |
| Top quartile | 115 | 60.0% | **+$17.17** | **0.32** |
| Top decile | 46 | 52.2% | +$6.81 | 0.29 |

**Critical finding:** The top 25% of trades by confidence score generate ALL the profit (+$17.17). The bottom 25% loses money (-$3.17). The current paper minimum of 60 confidence is working correctly — it is targeting the high-confidence subset.

The current implementation (PAPER_CORE_MIN_CONFIDENCE = 60) is near-optimal. Raising to 65–70 would further improve Sharpe at the cost of fewer trades. This is a lever to pull if the paper account begins to draw down.

---

## Creative Scenario Matrix Summary

| Scenario | Trades | Win% | Net P&L | Sharpe | Verdict |
|---|---|---|---|---|---|
| Full gate1 + 55–75c band + 9AM | 206 | 78.6% | +$23.60 | 0.282 | **Best realistic config** |
| NO trades only + 55–75c band | 198 | 78.8% | +$22.68 | 0.282 | Structural alpha confirmed |
| 55–75c + gap>15pp | 240 | 77.1% | +$23.75 | 0.238 | Good, slightly more trades |
| strict gate1 (1.5F) + 55–75c | 143 | 80.4% | +$19.28 | 0.347 | Best Sharpe achievable |
| DEEP_TAIL_NO at 7% threshold | 587 | 86.4% | +$34.32 | 0.19 | Biggest absolute P&L gain |
| Wing_high only | 17 | 82.4% | +$3.51 | 0.56 | Best Sharpe — too few trades |
| Open timing (no vintage guard) | 637 | 66.6% | +$80.33 | 0.28 | **Artifact — not real** |
| Remove dead zone | 545 | 58.0% | +$25.69 | 0.10 | Needs WF validation |
| Exit at 0.70 ceiling | 231 hits | 53.5% | -$17.54 | -0.11 | Exit hurts (simulation only) |

---

## Priority Action List

### Implement Now (low risk, clear improvement)
1. **Raise `DEEP_TAIL_NO_PROB_MAX` 0.02 → 0.07** in `config.py` after 30-day paper validation
   - Expected: +$8 P&L per backtest period (+37%)
   - Sharpe: 0.19 (vs 0.23 current — slight decrease but absolute gain is large)

2. **Add paper policy: CORE entry price ≥ 0.55** in `paper_trader/config_paper.py`
   - New flag: `PAPER_CORE_MIN_ENTRY_PRICE = 0.55`
   - Expected: Sharpe 0.282 vs 0.081 (3.5×), +$6 P&L with fewer trades
   - Requires change in `paper_trader/policy.py` only — not live config

### Test in Paper (medium confidence, needs forward validation)
3. **Gap threshold fine-tune**: test 22–24pp vs current 20pp
   - In-sample advantage at 24pp, but walk-forward favors 20pp
   - Run both in parallel paper for 60 days to compare

4. **Dead zone re-validation**: the 35–40pp zone adds +$8 in this backtest
   - Log these trades separately in candidate_signals
   - Do NOT remove from live config until 60 days of paper data confirm

### Do NOT Change
5. **NEVER_HOLD_ABOVE = 0.70** — NWS tail risk eliminates any P&L gained from removing it
6. **TARGET_EXIT_PRICE = 0.68** — correct for locking profit before settlement
7. **Entry timing gate (10 AM minimum)** — pre-10 AM advantage is a simulation artifact
8. **Wing_low suspension** — confirmed losing in backtest (-$2.21, 48.6% win)
9. **MIN_GAP_PP = 20pp** — walk-forward shows this generalizes best

---

## Model Comparison Note (EMOS vs Gumbel)

The paper bakeoff (CLAUDE.md) shows EMOS dominates Gumbel:
- NYC EMOS: 91.7% win, +$13.20 | Gumbel: 58.6% win, +$3.33
- KMDW EMOS: 80.0% win, +$11.35 | Gumbel: 40.3% win, -$12.03

The DEEP_TAIL_NO opportunity and entry price band insights above apply to both models.
EMOS probability estimates will produce different gap_pp values — run the same band analysis
against EMOS paper trades as more data accumulates.

---

*Output files: `data/research/knyc_backtest_summary.json`, `data/research/strategy_variation_summary.json`,
`data/research/strategy_variation_exit_grid.csv`, `data/research/strategy_variation_sleeve_grid.csv`*
