# Kalshi Weather Strategy Research Report
**Date:** 2026-05-03 | **Eval period:** 108 days (2026 KXHIGHNY) | **Data window:** 2024-10 → 2026-04

---

## Executive Summary

Three highest-impact, immediately implementable changes:

| # | Recommendation | Expected Sharpe | Win Rate | Est. Annual PnL |
|---|---------------|-----------------|----------|-----------------|
| 1 | Dual-model sleeve: EMOS + EMOS_GUMBEL_HETERO (consensus trades) | ~0.87 | 87.5% | $60–$110 |
| 2 | Adopt `report7_strict_selection` policy thresholds | 0.346 | 80.0% | +$37 at 3c stress |
| 3 | January + December CORE blackout | 0.260 | 79.6% | +$20/period |

---

## 1. Model Rankings (v2 Bakeoff, 108 days)

| Model | Brier | Sharpe | Win Rate | PnL | Trades | Max DD |
|-------|-------|--------|----------|-----|--------|--------|
| **EMOS** | 0.0907 | **0.835** | **85.1%** | $19.07 | 67 | −$0.97 |
| **EMOS_GUMBEL_HETERO** | **0.0865** | 0.789 | 83.5% | **$23.94** | 85 | −$1.01 |
| EMOS_GUMBEL | 0.0898 | 0.767 | 82.9% | $18.33 | 70 | −$1.01 |
| SEASONAL_EMOS | 0.0845 | 0.645 | 80.6% | $17.27 | 72 | −$0.97 |
| NGBOOST_GUMBEL | 0.1050 | 0.450 | 74.4% | $17.78 | 90 | −$2.87 |
| **GUMBEL (current live)** | 0.1694 | **−0.063** | 50.5% | −$3.09 | 105 | −$7.22 |

**Action:** Retire GUMBEL as primary live model. Promote EMOS_GUMBEL_HETERO.

**Dual-model consensus (EMOS ∩ EMOS_GUMBEL_HETERO):**
- 48 consensus trades → 87.5% win rate
- Return correlation: 0.493 (genuine diversification)
- Recommended sizing: 100% on consensus, 60% on single-model-only trades

---

## 2. Policy Stress Test Results

| Policy | Trades | Win Rate | Sharpe | Max DD | PnL @3c |
|--------|--------|----------|--------|--------|---------|
| current_strategy | 973 | 74.5% | 0.152 | −$16.85 | **−$2.61** |
| paper_net_edge_sized | 842 | 71.1% | 0.257 | −$5.35 | +$24.92 |
| report7_lower_tail_caution | 761 | 73.3% | 0.217 | −$11.60 | +$18.25 |
| **report7_strict_selection** | **589** | **80.0%** | **0.346** | **−$6.15** | **+$36.55** |

The current strategy goes negative at 3c adverse execution. `report7_strict_selection` remains profitable at +12.99 even at 5c adverse execution. It is strictly dominating.

**Key strict_selection characteristics:**
- Avg gap: 28.4pp (vs 26.0pp current)
- DEEP_TAIL_NO: 336/589 trades, 92.3% win rate
- CORE: 253 trades, 63.6% win rate, +$31.82

---

## 3. Loss Root Causes

**Top loss patterns:**
1. CORE YES at 45–65c entry price — near-model bets with no edge: **−$34.82**
2. January/December CORE trades: −$22.78, 50% win rate
3. CORE confidence < 60: +$9.13 improvement if filtered
4. Settlement mismatches: +$19.56 improvement if filtered

**Five additive loss filters (estimated +$57 in backtest, ~$30–40 annualized):**

| Filter | Implementation | PnL Impact |
|--------|---------------|------------|
| Jan + Dec CORE blackout | `if month in [1, 12]: skip_core` | +$20.15 |
| Settlement mismatch filter | Use existing `settlement_mismatch` DB flag | +$19.56 |
| CORE confidence ≥ 60 | Gate 2/3 threshold | +$9.13 |
| Avoid CORE entry 45–65c | Pre-entry price band guard | +$6.30 |
| Skip CORE wing_low entirely | Direction filter | +$2.21 |

---

## 4. Parameter Grid Search Findings (36,000 combinations)

