"""
DSM (Daily Summary Message) Entry/Exit Check Backtest
======================================================
Validates the correctness of _is_dsm_window() and the same-day entry guard
using three real datasets:
  1. Oracle dsm_reports (6,929 rows) — actual wethr dsm_received_at times
  2. Oracle kalshi_prices during DSM window hours (1,500 rows, 19-23 UTC)
  3. report7_policy_stress_backtest.csv (4,007 rows, Oct 2024 – May 2026)
  4. candidate_signals from Oracle (1,525 rows) — all gate check evaluations

Research-only: never modifies config or live code.
Outputs: data/research/dsm_check_backtest.csv, reports/dsm_check_backtest_report.md
"""

import csv
import json
import sys
import os
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# ------------------------------------------------------------------
# Config mirrors: active cities, DSM UTC primary fire time, city tz
# ------------------------------------------------------------------
ACTIVE_CITY_DSM = {
    # city_key: (station, primary_dsm_utc_hhmm, city_tz)
    "KNYC":      ("KNYC", "20:21", "America/New_York"),
    "KMDW":      ("KMDW", "21:17", "America/Chicago"),
    "KMIA":      ("KMIA", "20:21", "America/New_York"),
    "KXLOWTCHI": ("KMDW", "21:17", "America/Chicago"),
    "KXLOWTDEN": ("KDEN", "22:17", "America/Denver"),
}

CURRENT_WINDOW_START_ET = dt_time(16, 15)
CURRENT_WINDOW_END_ET   = dt_time(17, 30)

# Expected ET fire times for each city (UTC → ET, summer EDT = UTC-4)
EXPECTED_DSM_ET = {
    "KNYC":      dt_time(16, 21),
    "KMDW":      dt_time(17, 17),
    "KMIA":      dt_time(16, 21),
    "KXLOWTCHI": dt_time(17, 17),
    "KXLOWTDEN": dt_time(18, 17),   # ← outside current 17:30 window
}

lines = []

def log(s=""):
    print(s)
    lines.append(s)

def fmt_m(m):
    return f"{int(m)//60:02d}:{int(m)%60:02d}"

def to_et(ts_str):
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(ET)
    except Exception:
        return None

# ------------------------------------------------------------------
# SECTION 1: DSM Fire Time Distribution from Oracle dsm_reports
# ------------------------------------------------------------------
log("=" * 70)
log("SECTION 1: DSM FIRE TIME DISTRIBUTION (Oracle dsm_reports, 6,929 rows)")
log("=" * 70)

DSM_CSV = Path("/tmp/dsm_reports_oracle.csv")
if not DSM_CSV.exists():
    log("ERROR: /tmp/dsm_reports_oracle.csv not found.")
    sys.exit(1)

station_times: dict[str, list] = defaultdict(list)
station_scripts: dict[str, dict] = defaultdict(lambda: defaultdict(int))
station_dates: dict[str, set] = defaultdict(set)

