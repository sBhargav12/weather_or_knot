from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data_store.db import Database
from paper_trader import config_paper
from paper_trader.policy import regime_for_date, target_month

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


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


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
        print_paper_strategy_health(db_path, report_date),
        "",
        print_sleeve_summary(db_path, report_date),
        "",
        print_strategy_deep_dive(db_path, report_date),
        "",
        print_gate_summary(db_path, report_date),
        "",
        print_model_availability(db_path, report_date),
        "",
        print_orderbook_quality(db_path, report_date),
        "",
        "DATA HEALTH",
        f"  DSM events detected: {len(dsm_rows)}",
        f"  CLI events detected: {len(cli_rows)}",
    ]
    return "\n".join(lines)


def generate_eod_summary(db_path: str, report_date: str | None = None) -> str:
    """Short phone-notification summary for end-of-day push."""
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    all_trades = _rows_for_day(db, "paper_trades", report_date)
    settled = [t for t in all_trades if _row_get(t, "exit_time") is not None]
    open_trades = [t for t in all_trades if _row_get(t, "exit_time") is None]
    total_pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in settled)
    total_wins = sum(1 for t in settled if float(_row_get(t, "net_pnl_maker") or 0) > 0)

    all_sleeves = list(config_paper.PAPER_SLEEVE_STATES.keys())
    lines = [f"P&L: ${total_pnl:+.2f} | {total_wins}/{len(settled)} wins | {len(open_trades)} open"]

    for sleeve in all_sleeves:
        sleeve_trades = [t for t in settled if str(_row_get(t, "strategy_sleeve") or "") == sleeve]
        if not sleeve_trades:
            continue
        sleeve_pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in sleeve_trades)
        sleeve_wins = sum(1 for t in sleeve_trades if float(_row_get(t, "net_pnl_maker") or 0) > 0)
        lines.append(f"  {sleeve}: {sleeve_wins}/{len(sleeve_trades)} wins ${sleeve_pnl:+.2f}")

    gate_rows = _rows_for_day(db, "gate_checks", report_date)
    if gate_rows:
        all_pass = sum(1 for r in gate_rows if _row_get(r, "all_pass") == 1)
        lines.append(f"  Gates: {all_pass}/{len(gate_rows)} passed")

    return "\n".join(lines)


def print_paper_strategy_health(db_path: str, report_date: str | None = None) -> str:
    """Report paper-policy state. This is not a live deployment report."""
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)
    candidates = _rows_for_day(db, "candidate_signals", report_date)
    trades = _rows_for_day(db, "paper_trades", report_date)
    month = target_month({"target_date": report_date})
    regime = regime_for_date(report_date)
    seasonal_mult = config_paper.PAPER_SEASONAL_MULTIPLIERS.get(month, 1.0)
    regime_mult = config_paper.PAPER_REGIME_MULTIPLIERS.get(regime, config_paper.PAPER_REGIME_MULTIPLIERS["unknown"])

    def count_candidate_status(status: str) -> int:
        return sum(1 for row in candidates if _row_get(row, "candidate_status") == status)

    def count_trade_sleeve(sleeve: str) -> int:
        return sum(1 for row in trades if str(_row_get(row, "strategy_sleeve", "")) == sleeve)

    sleeve_states = ", ".join(f"{name}={state}" for name, state in config_paper.PAPER_SLEEVE_STATES.items())
    weights = ", ".join(f"{name}:{weight:.3f}" for name, weight in config_paper.PAPER_ENSEMBLE_WEIGHTS.items())

    all_sleeves = list(config_paper.PAPER_SLEEVE_STATES.keys())
    sleeve_trade_lines = [f"    {s}: {count_trade_sleeve(s)}" for s in all_sleeves]

    lines = [
        "PAPER STRATEGY HEALTH (paper policy only; not live deployment)",
        f"  Current month: {month} (seasonal multiplier {seasonal_mult:.2f})",
        f"  Current regime: {regime} (regime multiplier {regime_mult:.2f})",
        f"  Calibrated probabilities in paper: {'YES' if config_paper.PAPER_USE_CALIBRATED_PROBS else 'NO'}",
        f"  Sleeve states: {sleeve_states}",
        (
            "  Wing/central policy: enabled; central net edge "
            f"{config_paper.PAPER_MIN_NET_EDGE_PP_CORE:.1f}pp, "
            f"wing {config_paper.PAPER_MIN_NET_EDGE_PP_WING:.1f}pp"
        ),
        (
            "  Execution-margin policy: raw edge - est execution cost - "
            f"{config_paper.PAPER_FEE_MARGIN_PP:.1f}pp fee margin"
        ),
        f"  Paper ensemble weights: {weights}",
        "  Candidate rejection counts:",
        f"    suspended_policy:          {count_candidate_status('suspended_policy')}",
        f"    low_core_confidence:       {count_candidate_status('rejected_low_core_confidence')}",
        f"    rejected_execution_margin: {count_candidate_status('rejected_execution_margin')}",
        f"    rejected_regime:           {count_candidate_status('rejected_regime')}",
        f"    rejected_seasonal:         {count_candidate_status('rejected_seasonal')}",
        f"    insufficient_liquidity:    {count_candidate_status('insufficient_liquidity')}",
        "  Paper trades by bracket family:",
        f"    central:     {sum(1 for t in trades if str(_row_get(t, 'bracket_family', '')) == 'central')}",
        f"    lower_tail:  {sum(1 for t in trades if str(_row_get(t, 'bracket_family', '')) == 'lower_tail')}",
        f"    upper_tail:  {sum(1 for t in trades if str(_row_get(t, 'bracket_family', '')) == 'upper_tail')}",
        "  Paper trades by sleeve:",
        *sleeve_trade_lines,
    ]
    return "\n".join(lines)


