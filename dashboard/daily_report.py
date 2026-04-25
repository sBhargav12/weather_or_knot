from __future__ import annotations

from datetime import date

from data_store.db import Database


def generate_daily_report(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or date.today().isoformat()
    db = Database(db_path)
    signals = db.execute("SELECT * FROM signals WHERE date(created_at) = date(?)", (report_date,))
    trades = db.execute("SELECT * FROM paper_trades WHERE date(created_at) = date(?)", (report_date,))
    settled = [row for row in trades if row["exit_time"] is not None]
    pnl = sum(float(row["net_pnl_maker"] or 0) for row in settled)
    wins = sum(1 for row in settled if float(row["net_pnl_maker"] or 0) > 0)
    losses = sum(1 for row in settled if float(row["net_pnl_maker"] or 0) <= 0)
    dsm_rows = db.execute("SELECT * FROM dsm_reports WHERE date(created_at) = date(?)", (report_date,))
    cli_rows = db.execute("SELECT * FROM cli_reports WHERE date(created_at) = date(?)", (report_date,))

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
        print_gate_summary(db_path, report_date),
        "",
        "DATA HEALTH",
        f"  DSM events detected: {len(dsm_rows)}",
        f"  CLI events detected: {len(cli_rows)}",
    ]
    return "\n".join(lines)


def print_gate_summary(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or date.today().isoformat()
    db = Database(db_path)
    rows = db.execute("SELECT * FROM gate_checks WHERE date(created_at) = date(?)", (report_date,))
    summary = {
        "Gate 1 (HGEFS spread)": sum(1 for row in rows if row["gate1_pass"] == 0),
        "Gate 2 (gap < 20pp)": sum(1 for row in rows if row["gate2_pass"] == 0),
        "Gate 3 (price band)": sum(1 for row in rows if row["gate3_pass"] == 0),
        "Gate 4 (dead zone)": sum(1 for row in rows if row["gate4_pass"] == 0),
        "Gate 5 (METAR)": sum(1 for row in rows if row["gate5_pass"] == 0),
        "Gate 6 (reversal)": sum(1 for row in rows if row["gate6_pass"] == 0),
    }
    lines = ["GATE FAILURES TODAY"]
    lines.extend(f"  {label}: {count}" for label, count in summary.items())
    return "\n".join(lines)
