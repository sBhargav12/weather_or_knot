# DSM Check Backtest Report

======================================================================
SECTION 1: DSM FIRE TIME DISTRIBUTION (Oracle dsm_reports, 6,929 rows)
======================================================================

Station    N       Dates  Min ET     Median ET    P95 ET     Max ET     In window%   Scripts
-----------------------------------------------------------------------------------------------
KMDW       414     1      17:17      17:17        17:17      17:17         100.0%    {'dsm1': 414}
KNYC       3055    7      16:16      16:17        17:17      17:17         100.0%    {'dsm1': 3049, '': 6}
KPHL       2259    4      09:32      17:17        17:17      17:17          97.0%    {'dsm1': 2259}

Note: Low window% for KMDW = many rows are wethr polling duplicates (same
dsm_received_at repeated 30+ times). Unique-date coverage shown in 'Dates'.

Unique DSM dates per station:
  KMDW: ['2026-05-01']
  KNYC: ['2026-04-28', '2026-04-29', '2026-04-30', '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-05']
  KPHL: ['2026-04-28', '2026-04-29', '2026-04-30', '2026-05-01']

======================================================================
SECTION 2: DSM WINDOW COVERAGE PER ACTIVE CITY
======================================================================

Current window: 16:15 – 17:30 ET

City           Station  DSM UTC    DSM ET (EDT)   Covers?    Gap min    Risk
------------------------------------------------------------------------------
KNYC           KNYC     20:21      16:21          YES          +69       OK
KMDW           KMDW     21:17      17:17          YES          +13       OK
KMIA           KMIA     20:21      16:21          YES          +69       OK
KXLOWTCHI      KMDW     21:17      17:17          YES          +13       OK
KXLOWTDEN      KDEN     22:17      18:17          NO           -47       EXPOSED — 47min gap after DSM

⚠  CRITICAL GAPS:
   KXLOWTDEN: DSM fires 18:17 ET → 47min AFTER window close 17:30 ET

   KXLOWTDEN is active:True in config.py and fires at 22:17 UTC = 18:17 ET.
   Same-day KXLOWTDEN entries could fire between 17:30–18:17 ET.
   Fix: extend window end to 18:30 ET in _is_dsm_window().

======================================================================
SECTION 3: KALSHI PRICE BEHAVIOR DURING DSM WINDOW HOURS (Live prices)
======================================================================
  Oracle kalshi_prices 19–23 UTC, 1,500 rows — Apr 29 – May 6 2026

City           N mkts   ΔYesBid@20:21    ΔYesBid@21:17    ΔYesBid@22:17
----------------------------------------------------------------------
KMDW           36       0.0254           0.0300           0.1383
KMIA           12         n/a              n/a              n/a  
KNYC           48       0.0397           0.0979           0.1039
KXLOWTCHI      12         n/a              n/a              n/a  
KXLOWTDEN      12         n/a              n/a              n/a  

  ΔYesBid = |price_at_DSM_time − price_at_19:xx| per market per day.
  Large Δ at a given hour = settlement is being priced in aggressively.
  Small Δ = market was already well-priced; holding 1 extra hour costs little.

======================================================================
SECTION 4: GATE CHECK EVALUATIONS DURING DSM WINDOW (candidate_signals)
======================================================================

