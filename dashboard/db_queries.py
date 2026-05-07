from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _utc_window(report_date: str) -> tuple[str, str]:
    """UTC created_at window for a NY trading date."""
    d = date.fromisoformat(report_date)
    start = datetime.combine(d, time.min, tzinfo=NY_TZ).astimezone(UTC)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


def _today() -> str:
    return datetime.now(NY_TZ).date().isoformat()


def _days_ago_utc(days: int) -> str:
    dt = datetime.now(UTC) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Live tab
# ---------------------------------------------------------------------------

def get_open_trades(db_path: str) -> list[dict]:
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, city, ticker, target_date, bracket, direction,
                   contracts, stake_dollars, entry_price, strategy_sleeve,
                   candidate_status, policy_reason, bracket_family,
                   raw_edge_pp, est_net_edge_pp, final_size_mult,
                   seasonal_mult, regime_mult
            FROM paper_trades
            WHERE exit_time IS NULL
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_today_summary(db_path: str) -> dict:
    today = _today()
    start_utc, end_utc = _utc_window(today)
    with _conn(db_path) as conn:
        trades = conn.execute(
            "SELECT net_pnl_maker, exit_time, settled_correct FROM paper_trades "
            "WHERE created_at >= ? AND created_at < ?",
            (start_utc, end_utc),
        ).fetchall()
        signals = conn.execute(
            "SELECT id FROM signals WHERE created_at >= ? AND created_at < ?",
            (start_utc, end_utc),
        ).fetchall()
        gate_checks = conn.execute(
            "SELECT gate1_pass, gate2_pass, gate3_pass, all_pass FROM gate_checks "
            "WHERE created_at >= ? AND created_at < ?",
            (start_utc, end_utc),
        ).fetchall()
        candidates = conn.execute(
            "SELECT candidate_status FROM candidate_signals "
            "WHERE created_at >= ? AND created_at < ?",
            (start_utc, end_utc),
        ).fetchall()

    settled = [t for t in trades if t["exit_time"] is not None]
    pnl = sum(float(t["net_pnl_maker"] or 0) for t in settled)
    wins = sum(1 for t in settled if float(t["net_pnl_maker"] or 0) > 0)

    return {
        "date": today,
        "signals": len(signals),
        "trades_open": len(trades) - len(settled),
        "trades_settled": len(settled),
        "wins": wins,
        "losses": len(settled) - wins,
        "pnl": pnl,
        "gate_checks": len(gate_checks),
        "gate1_pass": sum(1 for g in gate_checks if g["gate1_pass"]),
        "gate2_pass": sum(1 for g in gate_checks if g["gate2_pass"]),
        "gate3_pass": sum(1 for g in gate_checks if g["gate3_pass"]),
        "all_pass": sum(1 for g in gate_checks if g["all_pass"]),
        "candidates": len(candidates),
        "suspended": sum(1 for c in candidates if c["candidate_status"] == "suspended_policy"),
        "rejected_conf": sum(1 for c in candidates if c["candidate_status"] == "rejected_low_core_confidence"),
        "rejected_edge": sum(1 for c in candidates if c["candidate_status"] == "rejected_execution_margin"),
    }


def get_latest_metar(db_path: str) -> dict | None:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM metar_observations ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_latest_model_run(db_path: str) -> dict | None:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM model_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Decision log tab
# ---------------------------------------------------------------------------