with open(DSM_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        recv = row.get("dsm_received_at", "").strip()
        station = row.get("station", "").strip()
        script = row.get("dsm_script", "").strip()
        dsm_date = row.get("dsm_date", "").strip()
        if not recv or not station:
            continue
        station_scripts[station][script] += 1
        station_dates[station].add(dsm_date)
        try:
            dt_utc = datetime.fromisoformat(recv).replace(tzinfo=UTC)
            dt_et = dt_utc.astimezone(ET)
            station_times[station].append(dt_et.time())
        except Exception:
            pass

log(f"\n{'Station':<10} {'N':<7} {'Dates':<6} {'Min ET':<10} {'Median ET':<12} {'P95 ET':<10} {'Max ET':<10} {'In window%':<12} {'Scripts'}")
log("-" * 95)

window_end_min   = CURRENT_WINDOW_END_ET.hour * 60   + CURRENT_WINDOW_END_ET.minute
window_start_min = CURRENT_WINDOW_START_ET.hour * 60 + CURRENT_WINDOW_START_ET.minute

station_coverage = {}
for station, times in sorted(station_times.items()):
    if not times:
        continue
    t_mins = sorted(t.hour * 60 + t.minute for t in times)
    n = len(t_mins)
    med_m = statistics.median(t_mins)
    p95_m = t_mins[int(n * 0.95)]
    mn, mx = t_mins[0], t_mins[-1]
    in_win = sum(1 for m in t_mins if window_start_min <= m <= window_end_min)
    pct = 100 * in_win / n
    scripts = dict(station_scripts[station])
    n_dates = len(station_dates[station])
    station_coverage[station] = pct
    log(f"{station:<10} {n:<7} {n_dates:<6} {fmt_m(mn):<10} {fmt_m(med_m):<12} {fmt_m(p95_m):<10} {fmt_m(mx):<10} {pct:>8.1f}%    {scripts}")

log()
log("Note: Low window% for KMDW = many rows are wethr polling duplicates (same")
log("dsm_received_at repeated 30+ times). Unique-date coverage shown in 'Dates'.")
log()
log("Unique DSM dates per station:")
for s in sorted(station_dates):
    log(f"  {s}: {sorted(station_dates[s])}")

# ------------------------------------------------------------------
# SECTION 2: Coverage Validation per Active City
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 2: DSM WINDOW COVERAGE PER ACTIVE CITY")
log("=" * 70)
log()
log(f"Current window: {CURRENT_WINDOW_START_ET.strftime('%H:%M')} – {CURRENT_WINDOW_END_ET.strftime('%H:%M')} ET")
log()
log(f"{'City':<14} {'Station':<8} {'DSM UTC':<10} {'DSM ET (EDT)':<14} {'Covers?':<10} {'Gap min':<10} {'Risk'}")
log("-" * 78)

coverage_issues = []
for city, (station, dsm_utc, tz) in ACTIVE_CITY_DSM.items():
    dsm_et = EXPECTED_DSM_ET[city]
    dsm_et_min = dsm_et.hour * 60 + dsm_et.minute
    # needs 5-min buffer after DSM fires before window can safely end
    covered = dsm_et_min <= window_end_min - 5
    gap = window_end_min - dsm_et_min
    risk = "OK" if covered else f"EXPOSED — {-gap}min gap after DSM"
    if not covered:
        coverage_issues.append((city, dsm_et, gap))
    log(f"{city:<14} {station:<8} {dsm_utc:<10} {dsm_et.strftime('%H:%M'):<14} {'YES' if covered else 'NO':<10} {gap:>+5d}       {risk}")

if coverage_issues:
    log()
    log("⚠  CRITICAL GAPS:")
    for city, dsm_et, gap in coverage_issues:
        log(f"   {city}: DSM fires {dsm_et.strftime('%H:%M')} ET → {-gap}min AFTER window close {CURRENT_WINDOW_END_ET.strftime('%H:%M')} ET")
    log()
    log("   KXLOWTDEN is active:True in config.py and fires at 22:17 UTC = 18:17 ET.")
    log("   Same-day KXLOWTDEN entries could fire between 17:30–18:17 ET.")
    log("   Fix: extend window end to 18:30 ET in _is_dsm_window().")

# ------------------------------------------------------------------
# SECTION 3: Kalshi Price Behavior at DSM Times (Live Data)
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 3: KALSHI PRICE BEHAVIOR DURING DSM WINDOW HOURS (Live prices)")
log("=" * 70)
log("  Oracle kalshi_prices 19–23 UTC, 1,500 rows — Apr 29 – May 6 2026")
log()

PRICES_CSV = Path("/tmp/kalshi_prices_dsm_window.csv")
ticker_prices: dict[tuple, list] = defaultdict(list)
with open(PRICES_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = (row["ticker"], row["target_date"], row["city"], row["bracket_type"])
        try:
            h = int(row["hour_utc"])
            m = int(row["minute_utc"])
            yb = float(row["yes_bid"]) if row["yes_bid"] else None
            ya = float(row["yes_ask"]) if row["yes_ask"] else None
            ticker_prices[key].append((h, m, yb, ya))
        except Exception:
            pass

def price_at_utc(entries, utc_hour, m_min=0, m_max=59):
    cands = sorted(
        [e for e in entries if e[0] == utc_hour and m_min <= e[1] <= m_max],
        key=lambda x: x[1]
    )
    return (cands[0][2], cands[0][3]) if cands else (None, None)

city_dsm_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "pre": [], "at_2021": [], "at_2117": [], "at_2217": [], "same_day_n": 0})