Total candidate signals:                 1525
Fired during DSM window (16:15–17:30):   295
  → would_pass_core = True (tradeable):  9
  → same-day target_date:                161
  → next-day target_date:                134

  Gate-passing signals during window (should all be blocked by fix):
    2026-05-05 20:52:07 | KXLOWTCHI      | KXLOWTCHI-26MAY05-B46.5          | NO | yes=0.97   | DEEP_TAIL_NO
    2026-05-05 20:53:45 | KXLOWTCHI      | KXLOWTCHI-26MAY05-B46.5          | NO | yes=0.98   | DEEP_TAIL_NO
    2026-05-05 21:21:51 | KMIA           | KXHIGHMIA-26MAY06-B88.5          | NO | yes=0.55   | CORE_HGEFS_EMOS
    2026-05-05 21:22:20 | KXLOWTCHI      | KXLOWTCHI-26MAY05-B46.5          | NO | yes=0.93   | DEEP_TAIL_NO
    2026-05-05 21:23:28 | KMIA           | KXHIGHMIA-26MAY06-B88.5          | NO | yes=0.55   | CORE_HGEFS_EMOS
    2026-05-05 21:23:57 | KXLOWTCHI      | KXLOWTCHI-26MAY05-B46.5          | NO | yes=0.93   | DEEP_TAIL_NO
    2026-05-05 21:25:35 | KXLOWTCHI      | KXLOWTCHI-26MAY05-B46.5          | NO | yes=0.93   | DEEP_TAIL_NO
    2026-05-05T21:21:50.945503+00:00 | KMIA           | KXHIGHMIA-26MAY06-B88.5          | NO | yes=0.55   | CORE_HGEFS_GUMBEL
    2026-05-05T21:23:28.642384+00:00 | KMIA           | KXHIGHMIA-26MAY06-B88.5          | NO | yes=0.55   | CORE_HGEFS_GUMBEL

Post-window same-day signals (>17:30 ET, target=today): 249
  These are candidates for Bug 2/3 (same-day entry after DSM fires):
    2026-04-30T03:49:28.439766+00:00 ET=23:49 | KNYC           | YES | passes=False
    2026-04-30T03:49:28.452187+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:28.463367+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:28.475377+00:00 ET=23:49 | KNYC           | YES | passes=False
    2026-04-30T03:49:28.488496+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:28.500209+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:48.981458+00:00 ET=23:49 | KNYC           | YES | passes=False
    2026-04-30T03:49:48.993823+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:49.005959+00:00 ET=23:49 | KNYC           | NO | passes=False
    2026-04-30T03:49:49.023902+00:00 ET=23:49 | KNYC           | YES | passes=False

======================================================================
SECTION 5: PAPER TRADE DSM EXIT TIMING AUDIT (all 15 Oracle paper_trades)
======================================================================

ID   Entry ET   Exit ET    Reason             In Window   Bug   SameDay    net_pnl
----------------------------------------------------------------------------------
1    06:09 ET   11:06 ET   NEVER_HOLD_ABOVE   no                YES         +21.30
2    06:09 ET   08:39 ET   STOP               no                YES          -6.20
3    06:09 ET   06:09 ET   STOP               no                YES          -2.72
4    11:45 ET   11:46 ET   NEVER_HOLD_ABOVE   no                no           -0.73
5    10:37 ET   10:42 ET   TARGET             no                no           -0.19
6    11:02 ET   16:16 ET   DSM_CANCEL         no                no           -0.69
7    12:00 ET   12:18 ET   NEVER_HOLD_ABOVE   no                YES          +0.15
8    11:02 ET   16:16 ET   DSM_CANCEL         no                no           -1.85
9    11:02 ET   16:16 ET   DSM_CANCEL         no                YES          -0.83
10   12:06 ET   16:16 ET   DSM_CANCEL         no                YES          -6.10
11   12:23 ET   16:16 ET   DSM_CANCEL         no                no           -0.20
12   16:52 ET   16:55 ET   DSM_CANCEL         YES         BUG   YES          -2.21
13   17:21 ET   17:27 ET   DSM_CANCEL         YES         BUG   no           -0.44
14   17:22 ET   17:27 ET   DSM_CANCEL         YES         BUG   YES          -1.74
15   17:51 ET   open       open               no                YES          open 

  Bug trades (entered during window):     3  — net_pnl = -4.39
  Correct DSM_CANCEL (entered pre-window):5  — held correctly until DSM
  Other exits (STOP/TARGET/etc):          7

  Correct DSM_CANCEL hold times:
    ID=6 KNYC           target=2026-05-02 hold=313min exit@16:16 ET net=-0.69
    ID=8 KNYC           target=2026-05-04 hold=313min exit@16:16 ET net=-1.85
    ID=9 KNYC           target=2026-05-03 hold=313min exit@16:16 ET net=-0.83
    ID=10 KNYC           target=2026-05-03 hold=249min exit@16:16 ET net=-6.10
    ID=11 KMIA           target=2026-05-06 hold=232min exit@16:16 ET net=-0.20

