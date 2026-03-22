import { useEffect, useState } from "react";
import axios from "axios";

interface StrategyDetail {
  name: string;
  active: boolean;
  params: Record<string, number | string>;
  state: Record<string, unknown>;
  pnl: { daily: number; total: number };
  open_orders: Array<Record<string, unknown>>;
}

const PARAM_LABELS: Record<string, Record<string, string>> = {
  smc: {
    min_bos_count: "Min BOS Count",
    ob_proximity_pct: "OB Proximity %",
    atr_tp_mult: "ATR TP Mult",
    atr_sl_mult: "ATR SL Mult",
    cooldown_bars: "Cooldown Bars",
    require_mtf_align: "Require MTF Align",
  },
  martingale: {
    multiplier: "Multiplier",
    max_levels: "Max Levels",
    pip_distance: "Pip Distance",
    take_profit_pips: "TP (pips)",
    pip_value: "Pip Value",
  },
  grid: {
    grid_spacing_pips: "Grid Spacing (pips)",
    take_profit_pips: "TP (pips)",
    max_orders: "Max Orders",
    pip_value: "Pip Value",
  },
  momentum: {
    fast_ema: "Fast EMA",
    slow_ema: "Slow EMA",
    rsi_bull: "RSI Bull",
    rsi_bear: "RSI Bear",
    atr_tp_mult: "ATR TP Mult",
    atr_sl_mult: "ATR SL Mult",
    cooldown_bars: "Cooldown Bars",
  },
};

function StrategyCard({ name }: { name: string }) {
  const [detail, setDetail] = useState<StrategyDetail | null>(null);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = async () => {
    try {
      const r = await axios.get(`/api/strategies/${name}`, { withCredentials: true });
      setDetail(r.data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    load();
  }, [name]);

  const dirty = Object.keys(editing);

  const handleSave = async () => {
    if (!dirty.length) return;
    setSaving(true);
    try {
      const params: Record<string, number | string> = {};
      for (const [k, v] of Object.entries(editing)) {
        params[k] = isNaN(Number(v)) ? v : Number(v);
      }
      await axios.put(`/api/strategies/${name}`, { params }, { withCredentials: true });
      setEditing({});
      setMsg({ text: "บันทึกแล้ว", ok: true });
      await load();
    } catch {
      setMsg({ text: "บันทึกไม่สำเร็จ", ok: false });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm(`Reset state of ${name}?`)) return;
    await axios.post(`/api/strategies/${name}/reset`, {}, { withCredentials: true });
    await load();
  };

  if (!detail) return null;

  const labels = PARAM_LABELS[name] || {};

  return (
    <div className="card space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold capitalize text-slate-200">{name}</h3>
          <div className="flex gap-3 text-[10px] text-muted mt-0.5">
            <span>Daily: <span className={detail.pnl.daily >= 0 ? "text-success" : "text-danger"}>
              {detail.pnl.daily >= 0 ? "+" : ""}{detail.pnl.daily.toFixed(4)}
            </span></span>
            <span>Total: <span className={detail.pnl.total >= 0 ? "text-success" : "text-danger"}>
              {detail.pnl.total >= 0 ? "+" : ""}{detail.pnl.total.toFixed(4)}
            </span></span>
            <span>Orders: {detail.open_orders.length}</span>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-muted hover:text-slate-300 px-2 py-1 border border-border rounded"
        >
          {expanded ? "ย่อ" : "แก้ไข"}
        </button>
      </div>

      {expanded && (
        <>
          {/* Params */}
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(detail.params).map(([key, val]) => {
              const editVal = editing[key] !== undefined ? editing[key] : String(val);
              const isChanged = editing[key] !== undefined;
              return (
                <div key={key}>
                  <label className="block text-[10px] text-muted mb-1">
                    {labels[key] || key}
                    {isChanged && <span className="ml-1 text-warning">●</span>}
                  </label>
                  <input
                    className="input text-xs py-1.5"
                    value={editVal}
                    onChange={(e) => {
                      setEditing((prev) => ({ ...prev, [key]: e.target.value }));
                      setMsg(null);
                    }}
                  />
                </div>
              );
            })}
          </div>

          {/* Actions */}
          {msg && (
            <p className={`text-[11px] ${msg.ok ? "text-success" : "text-danger"}`}>{msg.text}</p>
          )}
          <div className="flex gap-2">
            <button
              className="btn-primary text-xs flex-1"
              onClick={handleSave}
              disabled={saving || !dirty.length}
            >
              {saving ? "กำลังบันทึก…" : `บันทึก${dirty.length ? ` (${dirty.length})` : ""}`}
            </button>
            <button
              className="btn-secondary text-xs"
              onClick={handleReset}
            >
              Reset State
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function StrategyConfigPanel() {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-300 px-1">Strategy Config</h2>
      {["smc", "martingale", "grid", "momentum"].map((name) => (
        <StrategyCard key={name} name={name} />
      ))}
    </div>
  );
}