def get_gate_checks(db_path: str, limit: int = 200) -> list[dict]:
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM gate_checks
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def gate_explanation(row: dict) -> list[str]:
    """Return a list of human-readable lines explaining each gate decision."""
    lines = []

    def _v(key: str, default: str = "n/a") -> str:
        v = row.get(key)
        return str(round(float(v), 2)) if v is not None else default

    def _badge(passed) -> str:
        if passed is None:
            return "—"
        return "✅ PASS" if int(passed) else "❌ FAIL"

    # Gate 1
    src = row.get("gate1_ai_source") or "unknown"
    delta = abs((row.get("gate1_physics_mean") or 0) - (row.get("gate1_ai_mean") or 0))
    lines.append(
        f"Gate 1 {_badge(row.get('gate1_pass'))} — Model convergence | "
        f"Physics={_v('gate1_physics_mean')}°F  AI={_v('gate1_ai_mean')}°F  "
        f"Δ={delta:.2f}°F (max 1.5) | "
        f"σ_phys={_v('gate1_physics_spread')}  σ_ai={_v('gate1_ai_spread')} (max 3.0) | "
        f"AI source: {src}"
    )

    # Gate 2
    gap = row.get("gate2_gap_pp")
    dz_note = ""
    if gap is not None and 35 <= float(gap) <= 40:
        dz_note = " ⚠️ dead zone [35–40pp]"
    lines.append(
        f"Gate 2 {_badge(row.get('gate2_pass'))} — Edge gap | "
        f"P_model={_v('gate2_model_prob')}  P_mkt={_v('gate2_market_price')}  "
        f"gap={_v('gate2_gap_pp')}pp (min 20){dz_note} | "
        f"dir={row.get('gate2_direction') or 'n/a'}"
    )

    # Gate 3
    lines.append(
        f"Gate 3 {_badge(row.get('gate3_pass'))} — Price band | "
        f"YES price={_v('gate3_yes_price')} (valid range 0.25–0.75)"
    )

    # Gate 4 (modifier)
    in_dz = row.get("gate4_in_dead_zone")
    dz_str = "IN dead zone" if in_dz else "clear of dead zone"
    lines.append(f"Gate 4 [modifier] — Dead zone | {dz_str}")

    # Gate 5
    metar = row.get("gate5_metar_temp_f")
    center = row.get("gate5_bracket_center_f")
    dist = row.get("gate5_distance")
    if metar is not None:
        lines.append(
            f"Gate 5 {_badge(row.get('gate5_pass'))} — METAR | "
            f"METAR={_v('gate5_metar_temp_f')}°F  bracket center={_v('gate5_bracket_center_f')}°F  "
            f"dist={_v('gate5_distance')}°F"
        )
    else:
        lines.append("Gate 5 [not evaluated] — METAR not available at check time")

    # Gate 6
    rev = row.get("gate6_reversal_detected")
    cold = row.get("gate6_is_cold_bracket")
    lines.append(
        f"Gate 6 [modifier] — Reversal | "
        f"{'reversal detected' if rev else 'no reversal'} | "
        f"cold bracket: {'yes' if cold else 'no'}"
    )

    # Overall
    skip = row.get("skip_reason")
    if skip:
        lines.append(f"⏭ Skipped: {skip}")
    elif row.get("all_pass"):
        lines.append("✅ All gates passed → signal generated")
    else:
        failed = [
            f"G{i}" for i, col in enumerate(
                ["gate1_pass", "gate2_pass", "gate3_pass"], start=1
            ) if not row.get(col)
        ]
        lines.append(f"❌ Failed at: {', '.join(failed) if failed else 'unknown'}")

    return lines