def print_sleeve_summary(db_path: str, report_date: str | None = None) -> str:
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    all_sleeves = list(config_paper.PAPER_SLEEVE_STATES.keys())
    lines = ["SIGNAL BREAKDOWN BY SLEEVE"]
    for sleeve in all_sleeves:
        sigs = _rows_for_day(db, "signals", report_date, " AND strategy_sleeve = ?", (sleeve,))
        trades = _rows_for_day(db, "paper_trades", report_date, " AND strategy_sleeve = ?", (sleeve,))
        settled = [t for t in trades if _row_get(t, "exit_time") is not None]
        pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in settled)
        wins = sum(1 for t in settled if float(_row_get(t, "net_pnl_maker") or 0) > 0)
        avg_conf = (
            sum(float(s["confidence_score"] or 0) for s in sigs) / len(sigs)
            if sigs else 0.0
        )
        pnl_str = f" P&L ${pnl:+.2f}" if settled else ""
        win_str = f" {wins}/{len(settled)} wins" if settled else ""
        lines.append(f"  {sleeve}: {len(sigs)} signals, {len(trades)} trades (avg conf: {avg_conf:.0f}){win_str}{pnl_str}")
    return "\n".join(lines)


def print_strategy_deep_dive(db_path: str, report_date: str | None = None) -> str:
    """Per-trade breakdown by sleeve with settlement accuracy."""
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    all_trades = _rows_for_day(db, "paper_trades", report_date)
    if not all_trades:
        return "STRATEGY DEEP DIVE\n  No trades today."

    # Group by sleeve
    sleeve_groups: dict[str, list] = {}
    for trade in all_trades:
        sleeve = str(_row_get(trade, "strategy_sleeve") or "CORE_HGEFS_GUMBEL")
        sleeve_groups.setdefault(sleeve, []).append(trade)

    lines = ["STRATEGY DEEP DIVE"]

    for sleeve in list(config_paper.PAPER_SLEEVE_STATES.keys()) + [
        s for s in sleeve_groups if s not in config_paper.PAPER_SLEEVE_STATES
    ]:
        trades = sleeve_groups.get(sleeve)
        if not trades:
            continue

        settled = [t for t in trades if _row_get(t, "exit_time") is not None]
        open_trades = [t for t in trades if _row_get(t, "exit_time") is None]
        pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in settled)
        wins = sum(1 for t in settled if float(_row_get(t, "net_pnl_maker") or 0) > 0)
        correct = [t for t in settled if _row_get(t, "settled_correct") == 1]

        header = (
            f"\n  [{sleeve}] {len(trades)} trade(s) | "
            f"settled: {len(settled)} | open: {len(open_trades)} | "
            f"P&L: ${pnl:+.2f} | wins: {wins}/{len(settled)}"
        )
        if settled:
            header += f" | bracket accuracy: {len(correct)}/{len(settled)}"
        lines.append(header)

        for trade in trades:
            ticker = str(_row_get(trade, "ticker") or "?")
            bracket = str(_row_get(trade, "bracket") or "?")
            direction = str(_row_get(trade, "direction") or "?")
            entry_price = float(_row_get(trade, "entry_price") or 0)
            contracts = int(_row_get(trade, "contracts") or 0)
            exit_price = _row_get(trade, "exit_price")
            exit_reason = str(_row_get(trade, "exit_reason") or "OPEN")
            net_pnl = float(_row_get(trade, "net_pnl_maker") or 0)
            settled_correct = _row_get(trade, "settled_correct")
            settlement_temp = _row_get(trade, "settlement_temp_f")
            model_prob = _row_get(trade, "model_prob")

            if exit_price is not None:
                status = f"${net_pnl:+.2f} ({exit_reason} @{float(exit_price):.2f})"
            else:
                status = f"OPEN @{entry_price:.2f}"

            accuracy = ""
            if settled_correct == 1:
                accuracy = " [CORRECT]"
            elif settled_correct == 0:
                accuracy = " [WRONG]"

            extra = ""
            if settlement_temp is not None:
                extra += f" settle={settlement_temp:.1f}F"
            if model_prob is not None:
                extra += f" model={float(model_prob):.1%}"

            lines.append(
                f"    {direction} {contracts}x {ticker} [{bracket}] "
                f"entry={entry_price:.2f} → {status}{accuracy}{extra}"
            )

    return "\n".join(lines)


