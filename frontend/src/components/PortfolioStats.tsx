import { useEffect, useState } from "react";
import axios from "axios";

interface Stats {
  total_trades: number;
  win_rate: number;
  sharpe_ratio: number;
  profit_factor: number;
  max_drawdown_pct: number;
  avg_rr: number;
  total_pnl: number;
  daily_pnl: number;
  best_trade: number;
  worst_trade: number;
  by_strategy: Record<string, { trades: number; pnl: number; win_rate: number }>;
}

interface Risk {
  daily_pnl: number;
  drawdown_pct: number;
  peak_equity: number;
  open_positions: number;
  total_exposure_usd: number;
  circuit_breaker: boolean;
}

function Stat({ label, value, suffix = "", color }: {
  label: string; value: string | number; suffix?: string; color?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-muted">{label}</span>
      <span className={`text-sm font-semibold ${color || "text-slate-200"}`}>
        {value}{suffix}
      </span>
    </div>
  );
}

export default function PortfolioStats({ refreshTick }: { refreshTick?: number }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [risk, setRisk]   = useState<Risk | null>(null);

  const load = async () => {
    try {
      const [s, r] = await Promise.all([
        axios.get<Stats>("/api/portfolio/stats", { withCredentials: true }),
        axios.get<Risk>("/api/portfolio/risk",  { withCredentials: true }),
      ]);
      setStats(s.data);
      setRisk(r.data);
    } catch { /* unauthenticated or engine down — silently ignore */ }
  };

  useEffect(() => { load(); }, [refreshTick]);

  if (!stats && !risk) return null;

  const pnlColor = (v: number) => v >= 0 ? "text-success" : "text-danger";

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">Portfolio Stats</h2>
        {risk?.circuit_breaker && (
          <span className="badge badge-danger animate-pulse">Circuit Breaker</span>
        )}
      </div>

      {/* PnL row */}
      <div className="grid grid-cols-2 gap-3">
        <Stat
          label="Daily PnL"
          value={stats ? (stats.daily_pnl >= 0 ? "+" : "") + stats.daily_pnl.toFixed(4) : "—"}
          color={stats ? pnlColor(stats.daily_pnl) : ""}
        />
        <Stat
          label="Total PnL"
          value={stats ? (stats.total_pnl >= 0 ? "+" : "") + stats.total_pnl.toFixed(4) : "—"}
          color={stats ? pnlColor(stats.total_pnl) : ""}
        />
      </div>

      {/* Performance metrics */}
      {stats && stats.total_trades > 0 && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat
              label="Win Rate"
              value={stats.win_rate.toFixed(1)}
              suffix="%"
              color={stats.win_rate >= 50 ? "text-success" : "text-danger"}
            />
            <Stat
              label="Profit Factor"
              value={stats.profit_factor === Infinity ? "∞" : stats.profit_factor.toFixed(2)}
              color={stats.profit_factor >= 1.5 ? "text-success" : stats.profit_factor >= 1 ? "text-warning" : "text-danger"}
            />
            <Stat
              label="Avg R:R"
              value={stats.avg_rr.toFixed(2)}
              color={stats.avg_rr >= 1.5 ? "text-success" : "text-warning"}
            />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Stat
              label="Sharpe"
              value={stats.sharpe_ratio.toFixed(2)}
              color={stats.sharpe_ratio >= 1 ? "text-success" : stats.sharpe_ratio >= 0 ? "text-warning" : "text-danger"}
            />
            <Stat
              label="Max DD"
              value={stats.max_drawdown_pct.toFixed(1)}
              suffix="%"
              color={stats.max_drawdown_pct < 5 ? "text-success" : stats.max_drawdown_pct < 10 ? "text-warning" : "text-danger"}
            />
            <Stat label="Trades" value={stats.total_trades} />
          </div>

          <div className="grid grid-cols-2 gap-3 text-[10px]">
            <div>
              <span className="text-muted">Best</span>
              <span className="ml-1 text-success">+{stats.best_trade.toFixed(4)}</span>
            </div>
            <div>
              <span className="text-muted">Worst</span>
              <span className="ml-1 text-danger">{stats.worst_trade.toFixed(4)}</span>
            </div>
          </div>
        </>
      )}

      {/* Risk state */}
      {risk && (
        <div className="border-t border-border pt-3 grid grid-cols-2 gap-3">
          <Stat
            label="Drawdown"
            value={risk.drawdown_pct.toFixed(1)}
            suffix="%"
            color={risk.drawdown_pct < 5 ? "text-success" : risk.drawdown_pct < 10 ? "text-warning" : "text-danger"}
          />
          <Stat label="Open Positions" value={risk.open_positions} />
          <Stat label="Exposure (USDT)" value={risk.total_exposure_usd.toFixed(2)} />
          <Stat label="Peak Equity" value={risk.peak_equity.toFixed(2)} />
        </div>
      )}

      {/* Per-strategy breakdown */}
      {stats && Object.keys(stats.by_strategy).length > 0 && (
        <div className="border-t border-border pt-3">
          <p className="text-[10px] text-muted mb-2">By Strategy</p>
          <div className="space-y-1">
            {Object.entries(stats.by_strategy).map(([name, s]) => (
              <div key={name} className="flex items-center justify-between text-xs">
                <span className="capitalize text-slate-300">{name}</span>
                <div className="flex gap-3 text-muted">
                  <span>{s.trades} trades</span>
                  <span className={s.win_rate >= 50 ? "text-success" : "text-danger"}>
                    {s.win_rate}% WR
                  </span>
                  <span className={s.pnl >= 0 ? "text-success" : "text-danger"}>
                    {s.pnl >= 0 ? "+" : ""}{s.pnl.toFixed(4)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats && stats.total_trades === 0 && (
        <p className="text-xs text-muted text-center py-2">ยังไม่มี trade — เปิด strategy แล้วรอ signal</p>
      )}
    </div>
  );
}