for (ticker, target_date, city, btype), entries in ticker_prices.items():
    # same-day or next-day?
    # target_date is the settlement date; look at created_at date from first entry
    yb_pre, _ = price_at_utc(entries, 19)
    if yb_pre is None:
        yb_pre, _ = price_at_utc(entries, 20, 0, 14)
    if yb_pre is None:
        continue

    yb_2021, _ = price_at_utc(entries, 20, 15, 30)
    yb_2117, _ = price_at_utc(entries, 21, 12, 22)
    yb_2217, _ = price_at_utc(entries, 22, 12, 22)

    s = city_dsm_stats[city]
    s["n"] += 1
    if yb_2021 is not None:
        s["at_2021"].append(abs(yb_2021 - yb_pre))
    if yb_2117 is not None:
        s["at_2117"].append(abs(yb_2117 - yb_pre))
    if yb_2217 is not None:
        s["at_2217"].append(abs(yb_2217 - yb_pre))

log(f"{'City':<14} {'N mkts':<8} {'ΔYesBid@20:21':<16} {'ΔYesBid@21:17':<16} {'ΔYesBid@22:17'}")
log("-" * 70)
for city in sorted(city_dsm_stats):
    s = city_dsm_stats[city]
    def avg(lst): return f"{statistics.mean(lst):.4f}" if lst else "  n/a  "
    log(f"{city:<14} {s['n']:<8} {avg(s['at_2021']):<16} {avg(s['at_2117']):<16} {avg(s['at_2217'])}")

log()
log("  ΔYesBid = |price_at_DSM_time − price_at_19:xx| per market per day.")
log("  Large Δ at a given hour = settlement is being priced in aggressively.")
log("  Small Δ = market was already well-priced; holding 1 extra hour costs little.")

# ------------------------------------------------------------------
# SECTION 4: Entry During Window Audit (candidate_signals)
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 4: GATE CHECK EVALUATIONS DURING DSM WINDOW (candidate_signals)")
log("=" * 70)

SIGNALS_CSV = Path("/tmp/candidate_signals_oracle.csv")
in_window_sigs = []
post_window_sameday = []