Stable, reproducible signals across 2,233+ variants:

| Parameter | Best Value | Key Insight |
|-----------|-----------|-------------|
| `family` | `wing_high` | Wing-high NO: 0.513 median Sharpe vs wing_low −0.121 |
| `gap_threshold` | 30–40pp | Stable Sharpe 0.133 at 30pp vs 0.026 at 5pp |
| `directions` | `NO only` | NO trades: 2× Sharpe of YES trades |
| `price_band` | `15_85` | Wider band: 0.128 vs narrow band 0.056 |

**Actionable:** Raise `gap_threshold` to 30pp. Prioritize NO direction in CORE sleeve. Skip CORE YES when entry is 45–65c.

---

## 5. KNYC vs KMDW

| Metric | KNYC | KMDW |
|--------|------|------|
| Overall win rate | 72.4% | 66.3% |
| Net PnL | **+$58.19** | **−$8.58** |
| CORE win rate | 57.6% | **47.0%** |
| CORE net PnL | +$17.38 | **−$39.53** |
| DEEP_TAIL_NO win rate | 89.7% | 88.8% |
| DEEP_TAIL_NO PnL | +$31.86 | +$34.88 |

**KMDW CORE has never been profitable.** DEEP_TAIL_NO is strong (88.8%) on both cities.

**KMDW YES trades: 27.6% win rate, −$13.83 — disable immediately.**

**KMDW recommendation:** Run DEEP_TAIL_NO only until EMOS_GUMBEL_HETERO is validated for Chicago (KMDW EMOS backtest Sharpe: 0.71 vs legacy Gumbel −0.37).

---

## 6. Polymarket Alpha Signals

**Timing alpha (NYC markets):**
- 0–1 hour before close: +47.5pp 1-day markout (21 trades) — smart money signal
- 1–6 hours before: +3.6pp (not actionable)
- Caveat: Polymarket settles KLGA, Kalshi settles KNYC — use as soft signal only

**No front-running alpha available:** Top Polymarket wallets are resolution specialists (trading after settlement), not weather forecasters. Don't copy their direction signals.

**Cross-venue accuracy:**
- `range` NYC markets: 77.5% directional accuracy
- `exact_temp` markets: 28.1% — contrarian indicator

---

## 7. Orderbook Execution Analysis (Predexon, Jan 2026)

- Median spread (15–85c zone): **3c**, 98.1% valid two-sided quotes
- Mean bid depth: 4,587 contracts — ample liquidity for 100-contract orders
- **Do not exceed 200 contracts/bracket** (>4% of depth, market impact risk)
- **Filter: skip brackets with spread > 4c at entry time** (saves ~26% worst entries)

Tightest brackets (best execution): deep wings (38–43c, 57–62c), not near-consensus.
Near-consensus brackets (within ±2°F of forecast): systematically wider spreads (4.5–5.7c).

---

## 8. Implementation Priority Order

1. **Immediate:** Disable KMDW CORE sleeve and all KMDW YES trades
2. **Immediate:** Add January + December CORE blackout in `paper_trader/policy.py`
3. **Short-term:** Promote EMOS_GUMBEL_HETERO sleeve; retire GUMBEL as primary
4. **Short-term:** Raise gap_threshold to 30pp in production gate config
5. **Short-term:** Add CORE entry price 45–65c guard (skip near-market CORE bets)
6. **Medium-term:** Implement dual-model consensus sizing (100% vs 60% tiers)
7. **Medium-term:** Add orderbook spread filter (>4c → skip) at entry time
8. **Research:** Validate EMOS_GUMBEL_HETERO on KMDW with real data before enabling

---

## Risk Notes

- **Execution risk:** Strict selection survives to 5c adverse; current strategy fails at 3c. Priority fix.
- **Overfitting:** Jan/Dec blackout and gap_threshold improvements are based on 1–2 year samples. Apply to CORE only; keep DEEP_TAIL_NO running year-round.
- **HETERO win rate:** 87.5% consensus rate based on 48 trades — treat 85% as the real expectation.
- **KMDW EMOS validation:** 80% win rate in backtest; needs 30-day paper validation before live CORE use.
