import { useEffect, useState } from "react";
import axios from "axios";

const MODES = ["paper", "signal", "auto", "both"] as const;

interface StrategyInfo {
  name: string;
  active: boolean;
  open_orders: number;
  daily_pnl: number;
  total_pnl: number;
  params: Record<string, number | string>;
}

export default function BotControl() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [mode, setMode] = useState("paper");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load current state from server on mount
  useEffect(() => {
    const load = async () => {
      try {
        const [stratRes, statusRes] = await Promise.all([
          axios.get("/api/strategies", { withCredentials: true }),
          axios.get("/api/trading/status", { withCredentials: true }),
        ]);
        setStrategies(stratRes.data);
        if (statusRes.data.mode) setMode(statusRes.data.mode);
      } catch (err) {
        console.error("Failed to load bot state", err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const toggleStrategy = async (name: string, current: boolean) => {
    setBusy(name);
    try {
      await axios.put(
        `/api/strategies/${name}`,
        { active: !current },
        { withCredentials: true }
      );
      setStrategies((prev) =>
        prev.map((s) => (s.name === name ? { ...s, active: !current } : s))
      );
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  };

  const changeMode = async (newMode: string) => {
    try {
      await axios.post("/api/trading/mode", { mode: newMode }, { withCredentials: true });
      setMode(newMode);
    } catch (err) {
      console.error(err);
    }
  };

  if (loading) {
    return (
      <div className="card">
        <div className="text-xs text-muted animate-pulse">Loading bot state…</div>
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">Bot Control</h2>

      {/* Mode selector */}
      <div>
        <p className="text-xs text-muted mb-2">Trading Mode</p>
        <div className="flex gap-2 flex-wrap">
          {MODES.map((m) => (
            <button
              key={m}
              onClick={() => changeMode(m)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                mode === m
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-border text-muted hover:border-slate-500"
              }`}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Strategies */}
      <div>
        <p className="text-xs text-muted mb-2">Strategies</p>
        <div className="space-y-2">
          {strategies.map((s) => (
            <div key={s.name} className="flex items-center justify-between">
              <div className="flex flex-col min-w-0">
                <span className="text-sm capitalize">{s.name}</span>
                <span className="text-[10px] text-muted">
                  {s.open_orders > 0 ? `${s.open_orders} open · ` : ""}
                  PnL: <span className={s.daily_pnl >= 0 ? "text-success" : "text-danger"}>
                    {s.daily_pnl >= 0 ? "+" : ""}{s.daily_pnl.toFixed(2)}
                  </span>
                </span>
              </div>
              <button
                disabled={busy === s.name}
                onClick={() => toggleStrategy(s.name, s.active)}
                className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ml-2 ${
                  s.active ? "bg-accent" : "bg-border"
                } disabled:opacity-50`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    s.active ? "translate-x-5" : ""
                  }`}
                />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
