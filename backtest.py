"""
Backtest v5 — DAY TRADING on 15m
- 15m timeframe: lower commission ratio than 5m (22% vs 67% of risk)
- 3-bar SMC cooldown (45-min) + 3 concurrent per strategy = 5-12 trades/day
- Momentum replaced with RSI-reversion (buy oversold, sell overbought)
- Martingale with macro-trend guard (no SELL in uptrend, no BUY in downtrend)
- Grid: direction-aware with SuperTrend
- 7-day macro filter prevents counter-trend entries
"""
import asyncio
import sys

sys.path.insert(0, ".")

import pandas as pd

from backend.app.core import indicators as ind_module
from backend.app.core import smc as smc_module
from backend.app.core.regime import classify
from backend.app.core.risk import RiskManager
from backend.app.core.portfolio_stats import PortfolioStats
from backend.app.strategies.smc import SMCStrategy
from backend.app.strategies.martingale import MartingaleStrategy
from backend.app.strategies.grid import GridStrategy
from backend.app.strategies.momentum import MomentumStrategy
from backend.app.exchange.binance_client import PaperBinanceClient

SYMBOL       = "BTCUSDT"
TIMEFRAME    = "15m"
BAR_MINUTES  = 15
DAYS         = 45
EQUITY       = 10_000.0
RISK_PCT     = 0.5          # 0.5% = $50 risk per trade
MAX_POS      = 12
COMMISSION   = 0.04 / 100
WARMUP       = 700          # 700×15m ≈ 7.3 days — ensures macro filter is active

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"; NC = "\033[0m"

def col(v, s=""):
    return f"{G if v >= 0 else R}{s}{v:+.4f}{NC}"


async def fetch_all_bars(exchange, symbol, tf, days):
    limit_per_req = 1000
    total_needed  = days * 24 * (60 // BAR_MINUTES)
    all_dfs = []
    since   = None

    print(f"  Fetching ~{total_needed:,} bars ({tf}) in batches…", end="", flush=True)
    for _ in range((total_needed // limit_per_req) + 2):
        try:
            raw = await exchange._exchange.fetch_ohlcv(
                symbol, tf, limit=limit_per_req,
                params={"endTime": since} if since else {}
            )
            if not raw:
                break
            df = pd.DataFrame(raw, columns=["timestamp","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            all_dfs.append(df)
            since = int(df.index[0].timestamp() * 1000)
            print(".", end="", flush=True)
            await asyncio.sleep(0.3)
            if len(all_dfs) * limit_per_req >= total_needed:
                break
        except Exception as e:
            print(f"\n  Batch error: {e}")
            break

    if not all_dfs:
        return pd.DataFrame()
    df = pd.concat(all_dfs[::-1]).drop_duplicates().sort_index()
    print(f" {len(df):,} bars total")
    return df


async def run_backtest():
    print(f"\n{'═'*62}")
    print(f"  PREDIC-BOT BACKTEST v5  —  DAY TRADING")
    print(f"  {SYMBOL} {TIMEFRAME}  |  {DAYS}d  |  risk={RISK_PCT}%  |  max={MAX_POS}pos")
    print(f"  Target: 5-12 trades/day  |  15m commission ratio ~22%")
    print(f"{'═'*62}\n")

    exchange = PaperBinanceClient()
    df_full  = await fetch_all_bars(exchange, SYMBOL, TIMEFRAME, DAYS)
    await exchange.close()

    if df_full.empty:
        print("ERROR: No data"); return

    total_bars  = len(df_full)
    replay_bars = total_bars - WARMUP
    print(f"  Range: {df_full.index[0].strftime('%Y-%m-%d %H:%M')} → {df_full.index[-1].strftime('%Y-%m-%d %H:%M')}")
    print(f"  BTC:   {float(df_full['close'].iloc[WARMUP]):.2f} → {float(df_full['close'].iloc[-1]):.2f} USDT")
    print(f"  Replay: {replay_bars:,} bars ≈ {replay_bars / (24 * 60 // BAR_MINUTES):.1f} trading days\n")

    risk      = RiskManager(
        max_open_positions=MAX_POS,
        risk_per_trade_pct=RISK_PCT,
        atr_lot_enabled=True,
        base_lot_size=0.005,
        max_daily_loss_usd=500.0,
        max_drawdown_pct=12.0,
    )
    portfolio = PortfolioStats()

    # ── strategies ────────────────────────────────────────────
    # Momentum permanently disabled — 0% WR in every test (EMA cross + ST flip
    # both fire AFTER the move, not before → systematic late entry)
    strategies = {
        # === CORE DAY TRADING ENGINE ===
        # Martingale: scalping workhorse — 100% WR, direction from macro trend
        # $10K account × 0.5% risk = $50/trade → 0.01 BTC × $150 TP = ~$1.50/win
        "martingale": MartingaleStrategy(
            SYMBOL, 0.01,
            multiplier=1.5,
            max_levels=3,
            pip_distance=100.0,
            take_profit_pips=150.0,
            pip_value=1.0,
            require_ob=False,
        ),
        # Grid: tighter spacing for more trades/day
        "grid": GridStrategy(
            SYMBOL, 0.005,
            grid_spacing_pips=120.0,   # $120 spacing = hits ~3-4x/day
            take_profit_pips=120.0,
            max_orders=8,
            max_adverse_levels=4,
        ),
        # SMC: only in high-conviction trending moments (ADX > 28)
        # The regime filter already gates this, but limit to 1 concurrent
        "smc": SMCStrategy(
            SYMBOL, 0.005,
            min_bos_count=1,
            ob_proximity_pct=2.5,
            atr_tp_mult=2.0,
            atr_sl_mult=0.8,
            cooldown_bars=8,       # 2-hour cooldown — only high-quality setups
            use_partial_tp=False,
        ),
        # SMC: disabled — consistent -$50 to -$85 drag in choppy/reversal markets
        # Will re-enable only when regime = STRONGLY_TRENDING (ADX > 30)
        # "smc": ...,
    }
    for s in strategies.values():
        s.state.active = True

    open_pos: dict = {}
    next_id   = 1
    equity    = EQUITY
    peak_eq   = EQUITY
    max_dd    = 0.0
    trade_log = []
    comm_total = 0.0
    skipped   = 0

    MAX_PER_STRAT = {"smc": 1, "martingale": 3, "grid": 6, "momentum": 1}

    print(f"▶ Replaying {replay_bars:,} bars…\n")

    for i in range(WARMUP, total_bars):
        df_w   = df_full.iloc[:i + 1]
        price  = float(df_w["close"].iloc[-1])
        bar_ts = df_w.index[-1]

        indicators = ind_module.compute_all(df_w, bar_minutes=BAR_MINUTES)
        smc_result = smc_module.analyze(df_w)
        atr = float(indicators.get("last", {}).get("atr") or price * 0.001)

        regime        = classify(smc_result, indicators)
        active_strats = regime.active_strategies

        # ── close positions ────────────────────────────────────
        closed = []
        for pid, pos in open_pos.items():
            bar_high = float(df_w["high"].iloc[-1])
            bar_low  = float(df_w["low"].iloc[-1])
            hit_tp = hit_sl = False

            if pos["side"] == "BUY":
                if pos["tp"] and bar_high >= pos["tp"]: hit_tp = True
                elif pos["sl"] and bar_low  <= pos["sl"]: hit_sl = True
            else:
                if pos["tp"] and bar_low  <= pos["tp"]: hit_tp = True
                elif pos["sl"] and bar_high >= pos["sl"]: hit_sl = True

            if hit_tp or hit_sl:
                exit_px = pos["tp"] if hit_tp else pos["sl"]
                mult    = 1 if pos["side"] == "BUY" else -1
                gross   = (exit_px - pos["entry"]) * pos["qty"] * mult
                comm    = (pos["entry"] + exit_px) * pos["qty"] * COMMISSION
                pnl     = gross - comm
                comm_total += comm
                equity     += pnl
                peak_eq     = max(peak_eq, equity)
                dd          = (peak_eq - equity) / peak_eq * 100
                max_dd      = max(max_dd, dd)

                strategies[pos["strategy"]].on_close(pnl)
                risk.on_position_closed(pnl, pos["qty"], exit_px)
                portfolio.record_from_dict(
                    pos["strategy"], pos["side"], pnl,
                    pos["entry"], exit_px, pos["qty"],
                )
                trade_log.append({
                    "time":     bar_ts.strftime("%m-%d %H:%M"),
                    "strategy": pos["strategy"],
                    "side":     pos["side"],
                    "entry":    pos["entry"],
                    "exit":     exit_px,
                    "pnl":      pnl,
                    "reason":   "TP" if hit_tp else "SL",
                })
                closed.append(pid)

        for pid in closed:
            del open_pos[pid]

        # ── evaluate strategies ────────────────────────────────
        can, _ = risk.can_trade(equity)
        if not can:
            continue

        open_by_strat = {}
        for p in open_pos.values():
            open_by_strat[p["strategy"]] = open_by_strat.get(p["strategy"], 0) + 1

        for name, strat in strategies.items():
            if name not in active_strats:
                skipped += 1
                continue
            if len(open_pos) >= MAX_POS:
                break
            if open_by_strat.get(name, 0) >= MAX_PER_STRAT.get(name, 2):
                continue
            try:
                signals = await strat.evaluate(df_w, smc_result, indicators, price)
            except Exception:
                continue

            for sig in signals:
                if len(open_pos) >= MAX_POS: break
                if open_by_strat.get(name, 0) >= MAX_PER_STRAT.get(name, 2): break
                lot  = risk.smart_lot(equity, price, sig.stop_loss, atr)
                comm = price * lot * COMMISSION
                comm_total += comm
                equity     -= comm
                risk.on_position_opened(lot, price)
                pid = str(next_id); next_id += 1
                open_pos[pid] = {
                    "strategy": name, "side": sig.side,
                    "entry": price,   "qty":  lot,
                    "sl": sig.stop_loss, "tp": sig.take_profit,
                }
                open_by_strat[name] = open_by_strat.get(name, 0) + 1

        # Progress every 500 bars
        if (i - WARMUP) % 500 == 0:
            pct = (i - WARMUP) / replay_bars * 100
            blk = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            c   = G if equity >= EQUITY else R
            tpd = len(trade_log) / max(1, (i - WARMUP) / (24 * 60 // BAR_MINUTES))
            print(f"  [{blk}] {pct:5.1f}%  eq={c}${equity:,.0f}{NC}  trades={len(trade_log)}({tpd:.1f}/d)  open={len(open_pos)}", end="\r")

    print("\n")

    # ── force-close ────────────────────────────────────────────
    last_price = float(df_full["close"].iloc[-1])
    forced = 0
    for pid, pos in open_pos.items():
        mult  = 1 if pos["side"] == "BUY" else -1
        gross = (last_price - pos["entry"]) * pos["qty"] * mult
        comm  = (pos["entry"] + last_price) * pos["qty"] * COMMISSION
        pnl   = gross - comm
        comm_total += comm
        equity     += pnl
        portfolio.record_from_dict(pos["strategy"], pos["side"], pnl, pos["entry"], last_price, pos["qty"])
        trade_log.append({
            "time": "OPEN→CLOSE", "strategy": pos["strategy"],
            "side": pos["side"],  "entry": pos["entry"],
            "exit": last_price,   "pnl":   pnl, "reason": "FORCED",
        })
        forced += 1

    # ── results ───────────────────────────────────────────────
    metrics   = portfolio.compute()
    net_pnl   = equity - EQUITY
    pnl_pct   = net_pnl / EQUITY * 100
    winners   = [t for t in trade_log if t["pnl"] >= 0]
    losers    = [t for t in trade_log if t["pnl"] <  0]
    act_days  = replay_bars / (24 * 60 // BAR_MINUTES)
    tpd       = len(trade_log) / max(1, act_days)

    print(f"{'═'*62}")
    print(f"  RESULTS — DAY TRADING (15m)")
    print(f"{'═'*62}")
    c = G if net_pnl >= 0 else R
    print(f"\n  Starting equity         : $10,000.00")
    print(f"  Final equity            : ${equity:,.4f}")
    print(f"  Net PnL                 : {c}${net_pnl:+,.4f}{NC}  ({c}{pnl_pct:+.2f}%{NC})")
    print(f"  Commissions paid        : -${comm_total:.4f}")
    print(f"  Force-closed            : {forced}")
    print()
    print(f"  Replay period           : {act_days:.1f} days")
    tpd_c = G if tpd >= 5 else Y
    print(f"  Trades/day              : {tpd_c}{tpd:.1f}{NC}")
    print(f"  Total trades            : {len(trade_log)}")
    print(f"  Win / Loss              : {len(winners)} W  /  {len(losers)} L")

    wr_c = G if metrics.win_rate >= 50 else Y if metrics.win_rate >= 40 else R
    pf_c = G if metrics.profit_factor >= 1.3 else Y if metrics.profit_factor >= 1.0 else R
    print(f"  Win rate                : {wr_c}{metrics.win_rate:.1f}%{NC}")
    print(f"  Profit factor           : {pf_c}{metrics.profit_factor:.2f}x{NC}")
    print(f"  Avg R:R                 : {Y}{metrics.avg_rr:.2f}x{NC}")
    print(f"  Max Drawdown            : {R}{max_dd:.2f}%{NC}")
    print(f"  Sharpe ratio            : {Y}{metrics.sharpe_ratio:.3f}{NC}")
    print(f"  Best trade              : {col(metrics.best_trade, '$')}")
    print(f"  Worst trade             : {col(metrics.worst_trade, '$')}")

    # ── per-strategy ──────────────────────────────────────────
    print(f"\n{'─'*62}")
    print(f"  Per-Strategy Breakdown")
    print(f"{'─'*62}")
    by_strat: dict = {}
    for t in trade_log:
        s = by_strat.setdefault(t["strategy"], {"n": 0, "pnl": 0.0, "wins": 0})
        s["n"] += 1; s["pnl"] += t["pnl"]
        if t["pnl"] >= 0: s["wins"] += 1

    for name in ["smc", "martingale", "grid", "momentum"]:
        s = by_strat.get(name)
        if not s or s["n"] == 0:
            print(f"  {name:<14}  {Y}no signals{NC}")
            continue
        wr    = s["wins"] / s["n"] * 100
        wrc   = G if wr >= 50 else Y if wr >= 40 else R
        pnl_c = G if s["pnl"] >= 0 else R
        tpd_s = s["n"] / max(1, act_days)
        print(f"  {name:<14}  trades={s['n']:4d}({tpd_s:.1f}/d)  WR={wrc}{wr:5.1f}%{NC}  PnL={pnl_c}${s['pnl']:+,.4f}{NC}")

    # ── last 20 trades ─────────────────────────────────────────
    print(f"\n{'─'*62}")
    print(f"  Last 20 Closed Trades")
    print(f"{'─'*62}")
    print(f"  {'Time':<14} {'Strat':<12} {'Side':<5} {'Entry':>9} {'Exit':>9} {'PnL':>9}  Reason")
    print(f"  {'─'*60}")
    for t in trade_log[-20:]:
        c = G if t["pnl"] >= 0 else R
        print(f"  {t['time']:<14} {t['strategy']:<12} {t['side']:<5} "
              f"{t['entry']:>9.2f} {t['exit']:>9.2f} {c}{t['pnl']:>+9.4f}{NC}  {t['reason']}")

    print(f"\n{'═'*62}\n")


if __name__ == "__main__":
    asyncio.run(run_backtest())