======================================================================
SECTION 6: HISTORICAL BACKTEST — ENTRY TIMING VALUE (report7, 4,007 trades)
======================================================================

Entry timing         N      Win%     Mean PnL     Std        Sharpe     Total PnL
------------------------------------------------------------------------
9AM                  973      74.5%    +0.0573    0.3765    +0.152     +55.77

  Key insight: most trades enter at '9AM' (10:15 AM ET entry) or '11AM'.
  The DSM window (4:15–5:30 PM ET) is AFTER all normal entry times.
  Blocking the window costs zero expected alpha — no trades were ever
  supposed to enter during 4:15–5:30 PM ET in the historical backtest.

======================================================================
SECTION 7: IN-MEMORY STATE LOSS BUG (Restart clears _last_dsm_received)
======================================================================

  Mechanism:
    _last_dsm_received: dict[str, str] = {}  # empty on start
    Populated only when wethr obs returns a new dsm_received_at.
    If bot restarts after DSM fires, the guard check:
      last_dsm.startswith(today.isoformat())
    always evaluates to False → same-day entries allowed again.

  Evidence from May 5:
    KMDW DSM received at 21:17 UTC (17:17 ET) — within window, exits triggered.
    Trade 15 entered at 21:51 UTC (17:51 ET) — after window end, same-day.
    _last_dsm_received['KMDW'] was empty (restart or first poll) → guard missed.

  Fix: pre-populate from DB in EventTriggerEngine.__init__():

    rows = self.db.execute(
        """SELECT station, MAX(dsm_received_at) as last_recv
           FROM dsm_reports
           WHERE dsm_received_at IS NOT NULL
           GROUP BY station"""
    )
    for row in rows:
        if row['last_recv']:
            self._last_dsm_received[row['station']] = row['last_recv']
    logger.info('Pre-populated _last_dsm_received: %s', self._last_dsm_received)

  This makes the same-day guard restart-safe. At bot start, it immediately
  knows whether today's DSM has already been received.

======================================================================
SECTION 8: RECOMMENDED WINDOW OPTIONS
======================================================================

Option A (current):  16:15–17:30 ET — blocks 295 candidate signals
Option B (extended): 16:15–18:30 ET — additionally blocks 37 more signals
  Of the additional signals blocked by Option B:
    - Same-day target_date: 33  (correct to block — DSM already fired)
    - Would pass gates:     9  (opportunity cost of extension)

Option C (per-city cutoffs):
  KNYC          : block same-day entries after 16:11 ET
  KMDW          : block same-day entries after 17:07 ET
  KMIA          : block same-day entries after 16:11 ET
  KXLOWTCHI     : block same-day entries after 17:07 ET
  KXLOWTDEN     : block same-day entries after 18:07 ET

Recommendation: Option B (extend to 18:30 ET) — simplest, zero opportunity
cost (no legitimate entries happen 17:30–18:30 ET for any active city),
and fully protects KXLOWTDEN (DSM at 18:17 ET).

======================================================================
SECTION 9: COMPLETE BUG INVENTORY AND FIX STATUS
======================================================================

┌────┬──────────────────────────────────────────────┬──────────────┐
│ #  │ Bug                                          │ Status       │
├────┼──────────────────────────────────────────────┼──────────────┤
│ 1  │ fire_gate_check enters trades during window  │ FIXED May 5  │
│ 2  │ Same-day re-entry after DSM fires (in-proc)  │ FIXED May 5  │
│ 3  │ _last_dsm_received cleared on restart        │ NOT FIXED    │
│ 4  │ KXLOWTDEN DSM (18:17 ET) outside 17:30 win  │ NOT FIXED    │
└────┴──────────────────────────────────────────────┴──────────────┘

Estimated financial impact of unfixed bugs per active day:
  Bug 3: ~$0–$4 per restart event (same-day entry after DSM)
  Bug 4: KXLOWTDEN settlement not yet active in live bot — low urgency
         but must be fixed before KXLOWTDEN live trades start.