def print_orderbook_quality(db_path: str, report_date: str | None = None) -> str:
    """Average orderbook spread per ticker for the day."""
    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)
    start_utc, end_utc = _report_window_utc(report_date)

    ob_rows = db.execute(
        """
        SELECT ticker, AVG(spread_cents) as avg_spread_cents, COUNT(*) as snapshots
        FROM kalshi_orderbook_snapshots
        WHERE created_at >= ? AND created_at < ? AND spread_cents IS NOT NULL
        GROUP BY ticker
        ORDER BY avg_spread_cents DESC
        LIMIT 15
        """,
        (start_utc, end_utc),
    )

    rest_rows = db.execute(
        """
        SELECT ticker, AVG(spread_cents) as avg_spread_cents, COUNT(*) as snapshots
        FROM kalshi_prices
        WHERE created_at >= ? AND created_at < ? AND spread_cents IS NOT NULL AND source = 'rest_poll'
        GROUP BY ticker
        ORDER BY avg_spread_cents DESC
        LIMIT 15
        """,
        (start_utc, end_utc),
    )

    lines = ["ORDERBOOK QUALITY"]
    if ob_rows:
        lines.append("  WebSocket spreads (¢) by ticker:")
        for row in ob_rows:
            lines.append(f"    {row['ticker']}: avg {float(row['avg_spread_cents']):.1f}¢ ({row['snapshots']} snapshots)")
    else:
        lines.append("  No WebSocket orderbook snapshots today.")

    if rest_rows:
        lines.append("  REST poll spreads (¢) by ticker:")
        for row in rest_rows[:5]:
            lines.append(f"    {row['ticker']}: avg {float(row['avg_spread_cents']):.1f}¢ ({row['snapshots']} polls)")
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
    real_aigefs = sum(1 for r in rows if r["gate1_ai_source"] == "aigefs_real")
    wethr_proxy = sum(1 for r in rows if r["gate1_ai_source"] == "wethr_proxy")

    lines = [
        "GATE PASS RATES TODAY",
        f"  Gate 1 (model convergence): {pct('gate1_pass')}",
        f"  Gate 2 (gap threshold):     {pct('gate2_pass')}",
        f"  Gate 3 (price band):        {pct('gate3_pass')}",
        "  Gate 4 (dead zone mod):     modifier only",
        "  Gate 5 (METAR):             modifier only",
        "  Gate 6 (reversal):          modifier only",
        f"  Combined Tier 1:            {tier1_pass}/{total} → ~{tier1_pass} signals/day",
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

    # Candidate signals summary — all sleeves
    candidates = _rows_for_day(db, "candidate_signals", report_date)
    lines.append("")
    lines.append("CANDIDATE SIGNALS TODAY")

    all_sleeves = list(config_paper.PAPER_SLEEVE_STATES.keys())
    core_candidates = [c for c in candidates if str(_row_get(c, "strategy_sleeve") or "") in {"CORE_HGEFS_GUMBEL", "CORE_HGEFS_EMOS", "CORE"}]
    passed = sum(1 for c in core_candidates if _row_get(c, "would_pass_core") == 1)
    lines.append(f"  Evaluated (core sleeve): {len(core_candidates)}")
    lines.append(f"  Passed Tier 1:           {passed}")

    for sleeve in all_sleeves:
        if sleeve in {"CORE_HGEFS_GUMBEL", "CORE_HGEFS_EMOS", "CORE"}:
            continue
        count = sum(1 for c in candidates if str(_row_get(c, "strategy_sleeve") or "") == sleeve)
        if count > 0:
            lines.append(f"  {sleeve} candidates:  {count}")

    return "\n".join(lines)


def generate_eod_llm_analysis(db_path: str, report_date: str | None = None) -> str:
    """Call Claude Sonnet to analyze the day's trading activity and give strategic commentary.

    Falls back to empty string if ANTHROPIC_API_KEY is not set or the call fails.
    This is a higher-level daily review distinct from per-signal Haiku synthesis.
    """
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    report_date = report_date or datetime.now(NY_TZ).date().isoformat()
    db = Database(db_path)

    all_trades = _rows_for_day(db, "paper_trades", report_date)
    settled = [t for t in all_trades if _row_get(t, "exit_time") is not None]
    open_trades = [t for t in all_trades if _row_get(t, "exit_time") is None]
    total_pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in settled)
    total_wins = sum(1 for t in settled if float(_row_get(t, "net_pnl_maker") or 0) > 0)

    gate_rows = _rows_for_day(db, "gate_checks", report_date)
    gate_total = len(gate_rows)
    gate_pass = sum(1 for r in gate_rows if _row_get(r, "all_pass") == 1)
    g1_pass = sum(1 for r in gate_rows if _row_get(r, "gate1_pass") == 1)
    g2_pass = sum(1 for r in gate_rows if _row_get(r, "gate2_pass") == 1)
    g3_pass = sum(1 for r in gate_rows if _row_get(r, "gate3_pass") == 1)

    sleeve_lines: list[str] = []
    for sleeve in config_paper.PAPER_SLEEVE_STATES:
        sl_trades = [t for t in settled if str(_row_get(t, "strategy_sleeve") or "") == sleeve]
        if not sl_trades:
            continue
        sl_pnl = sum(float(_row_get(t, "net_pnl_maker") or 0) for t in sl_trades)
        sl_wins = sum(1 for t in sl_trades if float(_row_get(t, "net_pnl_maker") or 0) > 0)
        correct = sum(1 for t in sl_trades if _row_get(t, "settled_correct") == 1)
        sleeve_lines.append(
            f"  {sleeve}: {sl_wins}/{len(sl_trades)} wins ${sl_pnl:+.2f} "
            f"bracket_accuracy={correct}/{len(sl_trades)}"
        )

    trade_lines: list[str] = []
    for trade in settled:
        sleeve = str(_row_get(trade, "strategy_sleeve") or "CORE")
        direction = str(_row_get(trade, "direction") or "?")
        bracket = str(_row_get(trade, "bracket") or "?")
        entry = float(_row_get(trade, "entry_price") or 0)
        exit_p = float(_row_get(trade, "exit_price") or 0)
        pnl = float(_row_get(trade, "net_pnl_maker") or 0)
        reason = str(_row_get(trade, "exit_reason") or "?")
        model_prob = _row_get(trade, "model_prob")
        settle_f = _row_get(trade, "settlement_temp_f")
        correct = _row_get(trade, "settled_correct")
        trade_lines.append(
            f"  [{sleeve}] {direction} {bracket} entry={entry:.2f} exit={exit_p:.2f} "
            f"({reason}) P&L=${pnl:+.2f}"
            + (f" model={float(model_prob):.1%}" if model_prob is not None else "")
            + (f" settle={settle_f:.1f}F" if settle_f is not None else "")
            + (f" {'CORRECT' if correct == 1 else 'WRONG'}" if correct is not None else "")
        )

    start_utc, end_utc = _report_window_utc(report_date)
    hgefs = db.execute(
        "SELECT physics_mean, ai_mean FROM model_runs "
        "WHERE model = 'HGEFS' AND created_at >= ? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
        (start_utc, end_utc),
    )
    model_line = "HGEFS unavailable today"
    if hgefs:
        pm = hgefs[0]["physics_mean"]
        am = hgefs[0]["ai_mean"]
        model_line = (
            f"HGEFS physics={f'{pm:.1f}°F' if pm else 'N/A'} "
            f"AI={f'{am:.1f}°F' if am else 'proxy/N/A'}"
        )

    ob_rows = db.execute(
        "SELECT AVG(spread_cents) as avg_sc FROM kalshi_orderbook_snapshots "
        "WHERE created_at >= ? AND created_at < ? AND spread_cents IS NOT NULL",
        (start_utc, end_utc),
    )
    avg_spread = float(ob_rows[0]["avg_sc"]) if ob_rows and ob_rows[0]["avg_sc"] else None

    prompt = (
        f"You are a quantitative trading analyst reviewing end-of-day results for a "
        f"Kalshi temperature bracket paper-trading system.\n\n"
        f"Date: {report_date}\n"
        f"Active sleeves: S3_BRACKET_LOCK_YES (3PM intraday YES on confirmed bracket), "
        f"S1_FAR_BRACKET_NO_OVERLAY (NO on losing brackets), "
        f"LADDER_EVENT (morning YES/NO portfolio), "
        f"CORE_HGEFS_EMOS (gate-based directional trades)\n\n"
        f"== TODAY'S METRICS ==\n"
        f"Overall: {len(settled)} settled | {total_wins}/{len(settled)} wins | "
        f"P&L ${total_pnl:+.2f} | {len(open_trades)} open\n"
        f"Model: {model_line}\n"
        f"Avg orderbook spread: {f'{avg_spread:.1f}¢' if avg_spread else 'N/A'}\n\n"
        f"Gate funnel (CORE sleeve):\n"
        f"  Evaluated: {gate_total} | G1 convergence: {g1_pass}/{gate_total} | "
        f"G2 gap: {g2_pass}/{gate_total} | G3 price: {g3_pass}/{gate_total} | "
        f"All-pass: {gate_pass}/{gate_total}\n\n"
        f"Sleeve P&L:\n"
        f"{chr(10).join(sleeve_lines) if sleeve_lines else '  No settled trades.'}\n\n"
        f"Settled trades:\n"
        f"{chr(10).join(trade_lines) if trade_lines else '  None.'}\n\n"
        f"== ANALYSIS TASK ==\n"
        f"Write 4–6 sentences of plain prose covering:\n"
        f"1. Is today's gate pass rate ({gate_pass}/{gate_total}) normal or does it "
        f"indicate model disagreement / bad liquidity?\n"
        f"2. Did the new sleeves (S3, S1, LADDER) perform as expected? Any concerns?\n"
        f"3. Was the P&L outcome consistent with the model signals and entry prices?\n"
        f"4. One specific thing to watch or change tomorrow.\n\n"
        f"Be direct and quantitative. No bullet points. No headers. Plain paragraph prose."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text.strip()
        return f"\nEOD ANALYSIS (Claude Sonnet)\n{analysis}\n"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("EOD LLM analysis failed: %s", exc)
        return ""
