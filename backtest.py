"""
Backtest v6 — MULTI-PAIR DAY TRADING (BTCUSDT + ETHUSDT)
─────────────────────────────────────────────────────────
- 2 pairs × 3 strategies = 6 strategy instances → target 5-15 trades/day
- Strategies: Martingale (scalp) + Grid (range) + Donchian breakout
- Momentum permanently removed (0% WR, fires after the move)
- SMC optional (disabled by default — loses in choppy market)
- 7-day macro trend filter prevents counter-trend entries
- 15m timeframe: commission ratio ~22% (vs 67% on 5m)
- Shared equity pool across all pairs
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
from backend.app.strategies.martingale import MartingaleStrategy
from backend.app.strategies.grid import GridStrategy
from backend.app.strategies.donchian import DonchianStrategy
from backend.app.strategies.smc import SMCStrategy
from backend.app.exchange.binance_client import PaperBinanceClient

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOLS     = ["BTCUSDT", "ETHUSDT"]   # multi-pair day trading
TIMEFRAME   = "15m"
BAR_MINUTES = 15
DAYS        = 45
EQUITY      = 10_000.0
RISK_PCT    = 0.5            # 0.5% = $50 risk per trade (shared pool)
MAX_POS     = 16             # max concurrent positions (all pairs)
COMMISSION  = 0.04 / 100    # Binance Futures maker/taker ~0.04%
WARMUP      = 700            # 700 × 15m ≈ 7.3 days (macro filter needs 672)
MAX_BARS_OPEN = 192          # 192 × 15m = 48h max hold — gives TP more time to hit

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[94m"; NC = "\033[0m"

def col(v, prefix=""):
    return f"{G if v >= 0 else R}{prefix}{v:+.4f}{NC}"


# ── Data fetcher ──────────────────────────────────────────────────────────────
async def fetch_bars(exchange, symbol, tf, days):
    limit_per_req = 1000
    total_needed  = days * 24 * (60 // BAR_MINUTES)
    all_dfs = []
    since   = None

    print(f"  [{symbol}] Fetching ~{total_needed:,} bars ({tf})…", end="", flush=True)
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
            await asyncio.sleep(0.25)
            if len(all_dfs) * limit_per_req >= total_needed:
                break
        except Exception as e:
            print(f"\n  Batch error: {e}")
            break

    if not all_dfs:
        return pd.DataFrame()
    df = pd.concat(all_dfs[::-1]).drop_duplicates().sort_index()
    print(f" {len(df):,} bars")
    return df


# ── Strategy factory per symbol ───────────────────────────────────────────────
def make_strategies(symbol: str) -> dict:
    """Create a fresh set of strategies for one trading pair."""
    return {
        # Martingale: scalping workhorse — direction from macro trend
        # TP = 300 pips (not 150) → each win = $1.50 vs $0.28 commission (19% ratio, not 37%)
        "martingale": MartingaleStrategy(
            symbol, 0.01,
            multiplier=1.5,
            max_levels=1,             # NO escalation — level 0 only (pure directional scalp)
            pip_distance=100.0,       # not used with max_levels=1 (no level 1 trigger)
            take_profit_pips=300.0,   # TP = $300 from entry; commission ratio = 19%
            pip_value=1.0,
            require_ob=False,
        ),
        # Grid: range harvester with SuperTrend direction filter
        "grid": GridStrategy(
            symbol, 0.005,
            grid_spacing_pips=120.0,   # $120 spacing = more trades/day than $150
            take_profit_pips=120.0,
            max_orders=6,
            max_adverse_levels=3,
        ),
        # Donchian: disabled — only 31% WR in Jan-Mar 2026 BTC pump-dump market
        # Re-enable when there's a clear 5-10 day trend with ADX > 30
        # "donchian": DonchianStrategy(...),
    }


# ── Per-strategy position caps ────────────────────────────────────────────────
MAX_PER_STRAT = {
    "smc":        1,   # one structure trade at a time
    "martingale": 3,   # up to level 3 ladder
    "grid":       6,   # 6 grid levels
    "donchian":   1,   # one breakout trade per pair at a time
    "momentum":   1,
}


# ── Main backtest ─────────────────────────────────────────────────────────────
async def run_backtest():
    print(f"\n{'═'*66}")
    print(f"  PREDIC-BOT BACKTEST v6  —  MULTI-PAIR DAY TRADING")
    print(f"  Pairs: {' + '.join(SYMBOLS)}  |  {TIMEFRAME}  |  {DAYS}d  |  risk={RISK_PCT}%")
    print(f"  Strategies: martingale + grid + donchian  |  shared equity")
    print(f"{'═'*66}\n")

    exchange = PaperBinanceClient()
    symbol_data: dict[str, pd.DataFrame] = {}

    for sym in SYMBOLS:
        df = await fetch_bars(exchange, sym, TIMEFRAME, DAYS)
        if df.empty:
            print(f"ERROR: No data for {sym}")
            await exchange.close()
            return
        symbol_data[sym] = df

    await exchange.close()

    # Align all symbols on common timestamps (inner join)
    aligned_idx = None
    for sym, df in symbol_data.items():
        if aligned_idx is None:
            aligned_idx = df.index
        else:
            aligned_idx = aligned_idx.intersection(df.index)

    print(f"\n  Common bars: {len(aligned_idx):,}")
    for sym in SYMBOLS:
        symbol_data[sym] = symbol_data[sym].loc[aligned_idx]
        df = symbol_data[sym]
        warmup_price = float(df["close"].iloc[WARMUP])
        last_price   = float(df["close"].iloc[-1])
        print(f"  {sym}: {df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}"
              f"  {warmup_price:.2f} → {last_price:.2f}")

    total_bars  = len(aligned_idx)
    replay_bars = total_bars - WARMUP
    print(f"\n  Replay: {replay_bars:,} bars ≈ {replay_bars / (24 * 60 // BAR_MINUTES):.1f} days\n")

    # ── Init per-symbol strategies ────────────────────────────────────────────
    sym_strategies: dict[str, dict] = {sym: make_strategies(sym) for sym in SYMBOLS}
    for strategies in sym_strategies.values():
        for s in strategies.values():
            s.state.active = True

    risk      = RiskManager(
        max_open_positions=MAX_POS,
        risk_per_trade_pct=RISK_PCT,
        atr_lot_enabled=True,
        base_lot_size=0.005,
        max_daily_loss_usd=500.0,
        max_drawdown_pct=12.0,
    )
    portfolio = PortfolioStats()

    open_pos:  dict = {}
    next_id    = 1
    equity     = EQUITY
    peak_eq    = EQUITY
    max_dd     = 0.0
    trade_log  = []
    comm_total = 0.0

    print(f"▶ Replaying {replay_bars:,} bars × {len(SYMBOLS)} pairs…\n")

    for i in range(WARMUP, total_bars):
        bar_ts = aligned_idx[i]

        # ── Close open positions (check ALL symbols) ──────────────────────
        closed = []
        for pid, pos in open_pos.items():
            sym   = pos["symbol"]
            df_w  = symbol_data[sym]
            bar_h = float(df_w["high"].iloc[i])
            bar_l = float(df_w["low"].iloc[i])

            hit_tp = hit_sl = False
            if pos["side"] == "BUY":
                if pos["tp"] and bar_h >= pos["tp"]: hit_tp = True
                elif pos["sl"] and bar_l <= pos["sl"]: hit_sl = True
            else:
                if pos["tp"] and bar_l <= pos["tp"]: hit_tp = True
                elif pos["sl"] and bar_h >= pos["sl"]: hit_sl = True

            # Time-based exit: close after MAX_BARS_OPEN (day trading rule — no overnight holds)
            bars_held  = i - pos.get("opened_at", i)
            time_exit  = (bars_held >= MAX_BARS_OPEN) and not hit_tp and not hit_sl
            if time_exit:
                exit_at_close = float(symbol_data[sym]["close"].iloc[i])

            if hit_tp or hit_sl or time_exit:
                if hit_tp:
                    exit_px = pos["tp"]
                    reason  = "TP"
                elif hit_sl and pos["sl"]:
                    exit_px = pos["sl"]
                    reason  = "SL"
                else:
                    exit_px = exit_at_close if time_exit else float(symbol_data[sym]["close"].iloc[i])
                    reason  = "TIME"

                mult  = 1 if pos["side"] == "BUY" else -1
                gross = (exit_px - pos["entry"]) * pos["qty"] * mult
                comm  = (pos["entry"] + exit_px) * pos["qty"] * COMMISSION
                pnl   = gross - comm
                comm_total += comm
                equity     += pnl
                peak_eq     = max(peak_eq, equity)
                dd          = (peak_eq - equity) / peak_eq * 100
                max_dd      = max(max_dd, dd)

                sym_strategies[sym][pos["strategy"]].on_close(pnl)
                risk.on_position_closed(pnl, pos["qty"], exit_px)
                portfolio.record_from_dict(
                    pos["strategy"], pos["side"], pnl,
                    pos["entry"], exit_px, pos["qty"],
                )
                trade_log.append({
                    "time":     bar_ts.strftime("%m-%d %H:%M"),
                    "symbol":   sym,
                    "strategy": pos["strategy"],
                    "side":     pos["side"],
                    "entry":    pos["entry"],
                    "exit":     exit_px,
                    "pnl":      pnl,
                    "reason":   reason,
                })
                closed.append(pid)

        for pid in closed:
            del open_pos[pid]

        # ── Evaluate signals for each symbol ──────────────────────────────
        can, _ = risk.can_trade(equity)
        if not can:
            continue

        open_by_strat: dict[str, int] = {}
        for p in open_pos.values():
            key = f"{p['symbol']}_{p['strategy']}"
            open_by_strat[key] = open_by_strat.get(key, 0) + 1

        for sym in SYMBOLS:
            if len(open_pos) >= MAX_POS:
                break

            df_w      = symbol_data[sym].iloc[:i + 1]
            price     = float(df_w["close"].iloc[-1])
            indicators = ind_module.compute_all(df_w, bar_minutes=BAR_MINUTES)
            smc_result = smc_module.analyze(df_w)
            atr        = float(indicators.get("last", {}).get("atr") or price * 0.001)
            regime     = classify(smc_result, indicators)
            active_strats = regime.active_strategies

            for name, strat in sym_strategies[sym].items():
                if len(open_pos) >= MAX_POS:
                    break
                if name not in active_strats:
                    continue

                strat_key = f"{sym}_{name}"
                if open_by_strat.get(strat_key, 0) >= MAX_PER_STRAT.get(name, 2):
                    continue

                try:
                    signals = await strat.evaluate(df_w, smc_result, indicators, price)
                except Exception:
                    continue

                for sig in signals:
                    if len(open_pos) >= MAX_POS:
                        break
                    if open_by_strat.get(strat_key, 0) >= MAX_PER_STRAT.get(name, 2):
                        break

                    # Martingale uses fixed lot (strategy-defined) so SL doesn't amplify sizing
                    # Grid/SMC/Donchian use smart_lot (ATR-based risk sizing)
                    if name == "martingale":
                        lot = sig.quantity   # fixed lot from strategy (base_lot × multiplier^level)
                    else:
                        lot = risk.smart_lot(equity, price, sig.stop_loss, atr)
                    comm = price * lot * COMMISSION
                    comm_total += comm
                    equity     -= comm
                    risk.on_position_opened(lot, price)

                    pid = str(next_id); next_id += 1
                    open_pos[pid] = {
                        "symbol":    sym,
                        "strategy":  name,
                        "side":      sig.side,
                        "entry":     price,
                        "qty":       lot,
                        "sl":        sig.stop_loss,
                        "tp":        sig.take_profit,
                        "opened_at": i,   # bar index when opened
                    }
                    open_by_strat[strat_key] = open_by_strat.get(strat_key, 0) + 1

        # Progress every 500 bars
        if (i - WARMUP) % 500 == 0:
            pct = (i - WARMUP) / replay_bars * 100
            blk = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            c   = G if equity >= EQUITY else R
            tpd = len(trade_log) / max(1, (i - WARMUP) / (24 * 60 // BAR_MINUTES))
            print(f"  [{blk}] {pct:5.1f}%  eq={c}${equity:,.0f}{NC}"
                  f"  trades={len(trade_log)}({tpd:.1f}/d)  open={len(open_pos)}", end="\r")

    print("\n")

    # ── Force-close remaining positions ───────────────────────────────────────
    forced = 0
    for pid, pos in open_pos.items():
        sym        = pos["symbol"]
        last_price = float(symbol_data[sym]["close"].iloc[-1])
        mult       = 1 if pos["side"] == "BUY" else -1
        gross      = (last_price - pos["entry"]) * pos["qty"] * mult
        comm       = (pos["entry"] + last_price) * pos["qty"] * COMMISSION
        pnl        = gross - comm
        comm_total += comm
        equity     += pnl
        portfolio.record_from_dict(
            pos["strategy"], pos["side"], pnl,
            pos["entry"], last_price, pos["qty"],
        )
        trade_log.append({
            "time": "OPEN→CLOSE", "symbol": sym,
            "strategy": pos["strategy"], "side": pos["side"],
            "entry": pos["entry"], "exit": last_price,
            "pnl": pnl, "reason": "FORCED",
        })
        forced += 1

    # ── Results ───────────────────────────────────────────────────────────────
    metrics  = portfolio.compute()
    net_pnl  = equity - EQUITY
    pnl_pct  = net_pnl / EQUITY * 100
    winners  = [t for t in trade_log if t["pnl"] >= 0]
    losers   = [t for t in trade_log if t["pnl"] <  0]
    act_days = replay_bars / (24 * 60 // BAR_MINUTES)
    tpd      = len(trade_log) / max(1, act_days)

    print(f"{'═'*66}")
    print(f"  RESULTS — MULTI-PAIR DAY TRADING (15m)")
    print(f"{'═'*66}")
    c = G if net_pnl >= 0 else R
    print(f"\n  Starting equity         : ${EQUITY:,.2f}")
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

    # ── Per-pair breakdown ────────────────────────────────────────────────────
    print(f"\n{'─'*66}")
    print(f"  Per-Pair Breakdown")
    print(f"{'─'*66}")
    for sym in SYMBOLS:
        sym_trades = [t for t in trade_log if t["symbol"] == sym]
        if not sym_trades:
            print(f"  {sym:<10}  {Y}no signals{NC}")
            continue
        sym_wins = sum(1 for t in sym_trades if t["pnl"] >= 0)
        sym_pnl  = sum(t["pnl"] for t in sym_trades)
        wr_s     = sym_wins / len(sym_trades) * 100
        wrc_s    = G if wr_s >= 50 else Y if wr_s >= 40 else R
        pnl_c_s  = G if sym_pnl >= 0 else R
        tpd_s    = len(sym_trades) / max(1, act_days)
        print(f"  {sym:<10}  trades={len(sym_trades):4d}({tpd_s:.1f}/d)"
              f"  WR={wrc_s}{wr_s:5.1f}%{NC}  PnL={pnl_c_s}${sym_pnl:+,.4f}{NC}")

    # ── Per-strategy breakdown ────────────────────────────────────────────────
    print(f"\n{'─'*66}")
    print(f"  Per-Strategy Breakdown (all pairs combined)")
    print(f"{'─'*66}")
    by_strat: dict = {}
    for t in trade_log:
        s = by_strat.setdefault(t["strategy"], {"n": 0, "pnl": 0.0, "wins": 0})
        s["n"] += 1; s["pnl"] += t["pnl"]
        if t["pnl"] >= 0: s["wins"] += 1

    for name in ["donchian", "martingale", "grid", "smc", "momentum"]:
        s = by_strat.get(name)
        if not s or s["n"] == 0:
            continue
        wr    = s["wins"] / s["n"] * 100
        wrc   = G if wr >= 50 else Y if wr >= 40 else R
        pnl_c = G if s["pnl"] >= 0 else R
        tpd_s = s["n"] / max(1, act_days)
        print(f"  {name:<12}  trades={s['n']:4d}({tpd_s:.1f}/d)"
              f"  WR={wrc}{wr:5.1f}%{NC}  PnL={pnl_c}${s['pnl']:+,.4f}{NC}")

    # ── Last 20 trades ────────────────────────────────────────────────────────
    print(f"\n{'─'*66}")
    print(f"  Last 20 Closed Trades")
    print(f"{'─'*66}")
    print(f"  {'Time':<14} {'Sym':<8} {'Strat':<12} {'Side':<5} {'Entry':>9} {'Exit':>9} {'PnL':>9}  Reason")
    print(f"  {'─'*64}")
    for t in trade_log[-20:]:
        c = G if t["pnl"] >= 0 else R
        print(f"  {t['time']:<14} {t.get('symbol','?'):<8} {t['strategy']:<12} {t['side']:<5}"
              f" {t['entry']:>9.2f} {t['exit']:>9.2f} {c}{t['pnl']:>+9.4f}{NC}  {t['reason']}")

    print(f"\n{'═'*66}\n")


if __name__ == "__main__":
    asyncio.run(run_backtest())
