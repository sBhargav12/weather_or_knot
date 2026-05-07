"""
DEEP_TAIL_NO Timing Backtest
============================
Buy NO contracts when model P(YES) < 2% but the YES market price > 5¢.
Compare entry timing: open, 9AM, 11AM, 1PM.

Run: uv run python research/backtests/deep_tail_timing_backtest.py
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PRED_CSV = Path("data/research/model_bakeoff_predictions.csv")
PRICE_CSV = Path("data/kxhighny_prices.csv")

PROB_THRESHOLD = 0.02       # model P(YES) must be below this
MIN_YES_PRICE = 0.05        # YES price at entry must be above this (mispricing)
STAKE = 15.0                # dollars per trade
STOP_LOSS_DIFF = 0.40       # stop fires: no_entry - STOP_LOSS_DIFF
MAKER_FEE_RATE = 0.001      # per contract per side

ENTRY_TIMES = ["open", "9AM", "11AM", "1PM"]
PRICE_COLS = {
    "open": "yes_price_open",
    "9AM":  "yes_price_9AM",
    "11AM": "yes_price_11AM",
    "1PM":  "yes_price_1PM",
}

FOCUS_MODELS = ["EMOS", "GUMBEL"]   # primary + secondary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_trade(no_entry: float, win: bool) -> dict:
    """Compute PnL for a single NO trade."""
    contracts = max(1, math.floor(STAKE / no_entry))
    if win:
        gross_pnl = contracts * (1.0 - no_entry)
        exit_price = 1.0
    else:
        stop_price = max(0.0, no_entry - STOP_LOSS_DIFF)
        gross_pnl = contracts * (stop_price - no_entry)
        exit_price = stop_price

    maker_fee_entry = contracts * MAKER_FEE_RATE * no_entry
    maker_fee_exit  = contracts * MAKER_FEE_RATE * exit_price
    net_pnl = gross_pnl - maker_fee_entry - maker_fee_exit

    return {
        "contracts": contracts,
        "no_entry": no_entry,
        "gross_pnl": gross_pnl,
        "maker_fee_entry": maker_fee_entry,
        "maker_fee_exit": maker_fee_exit,
        "net_pnl": net_pnl,
        "win": win,
    }


def sharpe(series: pd.Series) -> float:
    """Annualised Sharpe assuming 252 trading days."""
    if len(series) < 2 or series.std() == 0:
        return float("nan")
    return (series.mean() / series.std()) * math.sqrt(252)


def print_separator(char="─", width=90):
    print(char * width)


# ---------------------------------------------------------------------------
# Load & join
# ---------------------------------------------------------------------------

def load_data():
    pred = pd.read_csv(PRED_CSV)
    prices = pd.read_csv(PRICE_CSV)

    # Rename pred date column; drop the predictions-file's yes_price_9AM snapshot
    # (we use only the intraday price file's prices for all four entry times)
    pred = pred.rename(columns={"date": "target_date"})
    if "yes_price_9AM" in pred.columns:
        pred = pred.drop(columns=["yes_price_9AM"])

    # Keep only the columns we need from the price file
    price_cols = ["ticker", "target_date", "yes_price_open",
                  "yes_price_9AM", "yes_price_11AM", "yes_price_1PM"]
    prices_slim = prices[price_cols].copy()

    # Join on ticker — pred has one row per ticker×model, prices has one row per ticker
    merged = pred.merge(
        prices_slim,
        on="ticker",
        how="inner",
        suffixes=("_pred", "_price"),
    )

    # Resolve any remaining target_date collision
    if "target_date_pred" in merged.columns:
        merged = merged.drop(columns=["target_date_pred"])
        merged = merged.rename(columns={"target_date_price": "target_date"})

    return merged


# ---------------------------------------------------------------------------
# Core backtest loop
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, model: str, entry_time: str) -> pd.DataFrame:
    """Return trade-level DataFrame for one model × entry_time combo."""
    price_col = PRICE_COLS[entry_time]
    subset = df[df["model_name"] == model].copy()
    subset = subset.dropna(subset=[price_col])

    # Signal filter
    subset = subset[
        (subset["probability"] < PROB_THRESHOLD) &
        (subset[price_col] > MIN_YES_PRICE)
    ].copy()

    if subset.empty:
        return pd.DataFrame()

    trades = []
    for _, row in subset.iterrows():
        yes_price = float(row[price_col])
        no_entry = 1.0 - yes_price
        if no_entry <= 0:
            continue
        # kalshi_result_yes == False means bracket did NOT settle YES → WIN for NO buyer
        win = not bool(row["kalshi_result_yes"])
        t = compute_trade(no_entry, win)
        t["ticker"]      = row["ticker"]
        t["target_date"] = row["target_date"]
        t["model"]       = model
        t["entry_time"]  = entry_time
        t["yes_price_entry"] = yes_price
        t["probability"] = row["probability"]
        trades.append(t)

    return pd.DataFrame(trades)


def aggregate(trades_df: pd.DataFrame) -> dict:
    if trades_df.empty:
        return {
            "trades": 0, "win_rate": float("nan"),
            "total_net_pnl": 0.0, "avg_no_entry": float("nan"),
            "sharpe": float("nan"),
        }
    return {
        "trades":        len(trades_df),
        "win_rate":      trades_df["win"].mean(),
        "total_net_pnl": trades_df["net_pnl"].sum(),
        "avg_no_entry":  trades_df["no_entry"].mean(),
        "sharpe":        sharpe(trades_df["net_pnl"]),
    }


# ---------------------------------------------------------------------------
# YES price drift analysis
# ---------------------------------------------------------------------------

def price_drift_analysis(df: pd.DataFrame, model: str):
    """
    For tail signals (prob < 0.02, yes_price_open > 0.05),
    show how YES prices move open→9AM→11AM→1PM for WIN vs LOSS outcomes.
    """
    subset = df[df["model_name"] == model].copy()
    subset = subset.dropna(subset=["yes_price_open", "yes_price_9AM",
                                   "yes_price_11AM", "yes_price_1PM"])
    subset = subset[
        (subset["probability"] < PROB_THRESHOLD) &
        (subset["yes_price_open"] > MIN_YES_PRICE)
    ].copy()

    if subset.empty:
        return None

    # WIN = bracket did NOT settle YES (kalshi_result_yes == False)
    subset["outcome"] = subset["kalshi_result_yes"].apply(
        lambda x: "LOSS (bracket hit)" if bool(x) else "WIN (bracket missed)"
    )

    cols = ["yes_price_open", "yes_price_9AM", "yes_price_11AM", "yes_price_1PM"]
    result = subset.groupby("outcome")[cols].mean()
    counts = subset.groupby("outcome").size().rename("n")
    result = result.join(counts)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print("=" * 90)
    print("  DEEP_TAIL_NO TIMING BACKTEST")
    print("  Signal: model P(YES) < 2%  AND  YES market price > 5¢")
    print(f"  Stake: ${STAKE:.0f}/trade  |  Stop-loss diff: {STOP_LOSS_DIFF}  |  Maker fee: {MAKER_FEE_RATE}/contract/side")
    print("=" * 90)

    df = load_data()
    print(f"\nLoaded {len(df):,} rows after join  "
          f"(predictions: {PRED_CSV.name}, prices: {PRICE_CSV.name})")

    # -----------------------------------------------------------------------
    # 1. Main results table
    # -----------------------------------------------------------------------
    print()
    print_separator()
    print("  RESULTS BY MODEL × ENTRY TIME")
    print_separator()

    all_trades: list[pd.DataFrame] = []
    results_rows = []

    for model in FOCUS_MODELS:
        for entry_time in ENTRY_TIMES:
            trades_df = run_backtest(df, model, entry_time)
            all_trades.append(trades_df)
            agg = aggregate(trades_df)
            results_rows.append({
                "model":        model,
                "entry_time":   entry_time,
                **agg,
            })

    results = pd.DataFrame(results_rows)

    header = f"{'Model':<14} {'Entry':<7} {'Trades':>7} {'Win%':>7} {'Net PnL':>10} {'Avg NO':>9} {'Sharpe':>8}"
    print(header)
    print_separator("·")
    for _, row in results.iterrows():
        win_str    = f"{row['win_rate']*100:.1f}%" if not math.isnan(row['win_rate']) else "  n/a"
        pnl_str    = f"${row['total_net_pnl']:+.2f}"
        avg_str    = f"{row['avg_no_entry']:.3f}" if not math.isnan(row['avg_no_entry']) else "  n/a"
        sharpe_str = f"{row['sharpe']:.2f}"       if not math.isnan(row['sharpe'])      else "  n/a"
        print(f"{row['model']:<14} {row['entry_time']:<7} {int(row['trades']):>7} "
              f"{win_str:>7} {pnl_str:>10} {avg_str:>9} {sharpe_str:>8}")

    # -----------------------------------------------------------------------
    # 2. Early vs late delta PnL
    # -----------------------------------------------------------------------
    print()
    print_separator()
    print("  EARLY ENTRY (open / 9AM) vs LATE ENTRY (11AM) — DELTA PnL")
    print_separator()

    for model in FOCUS_MODELS:
        sub = results[results["model"] == model].set_index("entry_time")
        early_times = [t for t in ["open", "9AM"] if t in sub.index and sub.loc[t, "trades"] > 0]
        late_times  = [t for t in ["11AM"]        if t in sub.index and sub.loc[t, "trades"] > 0]

        if not early_times or not late_times:
            print(f"  {model}: insufficient data for comparison")
            continue

        # Restrict to tickers that appear in all compared buckets (apples-to-apples)
        for late_t in late_times:
            for early_t in early_times:
                t_early = run_backtest(df, model, early_t)
                t_late  = run_backtest(df, model, late_t)
                if t_early.empty or t_late.empty:
                    continue
                common = set(t_early["ticker"]) & set(t_late["ticker"])
                e_pnl = t_early[t_early["ticker"].isin(common)]["net_pnl"].sum()
                l_pnl = t_late [t_late ["ticker"].isin(common)]["net_pnl"].sum()
                delta = e_pnl - l_pnl
                n     = len(common)
                sign  = "BETTER" if delta > 0 else "WORSE"
                print(f"  {model} | {early_t} vs {late_t} | common tickers: {n:>4} | "
                      f"early PnL: ${e_pnl:+.2f}  late PnL: ${l_pnl:+.2f}  "
                      f"delta: ${delta:+.2f} ({sign} earlier)")

    # -----------------------------------------------------------------------
    # 3. YES price drift: winners vs losers
    # -----------------------------------------------------------------------
    print()
    print_separator()
    print("  YES PRICE DRIFT  (open → 9AM → 11AM → 1PM)")
    print("  For tail signals: do LOSING brackets spike late in the day?")
    print_separator()

    for model in FOCUS_MODELS:
        drift = price_drift_analysis(df, model)
        if drift is None:
            print(f"  {model}: no data")
            continue

        print(f"\n  Model: {model}")
        col_labels = ["open", "9AM", "11AM", "1PM", "n"]
        header2 = f"  {'Outcome':<30} " + " ".join(f"{c:>7}" for c in col_labels)
        print(header2)
        print("  " + "·" * 68)
        for outcome, row in drift.iterrows():
            vals = [f"{row[c]:>7.3f}" for c in
                    ["yes_price_open", "yes_price_9AM", "yes_price_11AM", "yes_price_1PM"]]
            vals.append(f"{int(row['n']):>7}")
            print(f"  {outcome:<30} " + " ".join(vals))

        # Directional comment
        if len(drift) == 2:
            loss_rows = [r for o, r in drift.iterrows() if "LOSS" in o]
            win_rows  = [r for o, r in drift.iterrows() if "WIN"  in o]
            if loss_rows and win_rows:
                lr, wr = loss_rows[0], win_rows[0]
                loss_drift = lr["yes_price_1PM"] - lr["yes_price_open"]
                win_drift  = wr["yes_price_1PM"] - wr["yes_price_open"]
                print()
                if loss_drift > 0.02:
                    print(f"  ⚑  LOSERS drift YES price +{loss_drift:.3f} open→1PM "
                          f"(market pricing in risk late) — earlier entry AVOIDS this spike.")
                elif loss_drift < -0.02:
                    print(f"  ⚑  LOSERS drift YES price {loss_drift:.3f} open→1PM "
                          f"(market pushing YES down before reversal).")
                else:
                    print(f"  ⚑  LOSERS YES price roughly flat open→1PM ({loss_drift:+.3f}).")
                if win_drift < -0.02:
                    print(f"     WINNERS fade YES price {win_drift:.3f} open→1PM "
                          f"(market correctly marking brackets down).")

    # -----------------------------------------------------------------------
    # 4. Best single entry time summary
    # -----------------------------------------------------------------------
    print()
    print_separator()
    print("  BEST ENTRY TIME SUMMARY (by total net PnL, min 5 trades)")
    print_separator()

    for model in FOCUS_MODELS:
        sub = results[(results["model"] == model) & (results["trades"] >= 5)].copy()
        if sub.empty:
            print(f"  {model}: no entry time has ≥5 trades")
            continue
        best = sub.loc[sub["total_net_pnl"].idxmax()]
        print(f"  {model}: best entry = {best['entry_time']:<5}  "
              f"PnL ${best['total_net_pnl']:+.2f}  "
              f"({int(best['trades'])} trades, {best['win_rate']*100:.1f}% WR, "
              f"Sharpe {best['sharpe']:.2f})")

    print()
    print_separator()
    print("  END OF DEEP_TAIL_NO TIMING BACKTEST")
    print_separator()
    print()


if __name__ == "__main__":
    # Ensure we run from repo root regardless of cwd
    repo_root = Path(__file__).resolve().parents[2]
    import os
    os.chdir(repo_root)
    main()
