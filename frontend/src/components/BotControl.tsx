import { useState } from "react";
import axios from "axios";

const STRATEGIES = ["martingale", "grid", "momentum"] as const;
type Strategy = (typeof STRATEGIES)[number];
const MODES = ["paper", "signal", "auto", "both"] as const;

export default function BotControl() {
  const [activeStrategies, setActiveStrategies] = useState<Record<Strategy, boolean>>({
    martingale: false,
    grid: false,
    momentum: false,
  });
  const [mode, setMode] = useState("paper");
  const [busy, setBusy] = useState(false);

  const toggleStrategy = async (name: Strategy) => {
    setBusy(true);
    const newVal = !activeStrategies[name];
    try {
      await axios.post("/api/trading/strategy", { name, active: newVal }, { withCredentials: true });
      setActiveStrategies((prev) => ({ ...prev, [name]: newVal }));
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
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
          {STRATEGIES.map((name) => (
            <div key={name} className="flex items-center justify-between">
              <span className="text-sm capitalize">{name}</span>
              <button
                disabled={busy}
                onClick={() => toggleStrategy(name)}
                className={`relative w-11 h-6 rounded-full transition-colors ${
                  activeStrategies[name] ? "bg-accent" : "bg-border"
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    activeStrategies[name] ? "translate-x-5" : ""
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