def get_trade_decision_detail(db_path: str, trade_id: int) -> dict:
    """Full decision chain for one paper trade."""
    with _conn(db_path) as conn:
        trade = conn.execute(
            "SELECT * FROM paper_trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if not trade:
            return {}
        trade = dict(trade)
        signal = None
        if trade.get("signal_id"):
            row = conn.execute(
                "SELECT * FROM signals WHERE id = ?", (trade["signal_id"],)
            ).fetchone()
            signal = dict(row) if row else None
        gate = None
        if trade.get("ticker"):
            row = conn.execute(
                """
                SELECT * FROM gate_checks
                WHERE ticker = ? AND date(created_at) = date(?)
                ORDER BY created_at DESC LIMIT 1
                """,
                (trade["ticker"], trade.get("created_at", "")),
            ).fetchone()
            gate = dict(row) if row else None
    return {"trade": trade, "signal": signal, "gate": gate}


# ---------------------------------------------------------------------------
# Trade history tab
# ---------------------------------------------------------------------------

def get_trades(db_path: str, days: int = 60) -> list[dict]:
    cutoff = _days_ago_utc(days)
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, city, ticker, target_date, bracket, direction,
                   contracts, stake_dollars, entry_price, exit_price, exit_time,
                   exit_reason, gross_pnl, net_pnl_maker, net_pnl_taker,
                   strategy_sleeve, candidate_status, policy_reason,
                   bracket_family, raw_edge_pp, est_net_edge_pp,
                   seasonal_mult, regime_mult, final_size_mult,
                   settled_correct, settlement_temp_f
            FROM paper_trades
            WHERE created_at >= ?
            ORDER BY created_at DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Performance tab
# ---------------------------------------------------------------------------

def get_bankroll_curve(db_path: str) -> list[dict]:
    """All settled trades ordered by exit_time for cumulative P&L."""
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT exit_time, net_pnl_maker, strategy_sleeve, direction
            FROM paper_trades
            WHERE exit_time IS NOT NULL AND net_pnl_maker IS NOT NULL
            ORDER BY exit_time ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_sleeve_stats(db_path: str) -> list[dict]:
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT strategy_sleeve,
                   COUNT(*) as total,
                   SUM(CASE WHEN net_pnl_maker > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN net_pnl_maker <= 0 AND exit_time IS NOT NULL THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(COALESCE(net_pnl_maker, 0)), 2) as total_pnl,
                   ROUND(AVG(COALESCE(net_pnl_maker, 0)), 2) as avg_pnl,
                   ROUND(AVG(COALESCE(raw_edge_pp, 0)), 1) as avg_edge_pp
            FROM paper_trades
            WHERE exit_time IS NOT NULL
            GROUP BY strategy_sleeve
            ORDER BY total_pnl DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_exit_reason_breakdown(db_path: str) -> list[dict]:
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT exit_reason,
                   COUNT(*) as count,
                   ROUND(SUM(COALESCE(net_pnl_maker, 0)), 2) as total_pnl,
                   ROUND(AVG(COALESCE(net_pnl_maker, 0)), 2) as avg_pnl
            FROM paper_trades
            WHERE exit_time IS NOT NULL
            GROUP BY exit_reason
            ORDER BY count DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pipeline health tab
# ---------------------------------------------------------------------------

def get_gate_pass_rates(db_path: str, days: int = 7) -> dict:
    cutoff = _days_ago_utc(days)
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT gate1_pass, gate2_pass, gate3_pass, all_pass, gate1_ai_source "
            "FROM gate_checks WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    total = len(rows)
    if total == 0:
        return {"total": 0}
    return {
        "total": total,
        "gate1_pct": 100 * sum(1 for r in rows if r["gate1_pass"]) // total,
        "gate2_pct": 100 * sum(1 for r in rows if r["gate2_pass"]) // total,
        "gate3_pct": 100 * sum(1 for r in rows if r["gate3_pass"]) // total,
        "all_pass_pct": 100 * sum(1 for r in rows if r["all_pass"]) // total,
        "aigefs_real": sum(1 for r in rows if r["gate1_ai_source"] == "aigefs_real"),
        "wethr_proxy": sum(1 for r in rows if r["gate1_ai_source"] == "wethr_proxy"),
    }


def get_recent_model_runs(db_path: str) -> list[dict]:
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT model, city, created_at, physics_mean, ai_mean,
                   nbm_p50, aigefs_temp_corrected, source
            FROM model_runs
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_candidate_funnel(db_path: str, days: int = 7) -> dict:
    cutoff = _days_ago_utc(days)
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT candidate_status, strategy_sleeve FROM candidate_signals "
            "WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    total = len(rows)
    statuses: dict[str, int] = {}
    for r in rows:
        s = r["candidate_status"] or "unknown"
        statuses[s] = statuses.get(s, 0) + 1
    return {"total": total, "by_status": statuses}


def get_daily_performance(db_path: str, days: int = 30) -> list[dict]:
    cutoff = _days_ago_utc(days)
    with _conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT date, net_pnl_maker, wins, losses, trades_taken,
                   bankroll_end, win_rate
            FROM performance_daily
            WHERE date >= date(?)
            ORDER BY date ASC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]