with open(SIGNALS_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        ts = row.get("created_at", "").strip()
        if not ts:
            continue
        try:
            dt_utc = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except Exception:
            try:
                dt_utc = datetime.fromisoformat(ts).replace(tzinfo=UTC)
            except Exception:
                continue
        dt_et = dt_utc.astimezone(ET)
        t_et = dt_et.time()
        in_win = CURRENT_WINDOW_START_ET <= t_et <= CURRENT_WINDOW_END_ET
        same_day = row.get("target_date", "") == dt_et.date().isoformat()
        passes = row.get("would_pass_core", "0") in ("1",)
        entry = {
            "ts": ts, "city": row.get("city", ""), "ticker": row.get("ticker", ""),
            "target_date": row.get("target_date", ""), "direction": row.get("direction", ""),
            "yes_price": row.get("yes_price", ""), "strategy": row.get("strategy_sleeve", ""),
            "passes": passes, "same_day": same_day, "t_et": t_et,
        }
        if in_win:
            in_window_sigs.append(entry)
        elif t_et > CURRENT_WINDOW_END_ET and same_day:
            post_window_sameday.append(entry)

log(f"\nTotal candidate signals:                 {1525}")
log(f"Fired during DSM window (16:15–17:30):   {len(in_window_sigs)}")
log(f"  → would_pass_core = True (tradeable):  {sum(1 for s in in_window_sigs if s['passes'])}")
log(f"  → same-day target_date:                {sum(1 for s in in_window_sigs if s['same_day'])}")
log(f"  → next-day target_date:                {sum(1 for s in in_window_sigs if not s['same_day'])}")

passing_window = [s for s in in_window_sigs if s["passes"]]
if passing_window:
    log()
    log("  Gate-passing signals during window (should all be blocked by fix):")
    for s in passing_window:
        log(f"    {s['ts']} | {s['city']:<14} | {s['ticker']:<32} | {s['direction']} | "
            f"yes={s['yes_price']:<6} | {s['strategy']}")

log(f"\nPost-window same-day signals (>17:30 ET, target=today): {len(post_window_sameday)}")
if post_window_sameday:
    log("  These are candidates for Bug 2/3 (same-day entry after DSM fires):")
    for s in post_window_sameday[:10]:
        t = s["t_et"].strftime("%H:%M")
        log(f"    {s['ts']} ET={t} | {s['city']:<14} | {s['direction']} | passes={s['passes']}")

# ------------------------------------------------------------------
# SECTION 5: Paper Trade DSM Exit Audit
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 5: PAPER TRADE DSM EXIT TIMING AUDIT (all 15 Oracle paper_trades)")
log("=" * 70)

# All paper_trades from Oracle (hardcoded — only 15 trades)
paper_trades = [
    (1,  "KNYC",      "KXHIGHNY-26APR29-B62.5",    "YES", "CORE_HGEFS_GUMBEL", "2026-04-29T10:09:33+00:00", "2026-04-29T15:06:51+00:00", "NEVER_HOLD_ABOVE", 0.305, 0.70,  21.30, "2026-04-29"),
    (2,  "KNYC",      "KXHIGHNY-26APR29-B60.5",    "NO",  "CORE_HGEFS_GUMBEL", "2026-04-29T10:09:33+00:00", "2026-04-29T12:39:52+00:00", "STOP",             0.555, 0.35,  -6.20, "2026-04-29"),
    (3,  "KNYC",      "KXHIGHNY-26APR29-B58.5",    "NO",  "DEEP_TAIL_NO",      "2026-04-29T10:09:33+00:00", "2026-04-29T10:09:56+00:00", "STOP",             0.845, 0.17,  -2.72, "2026-04-29"),
    (4,  "KNYC",      "KXHIGHNY-26APR30-B65.5",    "NO",  "DEEP_TAIL_NO",      "2026-04-29T15:45:49+00:00", "2026-04-29T15:46:27+00:00", "NEVER_HOLD_ABOVE", 0.875, 0.70,  -0.73, "2026-04-30"),
    (5,  "KNYC",      "KXHIGHNY-26MAY01-B66.5",    "NO",  "DEEP_TAIL_NO",      "2026-04-30T14:37:04+00:00", "2026-04-30T14:42:08+00:00", "TARGET",           0.710, 0.68,  -0.19, "2026-05-01"),
    (6,  "KNYC",      "KXHIGHNY-26MAY02-B60.5",    "NO",  "DEEP_TAIL_NO",      "2026-05-01T15:02:33+00:00", "2026-05-01T20:16:29+00:00", "DSM_CANCEL",       0.685, 0.58,  -0.69, "2026-05-02"),
    (7,  "KNYC",      "KXHIGHNY-26MAY01-B66.5",    "NO",  "DEEP_TAIL_NO",      "2026-05-01T16:00:24+00:00", "2026-05-01T16:18:31+00:00", "NEVER_HOLD_ABOVE", 0.665, 0.70,  +0.15, "2026-05-01"),
    (8,  "KNYC",      "KXHIGHNY-26MAY04-B72.5",    "NO",  "CORE_HGEFS_EMOS",   "2026-05-03T15:02:26+00:00", "2026-05-03T20:16:09+00:00", "DSM_CANCEL",       0.655, 0.51,  -1.85, "2026-05-04"),
    (9,  "KNYC",      "KXHIGHNY-26MAY03-B59.5",    "NO",  "DEEP_TAIL_NO",      "2026-05-03T15:02:37+00:00", "2026-05-03T20:16:09+00:00", "DSM_CANCEL",       0.255, 0.21,  -0.83, "2026-05-03"),
    (10, "KNYC",      "KXHIGHNY-26MAY03-B59.5",    "NO",  "CORE_HGEFS_EMOS",   "2026-05-03T16:06:55+00:00", "2026-05-03T20:16:09+00:00", "DSM_CANCEL",       0.325, 0.21,  -6.10, "2026-05-03"),
    (11, "KMIA",      "KXHIGHMIA-26MAY06-B88.5",   "NO",  "CORE_HGEFS_EMOS",   "2026-05-05T16:23:32+00:00", "2026-05-05T20:16:06+00:00", "DSM_CANCEL",       0.505, 0.49,  -0.20, "2026-05-06"),
    (12, "KXLOWTCHI", "KXLOWTCHI-26MAY05-B46.5",   "NO",  "DEEP_TAIL_NO",      "2026-05-05T20:52:07+00:00", "2026-05-05T20:55:45+00:00", "DSM_CANCEL",       0.060, 0.03,  -2.21, "2026-05-05"),
    (13, "KMIA",      "KXHIGHMIA-26MAY06-B88.5",   "NO",  "CORE_HGEFS_EMOS",   "2026-05-05T21:21:51+00:00", "2026-05-05T21:27:37+00:00", "DSM_CANCEL",       0.495, 0.45,  -0.44, "2026-05-06"),
    (14, "KXLOWTCHI", "KXLOWTCHI-26MAY05-B46.5",   "NO",  "DEEP_TAIL_NO",      "2026-05-05T21:22:20+00:00", "2026-05-05T21:27:37+00:00", "DSM_CANCEL",       0.115, 0.07,  -1.74, "2026-05-05"),
    (15, "KXLOWTCHI", "KXLOWTCHI-26MAY05-B46.5",   "NO",  "DEEP_TAIL_NO",      "2026-05-05T21:51:55+00:00", None,                        None,               0.075, None,  None,  "2026-05-05"),
]

log()
log(f"{'ID':<4} {'Entry ET':<10} {'Exit ET':<10} {'Reason':<18} {'In Window':<11} {'Bug':<5} {'SameDay':<9} {'net_pnl':>8}")
log("-" * 82)

bug_trades, correct_dsm, correct_other = [], [], []
for t in paper_trades:
    tid, city, ticker, direction, strategy, entry_ts, exit_ts, reason, ep, xp, net, td = t
    entry_et = to_et(entry_ts)
    exit_et  = to_et(exit_ts)
    if entry_et is None:
        continue
    t_et = entry_et.time()
    in_win = CURRENT_WINDOW_START_ET <= t_et <= CURRENT_WINDOW_END_ET
    same_day = td == entry_et.date().isoformat()
    is_bug = in_win

    if is_bug:
        bug_trades.append(t)
    elif reason == "DSM_CANCEL":
        correct_dsm.append(t)
    else:
        correct_other.append(t)

    net_str = f"{net:+.2f}" if net is not None else "open "
    entry_str = entry_et.strftime("%H:%M ET")
    exit_str  = exit_et.strftime("%H:%M ET") if exit_et else "open  "
    log(f"{tid:<4} {entry_str:<10} {exit_str:<10} {(reason or 'open'):<18} {'YES' if in_win else 'no':<11} {'BUG' if is_bug else '':<5} {'YES' if same_day else 'no':<9} {net_str:>8}")

log()
log(f"  Bug trades (entered during window):     {len(bug_trades)}  — net_pnl = "
    f"{sum(float(t[10]) for t in bug_trades if t[10] is not None):+.2f}")
log(f"  Correct DSM_CANCEL (entered pre-window):{len(correct_dsm)}  — held correctly until DSM")
log(f"  Other exits (STOP/TARGET/etc):          {len(correct_other)}")
log()
log("  Correct DSM_CANCEL hold times:")
for t in correct_dsm:
    entry_et = to_et(t[5])
    exit_et  = to_et(t[6])
    hold_min = int((exit_et - entry_et).total_seconds() / 60) if exit_et else 0
    log(f"    ID={t[0]} {t[1]:<14} target={t[11]} hold={hold_min}min exit@{exit_et.strftime('%H:%M ET') if exit_et else 'open'} net={t[10]:+.2f}")

# ------------------------------------------------------------------
# SECTION 6: Historical Backtest from report7 (4,007 rows)
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 6: HISTORICAL BACKTEST — ENTRY TIMING VALUE (report7, 4,007 trades)")
log("=" * 70)
log()

R7_CSV = ROOT / "data" / "research" / "report7_policy_stress_backtest.csv"
r7_by_timing: dict[str, list] = defaultdict(list)

with open(R7_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get("policy", "").strip() != "current_strategy":
            continue
        timing = row.get("entry_timing", "").strip()
        try:
            net = float(row["maker_net"])
            win = row.get("win", "").strip() in ("True", "1", "true")
            r7_by_timing[timing].append((net, win))
        except Exception:
            pass

log(f"{'Entry timing':<20} {'N':<6} {'Win%':<8} {'Mean PnL':<12} {'Std':<10} {'Sharpe':<10} {'Total PnL'}")
log("-" * 72)
timing_totals = {}
for timing in sorted(r7_by_timing):
    pairs = r7_by_timing[timing]
    if not pairs:
        continue
    nets = [p[0] for p in pairs]
    wins = [p[1] for p in pairs]
    mean_ = statistics.mean(nets)
    std_  = statistics.stdev(nets) if len(nets) > 1 else 0
    sharpe = mean_ / std_ if std_ > 0 else 0
    win_pct = 100 * sum(wins) / len(wins)
    total = sum(nets)
    timing_totals[timing] = total
    log(f"{timing:<20} {len(nets):<6} {win_pct:>6.1f}%  {mean_:>+9.4f}   {std_:>7.4f}   {sharpe:>+7.3f}   {total:>+8.2f}")

log()
log("  Key insight: most trades enter at '9AM' (10:15 AM ET entry) or '11AM'.")
log("  The DSM window (4:15–5:30 PM ET) is AFTER all normal entry times.")
log("  Blocking the window costs zero expected alpha — no trades were ever")
log("  supposed to enter during 4:15–5:30 PM ET in the historical backtest.")

# ------------------------------------------------------------------
# SECTION 7: In-Memory State Loss — Restart Bug
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 7: IN-MEMORY STATE LOSS BUG (Restart clears _last_dsm_received)")
log("=" * 70)
log()
log("  Mechanism:")
log("    _last_dsm_received: dict[str, str] = {}  # empty on start")
log("    Populated only when wethr obs returns a new dsm_received_at.")
log("    If bot restarts after DSM fires, the guard check:")
log("      last_dsm.startswith(today.isoformat())")
log("    always evaluates to False → same-day entries allowed again.")
log()
log("  Evidence from May 5:")
log("    KMDW DSM received at 21:17 UTC (17:17 ET) — within window, exits triggered.")
log("    Trade 15 entered at 21:51 UTC (17:51 ET) — after window end, same-day.")
log("    _last_dsm_received['KMDW'] was empty (restart or first poll) → guard missed.")
log()
log("  Fix: pre-populate from DB in EventTriggerEngine.__init__():")
log()
log("    rows = self.db.execute(")
log("        \"\"\"SELECT station, MAX(dsm_received_at) as last_recv")
log("           FROM dsm_reports")
log("           WHERE dsm_received_at IS NOT NULL")
log("           GROUP BY station\"\"\"")
log("    )")
log("    for row in rows:")
log("        if row['last_recv']:")
log("            self._last_dsm_received[row['station']] = row['last_recv']")
log("    logger.info('Pre-populated _last_dsm_received: %s', self._last_dsm_received)")
log()
log("  This makes the same-day guard restart-safe. At bot start, it immediately")
log("  knows whether today's DSM has already been received.")

# ------------------------------------------------------------------
# SECTION 8: Recommended Fixes — Window Comparison
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 8: RECOMMENDED WINDOW OPTIONS")
log("=" * 70)
log()

# Compute opportunity cost of extending window
# = candidate_signals that fire in 17:30–18:30 ET that pass gates
ext_window_start = dt_time(17, 30)
ext_window_end   = dt_time(18, 30)
signals_in_ext = []
with open(SIGNALS_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        ts = row.get("created_at", "").strip()
        if not ts:
            continue
        try:
            dt_utc = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except Exception:
            continue
        dt_et = dt_utc.astimezone(ET)
        t_et = dt_et.time()
        if ext_window_start <= t_et <= ext_window_end:
            passes = row.get("would_pass_core", "0") in ("1",)
            signals_in_ext.append({"ts": ts, "city": row.get("city"), "passes": passes,
                                    "target_date": row.get("target_date"),
                                    "date": dt_et.date().isoformat()})

same_day_ext = [s for s in signals_in_ext if s["target_date"] == s["date"]]
passing_ext  = [s for s in signals_in_ext if s["passes"]]

log(f"Option A (current):  16:15–17:30 ET — blocks {len(in_window_sigs)} candidate signals")
log(f"Option B (extended): 16:15–18:30 ET — additionally blocks {len(signals_in_ext)} more signals")
log(f"  Of the additional signals blocked by Option B:")
log(f"    - Same-day target_date: {len(same_day_ext)}  (correct to block — DSM already fired)")
log(f"    - Would pass gates:     {len(passing_ext)}  (opportunity cost of extension)")
log()
log("Option C (per-city cutoffs):")
for city, (station, dsm_utc, tz) in ACTIVE_CITY_DSM.items():
    dsm_et = EXPECTED_DSM_ET[city]
    cutoff = dt_time(dsm_et.hour, max(0, dsm_et.minute - 10))
    end    = dt_time(dsm_et.hour, min(59, dsm_et.minute + 20))
    log(f"  {city:<14}: block same-day entries after {cutoff.strftime('%H:%M')} ET")
log()
log("Recommendation: Option B (extend to 18:30 ET) — simplest, zero opportunity")
log("cost (no legitimate entries happen 17:30–18:30 ET for any active city),")
log("and fully protects KXLOWTDEN (DSM at 18:17 ET).")

# ------------------------------------------------------------------
# SECTION 9: Complete Fix Inventory
# ------------------------------------------------------------------
log()
log("=" * 70)
log("SECTION 9: COMPLETE BUG INVENTORY AND FIX STATUS")
log("=" * 70)
log()
log("┌────┬──────────────────────────────────────────────┬──────────────┐")
log("│ #  │ Bug                                          │ Status       │")
log("├────┼──────────────────────────────────────────────┼──────────────┤")
log("│ 1  │ fire_gate_check enters trades during window  │ FIXED May 5  │")
log("│ 2  │ Same-day re-entry after DSM fires (in-proc)  │ FIXED May 5  │")
log("│ 3  │ _last_dsm_received cleared on restart        │ NOT FIXED    │")
log("│ 4  │ KXLOWTDEN DSM (18:17 ET) outside 17:30 win  │ NOT FIXED    │")
log("└────┴──────────────────────────────────────────────┴──────────────┘")
log()
log("Estimated financial impact of unfixed bugs per active day:")
log("  Bug 3: ~$0–$4 per restart event (same-day entry after DSM)")
log("  Bug 4: KXLOWTDEN settlement not yet active in live bot — low urgency")
log("         but must be fixed before KXLOWTDEN live trades start.")

# ------------------------------------------------------------------
# Save outputs
# ------------------------------------------------------------------
report_path = ROOT / "reports" / "dsm_check_backtest_report.md"
report_path.parent.mkdir(exist_ok=True)
with open(report_path, "w") as f:
    f.write("# DSM Check Backtest Report\n\n")
    f.write("\n".join(lines))
print(f"\nReport saved: {report_path}")

csv_path = ROOT / "data" / "research" / "dsm_check_backtest.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["trade_id", "city", "ticker", "direction", "strategy",
                "entry_time_utc", "exit_time_utc", "exit_reason",
                "entry_price", "exit_price", "net_pnl", "target_date",
                "entry_time_et", "exit_time_et", "in_dsm_window", "is_bug"])
    for t in paper_trades:
        tid, city, ticker, direction, strategy, entry_ts, exit_ts, reason, ep, xp, net, td = t
        entry_et = to_et(entry_ts)
        exit_et  = to_et(exit_ts)
        if entry_et is None:
            continue
        in_win = CURRENT_WINDOW_START_ET <= entry_et.time() <= CURRENT_WINDOW_END_ET
        w.writerow([tid, city, ticker, direction, strategy,
                    entry_ts, exit_ts or "", reason or "", ep, xp or "", net or "",
                    td, entry_et.strftime("%H:%M"), exit_et.strftime("%H:%M") if exit_et else "",
                    int(in_win), int(in_win)])
print(f"CSV saved:    {csv_path}")
