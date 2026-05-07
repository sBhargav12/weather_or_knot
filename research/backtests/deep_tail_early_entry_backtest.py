"""DEEP_TAIL_NO Early Entry Backtest

Measures the PnL impact of entering DEEP_TAIL_NO at 10:15 AM ET the day before
the target date, shortly after the market opens, vs the actual entry time.

Methodology
-----------
For every DEEP_TAIL_NO trade in paper_trades:

1. Determine the "early check date": the day BEFORE the target date.  The
   _early_deep_tail_loop fires at 10:15 AM ET each day and checks only
   tomorrow's brackets.  So for a trade with target_date=2026-04-30, the early
   check fires at 10:15 AM on 2026-04-29.

2. Find the latest Kalshi price available by 10:15 AM ET on the day before the
   target date.

3. Check thresholds (YES >= 5¢, model_prob < 2%) — if YES is below 5¢ at
   10:15 AM, the early check would have correctly skipped the trade.

4. Compute hypothetical NO entry = 1 - yes_bid at 10:15 AM.

5. Apply the same exit outcome (exit_price, exit_reason) with the new entry
   to compute the hypothetical gross PnL.  Where the stop (entry - 0.40)
   shifts, we note it but do not adjust exit_price (conservative assumption).

6. Compare actual net PnL vs hypothetical net PnL.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[2] / "data" / "pipeline.db"

MAKER_FEE_RATE = 0.001   # $0.001 per contract per side
STOP_LOSS_DIFF = 0.40    # from config.py
DEEP_TAIL_YES_MIN = 0.05  # from config.py


def maker_fee(contracts: int) -> float:
    return round(contracts * MAKER_FEE_RATE, 4)


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    trades = conn.execute("""
        SELECT pt.id, pt.created_at, pt.ticker, pt.target_date,
               pt.entry_price, pt.exit_price, pt.exit_reason,
               pt.gross_pnl, pt.net_pnl_maker, pt.contracts,
               pt.maker_fee_entry, pt.maker_fee_exit,
               s.model_prob, s.market_price as sig_yes_price
        FROM paper_trades pt
        LEFT JOIN signals s ON pt.signal_id = s.id
        WHERE pt.strategy_sleeve = 'DEEP_TAIL_NO'
        ORDER BY pt.created_at
    """).fetchall()

    print("=" * 90)
    print("DEEP_TAIL_NO Early Entry Backtest  (actual vs 8:30 AM ET on TARGET DATE)")
    print("=" * 90)
    print()

    rows = []
    for t in trades:
        ticker      = t["ticker"]
        entry_utc   = t["created_at"]
        target_date = t["target_date"]          # use target date, not entry date
        actual_ep   = t["entry_price"]
        actual_xp   = t["exit_price"]
        contracts   = t["contracts"]
        actual_gross = t["gross_pnl"] or 0.0
        actual_net   = t["net_pnl_maker"] or 0.0
        exit_reason  = t["exit_reason"] or "OPEN"
        model_prob   = t["model_prob"] or 0.0

        # 8:30 AM ET = 12:30 UTC (EDT, UTC-4)
        early_utc = target_date + " 12:30:00"

        early_row = conn.execute("""
            SELECT yes_bid, no_ask, created_at
            FROM kalshi_prices
            WHERE ticker = ? AND created_at <= ?
            ORDER BY created_at DESC LIMIT 1
        """, (ticker, early_utc)).fetchone()

        # Also pull the intraday high for YES to understand market dynamics
        yes_high_row = conn.execute("""
            SELECT MAX(CAST(yes_bid AS REAL)) as yes_max
            FROM kalshi_prices
            WHERE ticker = ? AND created_at LIKE ?
        """, (ticker, target_date + "%")).fetchone()
        yes_intraday_max = yes_high_row["yes_max"] if yes_high_row else None

        def make_row(early_ep, early_gross, early_net, delta_gross, delta_net, note):
            return {
                "id": t["id"], "ticker": ticker,
                "entry_date": entry_utc[:10], "target_date": target_date,
                "actual_ep": actual_ep, "actual_xp": actual_xp,
                "actual_gross": actual_gross, "actual_net": actual_net,
                "early_ep": early_ep,
                "early_gross": early_gross, "early_net": early_net,
                "delta_gross": delta_gross, "delta_net": delta_net,
                "exit_reason": exit_reason, "note": note,
                "contracts": contracts, "model_prob": model_prob,
                "yes_intraday_max": yes_intraday_max,
            }

        if early_row is None:
            rows.append(make_row(None, None, None, None, None, "NO_DATA_AT_8:30"))
            continue

        yes_bid_early = float(early_row["yes_bid"]) if early_row["yes_bid"] else None

        if yes_bid_early is None:
            rows.append(make_row(None, None, None, None, None, "YES_BID_NULL"))
            continue

        # Filter: 5c YES minimum (same as live logic)
        if yes_bid_early < DEEP_TAIL_YES_MIN:
            early_ep = round(1.0 - yes_bid_early, 4)
            rows.append(make_row(early_ep, None, None, None, None,
                                 f"BELOW_5C_MIN (YES={yes_bid_early:.2f})"))
            continue

        early_ep = round(1.0 - yes_bid_early, 4)

        # Model prob still < 2%? (assume yes — same signal, same model)
        if model_prob >= 0.02:
            rows.append(make_row(early_ep, None, None, None, None,
                                 f"PROB_ABOVE_2PCT ({model_prob:.4f})"))
            continue

        note = ""
        if actual_xp is None:
            rows.append(make_row(early_ep, None, None, None, None, "OPEN_TRADE"))
            continue

        # Stop level shifts with new entry
        new_stop = early_ep - STOP_LOSS_DIFF
        hypo_xp = actual_xp
        if exit_reason == "STOP" and new_stop > 0 and actual_xp > new_stop:
            # Actual stop was lower than new stop → new stop fires first
            hypo_xp = new_stop
            note = "STOP_ADJUSTED_HIGHER"
        elif exit_reason == "STOP":
            note = "STOP_SAME"
        else:
            note = ""

        early_gross = round(contracts * (hypo_xp - early_ep), 4)
        fee_in  = maker_fee(contracts)
        fee_out = maker_fee(contracts)
        early_net = round(early_gross - fee_in - fee_out, 4)
        delta_gross = round(early_gross - actual_gross, 4)
        delta_net   = round(early_net   - actual_net,   4)

        rows.append(make_row(early_ep, early_gross, early_net,
                             delta_gross, delta_net, note))

    # ── Print trade-by-trade table ───────────────────────────────────────────
    print(f"{'ID':>4}  {'Ticker':<32}  {'Act EP':>7}  {'8:30 EP':>8}  "
          f"{'EP Δ':>7}  {'Act Gross':>9}  {'Hypo Gross':>10}  {'Δ Gross':>8}  "
          f"{'Exit':<16}  Note")
    print("-" * 120)

    total_actual_gross = 0.0
    total_actual_net   = 0.0
    total_hypo_gross   = 0.0
    total_hypo_net     = 0.0
    comparable_n = 0

    for r in rows:
        ep_delta   = f"{r['early_ep'] - r['actual_ep']:+.3f}" if r["early_ep"] else ""
        gross_delta = f"{r['delta_gross']:+.2f}" if r["delta_gross"] is not None else ""
        early_gross_s = f"{r['early_gross']:.2f}" if r["early_gross"] is not None else ""

        print(
            f"{r['id']:>4}  {r['ticker']:<32}  "
            f"{r['actual_ep']:>7.3f}  "
            f"{(r['early_ep'] or 0):>8.3f}  "
            f"{ep_delta:>7}  "
            f"{r['actual_gross']:>9.2f}  "
            f"{early_gross_s:>10}  "
            f"{gross_delta:>8}  "
            f"{r['exit_reason']:<16}  {r['note']}"
        )

        total_actual_gross += r["actual_gross"]
        total_actual_net   += r["actual_net"]
        if r["early_gross"] is not None:
            total_hypo_gross += r["early_gross"]
            total_hypo_net   += r["early_net"]
            comparable_n += 1
        else:
            # carry actual forward for total comparison
            total_hypo_gross += r["actual_gross"]
            total_hypo_net   += r["actual_net"]

    print("-" * 120)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Trades total             : {len(rows)}")
    print(f"  Comparable (full sim)    : {comparable_n}")
    print()
    print(f"  Actual   gross PnL (all) : ${total_actual_gross:+.2f}")
    print(f"  Actual   net   PnL (all) : ${total_actual_net:+.2f}")
    print()
    print(f"  8:30 AM  gross PnL (all) : ${total_hypo_gross:+.2f}")
    print(f"  8:30 AM  net   PnL (all) : ${total_hypo_net:+.2f}")
    print()
    print(f"  Net delta (gross)        : ${total_hypo_gross - total_actual_gross:+.2f}")
    print(f"  Net delta (net fees)     : ${total_hypo_net   - total_actual_net:+.2f}")

    # ── Intraday YES dynamics ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("Intraday YES bid dynamics on target date:")
    print(f"  {'ID':>4}  {'Ticker':<32}  {'YES 8:30AM':>10}  {'YES at entry':>13}  "
          f"{'YES intraday max':>16}  {'Dynamics'}")
    print("  " + "-" * 80)
    for r in rows:
        yes_8 = round(1 - r["early_ep"], 3) if r["early_ep"] else None
        yes_e = round(1 - r["actual_ep"], 3)
        mx    = r["yes_intraday_max"]
        if yes_8 and mx:
            dyn = "YES peaked AFTER entry (early better)" if yes_e > (yes_8 or 0) else \
                  "YES peaked BEFORE entry (waiting better)"
        else:
            dyn = "—"
        print(f"  {r['id']:>4}  {r['ticker']:<32}  "
              f"{(yes_8 or 0):>10.3f}  {yes_e:>13.3f}  "
              f"{(mx or 0):>16.3f}  {dyn}")

    print(f"\n{'='*90}")
    print("Key insight: DEEP_TAIL_NO profits from market OVERpricing of tails.")
    print("Early entry captures the signal sooner but may miss peak mispricing.")
    print("Later entry when YES is highest = cheapest NO entry = better risk/reward.")


if __name__ == "__main__":
    run()
