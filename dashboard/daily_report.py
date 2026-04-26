from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data_store.db import Database

NY_TZ = ZoneInfo("America/New_York")


def _report_window_utc(report_date: str) -> tuple[str, str]:
    """Return the UTC created_at window for a New York trading/report date."""
    start_local = datetime.combine(date.fromisoformat(report_date), time.min, tzinfo=NY_TZ)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        end_local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    )


def _rows_for_day(db: Database, table: str, report_date: str, extra_where: str = "", params: tuple[Any, ...] = ()) -> list:
    start_utc, end_utc = _report_window_utc(report_date)
    where = f"created_at >= ? AND created_at < ?{extra_where}"
    return db.execute(f"SELECT * FROM {table} WHERE {where}", (start_utc, end_utc, *params))


def generate_daily_report(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    signals = _rows_for_day(db, "signals", report_date)
    trades = _rows_for_day(db, "paper_trades", report_date)
    settled = [row for row in trades if row["exit_time"] is not None]
    pnl = sum(float(row["net_pnl_maker"] or 0) for row in settled)
    wins = sum(1 for row in settled if float(row["net_pnl_maker"] or 0) > 0)
    losses = sum(1 for row in settled if float(row["net_pnl_maker"] or 0) <= 0)
    dsm_rows = _rows_for_day(db, "dsm_reports", report_date)
    cli_rows = _rows_for_day(db, "cli_reports", report_date)

    lines = [
        "KALSHI WEATHER PIPELINE - DAILY REPORT",
        f"Date: {report_date}",
        "",
        "BANKROLL",
        f"  Net P&L today (maker): ${pnl:.2f}",
        "",
        "TODAY'S ACTIVITY",
        f"  Signals generated: {len(signals)}",
        f"  Trades simulated:  {len(trades)}",
        f"  Trades exited:     {len(settled)}",
        f"  Wins / Losses:     {wins} / {losses}",
        "",
        print_sleeve_summary(db_path, report_date),
        "",
        print_gate_summary(db_path, report_date),
        "",
        print_model_availability(db_path, report_date),
        "",
        "DATA HEALTH",
        f"  DSM events detected: {len(dsm_rows)}",
        f"  CLI events detected: {len(cli_rows)}",
    ]
    return "\n".join(lines)


def print_sleeve_summary(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    lines = ["SIGNAL BREAKDOWN BY SLEEVE"]
    for sleeve in ["CORE_HGEFS_GUMBEL", "TAIL_NO", "DEEP_TAIL_NO", "LADDER"]:
        sigs = _rows_for_day(db, "signals", report_date, " AND strategy_sleeve = ?", (sleeve,))
        trades = _rows_for_day(db, "paper_trades", report_date, " AND strategy_sleeve = ?", (sleeve,))
        avg_conf = (
            sum(float(s["confidence_score"] or 0) for s in sigs) / len(sigs)
            if sigs else 0.0
        )
        lines.append(f"  {sleeve}: {len(sigs)} signals, {len(trades)} trades (avg conf: {avg_conf:.0f})")
    return "\n".join(lines)


def print_gate_summary(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)
    rows = _rows_for_day(db, "gate_checks", report_date)

    total = len(rows)
    if total == 0:
        return "GATE PASS RATES TODAY\n  No gate checks recorded."

    def pct(col: str) -> str:
        n = sum(1 for r in rows if r[col] == 1)
        return f"{n}/{total} ({100*n//total}%)"

    tier1_pass = sum(1 for r in rows if r["all_pass"] == 1)
    signals_per_day = tier1_pass  # each all_pass generates a signal

    real_aigefs = sum(1 for r in rows if r["gate1_ai_source"] == "aigefs_real")
    wethr_proxy = sum(1 for r in rows if r["gate1_ai_source"] == "wethr_proxy")

    lines = [
        "GATE PASS RATES TODAY",
        f"  Gate 1 (model convergence): {pct('gate1_pass')}",
        f"  Gate 2 (gap threshold):     {pct('gate2_pass')}",
        f"  Gate 3 (price band):        {pct('gate3_pass')}",
        f"  Gate 4 (dead zone mod):     modifier only",
        f"  Gate 5 (METAR):             modifier only",
        f"  Gate 6 (reversal):          modifier only",
        f"  Combined Tier 1:            {tier1_pass}/{total} → ~{signals_per_day} signals/day",
        "",
        "GATE 1 AI SOURCE",
        f"  aigefs_real:  {real_aigefs} checks",
        f"  wethr_proxy:  {wethr_proxy} checks",
    ]
    return "\n".join(lines)


def print_model_availability(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)
    start_utc, end_utc = _report_window_utc(report_date)

    hgefs = db.execute(
        """
        SELECT * FROM model_runs
        WHERE model = 'HGEFS' AND created_at >= ? AND created_at < ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (start_utc, end_utc),
    )

    lines = ["MODEL AVAILABILITY TODAY"]
    if hgefs:
        row = hgefs[0]
        real = row["physics_mean"] is not None
        ai_real = row["ai_mean"] is not None and row["aigefs_temp_raw"] is not None
        lines.append(f"  HGEFS real physics data: {'YES' if real else 'NO'}")
        lines.append(f"  AIGEFS real AI data:     {'YES' if ai_real else 'NO (wethr proxy)'}")
        if real:
            lines.append(f"  Physics mean: {row['physics_mean']:.1f}°F ± {row['physics_spread']:.2f}°F")
        if ai_real:
            lines.append(f"  AIGEFS mean (corrected): {row['ai_mean']:.1f}°F (raw: {row['aigefs_temp_raw']:.1f}°F)")
    else:
        lines.append("  HGEFS real physics data: NO")
        lines.append("  AIGEFS real AI data:     NO")

    # List models that returned data today
    wethr_models = db.execute(
        """
        SELECT DISTINCT model FROM model_runs
        WHERE model NOT IN ('HGEFS','NBM_BULLETIN','WETHR_CONSENSUS')
          AND created_at >= ? AND created_at < ?
        """,
        (start_utc, end_utc),
    )
    model_list = [r["model"] for r in wethr_models]
    lines.append(f"  Wethr models today: {', '.join(model_list) if model_list else 'none'}")

    # Candidate signals summary
    candidates = _rows_for_day(db, "candidate_signals", report_date)
    core_candidates = [c for c in candidates if c["strategy_sleeve"] == "CORE_HGEFS_GUMBEL"]
    passed = sum(1 for c in core_candidates if c["would_pass_core"] == 1)
    lines.append("")
    lines.append("CANDIDATE SIGNALS TODAY")
    lines.append(f"  Evaluated (core sleeve): {len(core_candidates)}")
    lines.append(f"  Passed Tier 1:           {passed}")
    lines.append(f"  TAIL_NO candidates:      {sum(1 for c in candidates if c['strategy_sleeve'] == 'TAIL_NO')}")
    lines.append(f"  DEEP_TAIL_NO candidates: {sum(1 for c in candidates if c['strategy_sleeve'] == 'DEEP_TAIL_NO')}")

    return "\n".join(lines)
