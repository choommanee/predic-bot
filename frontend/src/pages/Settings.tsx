import { useEffect, useState } from "react";
import axios from "axios";
import Navbar from "../components/Navbar";

interface SettingField {
  key: string;
  label: string;
  type: "text" | "password" | "select" | "number";
  options?: string[];
  placeholder?: string;
}

const FIELDS: SettingField[] = [
  { key: "trading_symbol", label: "Symbol", type: "text", placeholder: "BTCUSDT" },
  {
    key: "trading_mode",
    label: "Trading Mode",
    type: "select",
    options: ["paper", "signal", "auto", "both"],
  },
  { key: "max_daily_loss_usd", label: "Max Daily Loss (USD)", type: "number", placeholder: "100" },
  { key: "max_drawdown_pct", label: "Max Drawdown (%)", type: "number", placeholder: "15" },
  { key: "base_lot_size", label: "Base Lot Size (BTC)", type: "number", placeholder: "0.001" },
  { key: "binance_api_key", label: "Binance API Key", type: "password", placeholder: "Stored encrypted" },
  { key: "binance_secret_key", label: "Binance Secret Key", type: "password", placeholder: "Stored encrypted" },
  {
    key: "binance_testnet",
    label: "Binance Testnet",
    type: "select",
    options: ["true", "false"],
  },
  { key: "telegram_bot_token", label: "Telegram Bot Token", type: "password", placeholder: "Stored encrypted" },
  { key: "telegram_chat_id", label: "Telegram Chat ID", type: "text", placeholder: "Your chat ID" },
  { key: "anthropic_api_key", label: "Anthropic API Key", type: "password", placeholder: "Stored encrypted" },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    axios.get("/api/settings").then((r) => setValues(r.data.settings || {}));
  }, []);

  const handleChange = (key: string, val: string) => {
    setDirty((d) => ({ ...d, [key]: val }));
  };

  const handleSave = async () => {
    const items = Object.entries(dirty).map(([key, value]) => ({ key, value }));
    if (!items.length) return;
    setSaving(true);
    try {
      await axios.put("/api/settings", items);
      setValues((v) => ({ ...v, ...dirty }));
      setDirty({});
      setMsg({ text: "Saved. Click Reload Engine to apply.", ok: true });
    } catch {
      setMsg({ text: "Save failed.", ok: false });
    } finally {
      setSaving(false);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      await axios.post("/api/settings/reload");
      setMsg({ text: "Engine reloaded with new settings.", ok: true });
    } catch (e: any) {
      setMsg({ text: e?.response?.data?.detail || "Reload failed.", ok: false });
    } finally {
      setReloading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      <Navbar connected={false} />
      <main className="flex-1 max-w-2xl mx-auto w-full px-4 py-8">
        <h1 className="text-xl font-bold text-slate-100 mb-6">Bot Settings</h1>

        <div className="card space-y-4">
          {FIELDS.map((f) => {
            const current = dirty[f.key] ?? (values[f.key] != null ? String(values[f.key]) : "");
            return (
              <div key={f.key}>
                <label className="block text-xs text-muted mb-1">{f.label}</label>
                {f.type === "select" ? (
                  <select
                    className="input w-full"
                    value={current}
                    onChange={(e) => handleChange(f.key, e.target.value)}
                  >
                    {(f.options ?? []).map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input w-full"
                    type={f.type === "password" ? "password" : "text"}
                    placeholder={f.placeholder}
                    value={current}
                    onChange={(e) => handleChange(f.key, e.target.value)}
                  />
                )}
              </div>
            );
          })}
        </div>

        {msg && (
          <p className={`mt-3 text-sm ${msg.ok ? "text-green-400" : "text-red-400"}`}>
            {msg.text}
          </p>
        )}

        <div className="flex gap-3 mt-6">
          <button
            className="btn-primary flex-1"
            onClick={handleSave}
            disabled={saving || !Object.keys(dirty).length}
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
          <button
            className="btn-secondary flex-1"
            onClick={handleReload}
            disabled={reloading}
          >
            {reloading ? "Reloading…" : "Reload Engine"}
          </button>
        </div>

        <p className="mt-4 text-xs text-muted">
          Sensitive values (API keys, tokens) are encrypted in the database.
          Only the first 4 characters are shown after saving.
        </p>
      </main>
    </div>
  );
}
