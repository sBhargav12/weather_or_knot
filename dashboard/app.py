"""
Kalshi Weather Pipeline Dashboard
Run locally:  streamlit run dashboard/app.py
With Oracle sync: ORACLE_SSH_HOST=ubuntu@<ip> streamlit run dashboard/app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project root is on path so package imports work regardless of how
# streamlit resolves the script directory.
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from dashboard.db_queries import (
    gate_explanation,
    get_bankroll_curve,
    get_candidate_funnel,
    get_daily_performance,
    get_exit_reason_breakdown,
    get_gate_checks,
    get_gate_pass_rates,
    get_latest_metar,
    get_latest_model_run,
    get_open_trades,
    get_recent_model_runs,
    get_sleeve_stats,
    get_today_summary,
    get_trade_decision_detail,
    get_trades,
)

NY_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ORACLE_SSH_HOST = os.environ.get("ORACLE_SSH_HOST", "")
ORACLE_DB_PATH = os.environ.get(
    "ORACLE_DB_PATH",
    "/home/ubuntu/prediction-market-analysis/data/pipeline.db",
)
LOCAL_DB_PATH = os.environ.get(
    "LOCAL_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "pipeline.db"),
)
SYNC_INTERVAL = 60  # seconds

st.set_page_config(
    page_title="Kalshi Pipeline",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Oracle sync — use plain module globals (st.session_state is main-thread only)
# ---------------------------------------------------------------------------

_sync_lock = threading.Lock()
_sync_state: dict = {"last_sync": None, "error": None, "started": False}
_LOCAL_COPY = "/tmp/pipeline_dashboard.db"


def _run_rsync() -> str | None:
    """Run rsync, return error string or None on success."""
    result = subprocess.run(
        [
            "rsync", "-az", "--timeout=15",
            "-e", f"ssh -i {Path.home()}/.ssh/oracle_kalshi -o StrictHostKeyChecking=no",
            f"{ORACLE_SSH_HOST}:{ORACLE_DB_PATH}",
            _LOCAL_COPY,
        ],
        capture_output=True, text=True, timeout=40,
    )
    return result.stderr.strip() if result.returncode != 0 else None


def _sync_loop():
    while True:
        err = _run_rsync()
        with _sync_lock:
            _sync_state["last_sync"] = datetime.now(NY_TZ).strftime("%H:%M:%S")
            _sync_state["error"] = err
        time.sleep(SYNC_INTERVAL)


def _ensure_sync_started():
    with _sync_lock:
        if _sync_state["started"]:
            return
        _sync_state["started"] = True
    # Initial blocking sync so the DB exists before first render
    err = _run_rsync()
    with _sync_lock:
        _sync_state["last_sync"] = datetime.now(NY_TZ).strftime("%H:%M:%S")
        _sync_state["error"] = err
    t = threading.Thread(target=_sync_loop, daemon=True)
    t.start()


def _db_path() -> str:
    if ORACLE_SSH_HOST:
        _ensure_sync_started()
        return _LOCAL_COPY
    return LOCAL_DB_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pnl_color(val: float) -> str:
    return "green" if val > 0 else ("red" if val < 0 else "gray")


def _fmt_pnl(val) -> str:
    if val is None:
        return "—"
    v = float(val)
    return f"+${v:.2f}" if v > 0 else f"-${abs(v):.2f}"


def _pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100*n//total}%)" if total else "0/0"


def _gate_badge(passed) -> str:
    if passed is None:
        return "—"
    return "✅" if int(passed) else "❌"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Pipeline Dashboard")
    if ORACLE_SSH_HOST:
        with _sync_lock:
            last = _sync_state["last_sync"] or "syncing..."
            err = _sync_state["error"]
        st.caption(f"Oracle sync: {last}")
        if err:
            st.error(f"Sync error: {err}")
        else:
            st.success("DB synced")
    else:
        st.info(f"Local DB\n`{LOCAL_DB_PATH}`")

    if st.button("Force Refresh"):
        st.rerun()

    st.caption(f"Now (ET): {datetime.now(NY_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------

tab_live, tab_decisions, tab_history, tab_perf, tab_health = st.tabs([
    "Live", "Decision Log", "Trade History", "Performance", "Pipeline Health"
])

db = _db_path()

if not Path(db).exists():
    st.warning("Waiting for initial DB sync from Oracle...")
    time.sleep(3)
    st.rerun()

# ===========================================================================
# TAB 1 — LIVE
# ===========================================================================
with tab_live:
    try:
        summary = get_today_summary(db)
        open_trades = get_open_trades(db)
        metar = get_latest_metar(db)
        model = get_latest_model_run(db)
    except Exception as e:
        st.error(f"DB read error: {e}")
        st.stop()

    st.subheader(f"Today — {summary['date']}")

    # KPI row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    pnl = summary["pnl"]
    c1.metric("Net P&L (today)", _fmt_pnl(pnl), delta=None)
    c2.metric("Open trades", summary["trades_open"])
    c3.metric("Settled", summary["trades_settled"])
    wr = (
        f"{summary['wins']}/{summary['trades_settled']}"
        if summary["trades_settled"]
        else "—"
    )
    c4.metric("W/L", wr)
    c5.metric("Signals", summary["signals"])
    c6.metric("Gate checks", summary["gate_checks"])

    st.divider()

    # Gate pass funnel
    st.markdown("**Gate pass funnel (today)**")
    fc1, fc2, fc3, fc4 = st.columns(4)
    total = summary["gate_checks"] or 1
    fc1.metric("Gate 1", _pct(summary["gate1_pass"], summary["gate_checks"]))
    fc2.metric("Gate 2", _pct(summary["gate2_pass"], summary["gate_checks"]))
    fc3.metric("Gate 3", _pct(summary["gate3_pass"], summary["gate_checks"]))
    fc4.metric("All pass", _pct(summary["all_pass"], summary["gate_checks"]))

    # Candidate rejection
    st.markdown("**Candidate rejections (today)**")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Suspended policy", summary["suspended"])
    rc2.metric("Low confidence", summary["rejected_conf"])
    rc3.metric("Margin rejected", summary["rejected_edge"])

    st.divider()

    # Open trades
    st.markdown(f"**Open paper trades ({len(open_trades)})**")
    if open_trades:
        df = pd.DataFrame(open_trades)[[
            "id", "created_at", "city", "ticker", "bracket", "direction",
            "contracts", "entry_price", "stake_dollars", "strategy_sleeve",
            "raw_edge_pp", "est_net_edge_pp", "final_size_mult",
            "candidate_status", "policy_reason",
        ]]
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%m-%d %H:%M")
        df.columns = [c.replace("_", " ") for c in df.columns]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No open trades right now.")

    st.divider()

    # Latest METAR + model run
    mc1, mc2 = st.columns(2)
    with mc1:
        st.markdown("**Latest METAR**")
        if metar:
            st.json({
                "station": metar.get("station"),
                "time": metar.get("observation_time"),
                "temp_f": metar.get("temp_f"),
                "six_hour_high_f": metar.get("six_hour_high_f"),
                "dsm_high_f": metar.get("dsm_high_f"),
                "cli_high_f": metar.get("cli_high_f"),
            })
        else:
            st.info("No METAR data.")

    with mc2:
        st.markdown("**Latest model run**")
        if model:
            st.json({
                "model": model.get("model"),
                "city": model.get("city"),
                "target_date": model.get("target_date"),
                "physics_mean": model.get("physics_mean"),
                "ai_mean": model.get("ai_mean"),
                "nbm_p50": model.get("nbm_p50"),
                "source": model.get("source"),
                "created_at": model.get("created_at"),
            })
        else:
            st.info("No model run data.")

# ===========================================================================
# TAB 2 — DECISION LOG
# ===========================================================================
with tab_decisions:
    st.subheader("Decision Log — Gate Checks")

    n_checks = st.slider("Show last N gate checks", 20, 500, 100, step=20)
    checks = get_gate_checks(db, limit=n_checks)

    if not checks:
        st.info("No gate checks in DB yet.")
    else:
        # Summary table
        rows = []
        for c in checks:
            rows.append({
                "time": c.get("created_at", "")[:16],
                "city": c.get("city"),
                "ticker": c.get("ticker"),
                "trigger": c.get("trigger_reason"),
                "G1": _gate_badge(c.get("gate1_pass")),
                "G2": _gate_badge(c.get("gate2_pass")),
                "G3": _gate_badge(c.get("gate3_pass")),
                "G4": "ℹ" if c.get("gate4_in_dead_zone") else "—",
                "G5": _gate_badge(c.get("gate5_pass")),
                "G6": "—",
                "all": "✅ SIGNAL" if c.get("all_pass") else "❌",
                "skip": c.get("skip_reason") or "",
                "ai_src": c.get("gate1_ai_source") or "",
                "id": c.get("id"),
            })

        df = pd.DataFrame(rows)
        st.dataframe(
            df.drop(columns=["id"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("**Full gate reasoning — expand any check**")

        for c in checks[:50]:
            label = (
                f"{c.get('created_at','')[:16]}  |  "
                f"{c.get('city','')}  {c.get('ticker','')}  |  "
                f"{'✅ SIGNAL' if c.get('all_pass') else '❌ blocked'}"
            )
            with st.expander(label):
                for line in gate_explanation(c):
                    st.markdown(f"- {line}")
                if c.get("reasoning"):
                    st.caption(f"Signal reasoning: {c['reasoning']}")

# ===========================================================================
# TAB 3 — TRADE HISTORY
# ===========================================================================
with tab_history:
    st.subheader("Trade History")

    col_days, col_sleeve = st.columns([2, 3])
    days = col_days.selectbox("Look-back", [7, 14, 30, 60, 90], index=2)
    trades = get_trades(db, days=days)

    sleeves = ["All"] + sorted({t["strategy_sleeve"] for t in trades if t["strategy_sleeve"]})
    sleeve_filter = col_sleeve.multiselect("Sleeve", sleeves[1:], default=[])

    if sleeve_filter:
        trades = [t for t in trades if t["strategy_sleeve"] in sleeve_filter]

    if not trades:
        st.info("No trades in this range.")
    else:
        settled = [t for t in trades if t["exit_time"] is not None]
        total_pnl = sum(float(t["net_pnl_maker"] or 0) for t in settled)
        wins = sum(1 for t in settled if float(t["net_pnl_maker"] or 0) > 0)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total trades", len(trades))
        m2.metric("Settled", len(settled))
        m3.metric(
            "Win rate",
            f"{100*wins//len(settled)}%" if settled else "—",
        )
        m4.metric("Net P&L", _fmt_pnl(total_pnl))

        df = pd.DataFrame(trades)
        display_cols = [
            "id", "created_at", "city", "ticker", "bracket", "direction",
            "contracts", "entry_price", "exit_price", "exit_reason",
            "net_pnl_maker", "strategy_sleeve", "bracket_family",
            "raw_edge_pp", "est_net_edge_pp", "final_size_mult",
            "candidate_status", "policy_reason", "settled_correct",
        ]
        display_cols = [c for c in display_cols if c in df.columns]
        df = df[display_cols].copy()
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.strftime("%m-%d %H:%M")

        def _color_pnl(val):
            if pd.isna(val):
                return ""
            return "color: green" if float(val) > 0 else "color: red"

        styled = df.style.map(_color_pnl, subset=["net_pnl_maker"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Decision detail — expand any trade**")
        for t in trades[:30]:
            pnl_str = _fmt_pnl(t.get("net_pnl_maker"))
            label = (
                f"{str(t.get('created_at',''))[:16]}  |  "
                f"{t.get('ticker','')}  {t.get('direction','')}  |  "
                f"P&L: {pnl_str}  |  sleeve: {t.get('strategy_sleeve','')}  |  "
                f"exit: {t.get('exit_reason','open')}"
            )
            with st.expander(label):
                detail = get_trade_decision_detail(db, t["id"])
                trade_d = detail.get("trade", {})
                signal_d = detail.get("signal", {})
                gate_d = detail.get("gate", {})

                tc1, tc2 = st.columns(2)
                with tc1:
                    st.markdown("**Trade**")
                    st.json({
                        "sleeve": trade_d.get("strategy_sleeve"),
                        "bracket_family": trade_d.get("bracket_family"),
                        "entry_price": trade_d.get("entry_price"),
                        "exit_price": trade_d.get("exit_price"),
                        "exit_reason": trade_d.get("exit_reason"),
                        "contracts": trade_d.get("contracts"),
                        "stake_$": trade_d.get("stake_dollars"),
                        "net_pnl_maker": trade_d.get("net_pnl_maker"),
                        "raw_edge_pp": trade_d.get("raw_edge_pp"),
                        "est_net_edge_pp": trade_d.get("est_net_edge_pp"),
                        "seasonal_mult": trade_d.get("seasonal_mult"),
                        "regime_mult": trade_d.get("regime_mult"),
                        "final_size_mult": trade_d.get("final_size_mult"),
                        "candidate_status": trade_d.get("candidate_status"),
                        "policy_reason": trade_d.get("policy_reason"),
                        "settlement_temp_f": trade_d.get("settlement_temp_f"),
                        "settled_correct": trade_d.get("settled_correct"),
                    })

                with tc2:
                    if signal_d:
                        st.markdown("**Signal**")
                        st.json({
                            "model_prob": signal_d.get("model_prob"),
                            "market_price": signal_d.get("market_price"),
                            "gap_pp": signal_d.get("gap_pp"),
                            "confidence_score": signal_d.get("confidence_score"),
                            "physics_mean": signal_d.get("physics_mean"),
                            "ai_mean": signal_d.get("ai_mean"),
                            "nbm_p50": signal_d.get("nbm_p50"),
                            "metar_temp_f": signal_d.get("metar_temp_f"),
                            "hgefs_proxy": signal_d.get("hgefs_proxy"),
                            "trigger_reason": signal_d.get("trigger_reason"),
                            "reasoning": signal_d.get("reasoning"),
                        })

                if gate_d:
                    st.markdown("**Gate check (nearest)**")
                    for line in gate_explanation(gate_d):
                        st.markdown(f"- {line}")

# ===========================================================================
# TAB 4 — PERFORMANCE
# ===========================================================================
with tab_perf:
    st.subheader("Performance")

    curve = get_bankroll_curve(db)
    sleeve_stats = get_sleeve_stats(db)
    exit_stats = get_exit_reason_breakdown(db)
    daily = get_daily_performance(db, days=60)

    if not curve:
        st.info("No settled trades yet.")
    else:
        # Cumulative P&L chart
        df_curve = pd.DataFrame(curve)
        df_curve["cumulative_pnl"] = df_curve["net_pnl_maker"].astype(float).cumsum()
        df_curve["exit_time"] = pd.to_datetime(df_curve["exit_time"])
        df_curve = df_curve.set_index("exit_time")

        st.markdown("**Cumulative P&L**")
        st.line_chart(df_curve["cumulative_pnl"])

        total_pnl = float(df_curve["net_pnl_maker"].sum())
        n = len(df_curve)
        wins = int((df_curve["net_pnl_maker"] > 0).sum())
        max_dd = float(
            (df_curve["cumulative_pnl"] - df_curve["cumulative_pnl"].cummax()).min()
        )

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total P&L", _fmt_pnl(total_pnl))
        m2.metric("Trades", n)
        m3.metric("Win rate", f"{100*wins//n}%" if n else "—")
        m4.metric("Avg P&L/trade", _fmt_pnl(total_pnl / n if n else 0))
        m5.metric("Max drawdown", _fmt_pnl(max_dd))

        st.divider()

        # Sleeve breakdown
        if sleeve_stats:
            st.markdown("**By sleeve**")
            df_sl = pd.DataFrame(sleeve_stats)
            df_sl["win_rate"] = df_sl.apply(
                lambda r: f"{100*r['wins']//(r['wins']+r['losses'])}%"
                if (r["wins"] + r["losses"]) > 0 else "—",
                axis=1,
            )
            st.dataframe(df_sl, use_container_width=True, hide_index=True)

        # Exit reason breakdown
        if exit_stats:
            st.markdown("**By exit reason**")
            df_ex = pd.DataFrame(exit_stats)
            st.dataframe(df_ex, use_container_width=True, hide_index=True)

        # Daily P&L bar chart
        if daily:
            st.markdown("**Daily P&L (last 60 days)**")
            df_daily = pd.DataFrame(daily).set_index("date")
            st.bar_chart(df_daily["net_pnl_maker"])

# ===========================================================================
# TAB 5 — PIPELINE HEALTH
# ===========================================================================
with tab_health:
    st.subheader("Pipeline Health")

    gate_rates = get_gate_pass_rates(db, days=7)
    model_runs = get_recent_model_runs(db)
    funnel = get_candidate_funnel(db, days=7)

    # Gate pass rates (7 days)
    st.markdown("**Gate pass rates — last 7 days**")
    if gate_rates.get("total", 0) == 0:
        st.info("No gate checks in last 7 days.")
    else:
        gc1, gc2, gc3, gc4 = st.columns(4)
        gc1.metric("Gate 1", f"{gate_rates['gate1_pct']}%")
        gc2.metric("Gate 2", f"{gate_rates['gate2_pct']}%")
        gc3.metric("Gate 3", f"{gate_rates['gate3_pct']}%")
        gc4.metric("All pass", f"{gate_rates['all_pass_pct']}%")

        src1, src2 = st.columns(2)
        src1.metric("AIGEFS real", gate_rates["aigefs_real"])
        src2.metric("Wethr proxy", gate_rates["wethr_proxy"])

    st.divider()

    # Candidate funnel (7 days)
    st.markdown("**Candidate signal funnel — last 7 days**")
    if funnel["total"] == 0:
        st.info("No candidate signals in last 7 days.")
    else:
        st.metric("Total candidates evaluated", funnel["total"])
        df_funnel = pd.DataFrame(
            [{"status": k, "count": v} for k, v in funnel["by_status"].items()]
        ).sort_values("count", ascending=False)
        st.dataframe(df_funnel, use_container_width=True, hide_index=True)

    st.divider()

    # Recent model runs
    st.markdown("**Recent model runs (last 20)**")
    if model_runs:
        df_mr = pd.DataFrame(model_runs)
        df_mr["created_at"] = pd.to_datetime(df_mr["created_at"]).dt.strftime("%m-%d %H:%M")
        st.dataframe(df_mr, use_container_width=True, hide_index=True)
    else:
        st.info("No model runs recorded.")
