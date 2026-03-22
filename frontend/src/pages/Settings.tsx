import { useEffect, useState } from "react";
import axios from "axios";
import Navbar from "../components/Navbar";

interface SettingField {
  key: string;
  label: string;
  type: "text" | "password" | "select" | "number";
  options?: string[];
  placeholder?: string;
  hint?: string;
}

const SECTIONS: Array<{ title: string; icon: string; fields: SettingField[] }> = [
  {
    title: "Trading",
    icon: "📊",
    fields: [
      { key: "trading_symbol", label: "Symbol", type: "text" as const, placeholder: "BTCUSDT", hint: "Binance Futures pair" },
      {
        key: "trading_mode", label: "Mode", type: "select" as const,
        options: ["paper", "signal", "auto", "both"],
        hint: "paper = simulate | signal = notify only | auto = real orders",
      },
      { key: "max_daily_loss_usd", label: "Max Daily Loss (USD)", type: "number" as const, placeholder: "100" },
      { key: "max_drawdown_pct", label: "Max Drawdown (%)", type: "number" as const, placeholder: "15" },
      { key: "base_lot_size", label: "Base Lot Size (BTC)", type: "number" as const, placeholder: "0.001" },
    ],
  },
  {
    title: "Binance API",
    icon: "🔑",
    fields: [
      { key: "binance_api_key", label: "API Key", type: "password" as const, placeholder: "เก็บ encrypted ใน DB" },
      { key: "binance_secret_key", label: "Secret Key", type: "password" as const, placeholder: "เก็บ encrypted ใน DB" },
      {
        key: "binance_testnet", label: "Testnet", type: "select" as const,
        options: ["true", "false"],
        hint: "true = testnet.binancefuture.com | false = production",
      },
    ],
  },
  {
    title: "Telegram",
    icon: "📣",
    fields: [
      { key: "telegram_bot_token", label: "Bot Token", type: "password" as const, placeholder: "เก็บ encrypted ใน DB" },
      { key: "telegram_chat_id", label: "Chat ID", type: "text" as const, placeholder: "เช่น -100123456789" },
    ],
  },
  {
    title: "Claude AI",
    icon: "🧠",
    fields: [
      { key: "anthropic_api_key", label: "Anthropic API Key", type: "password" as const, placeholder: "เก็บ encrypted ใน DB", hint: "ใช้ claude-sonnet-4-6 วิเคราะห์ตลาด" },
    ],
  },
];

export default function Settings() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});

  useEffect(() => {
    axios.get("/api/settings").then((r) => setValues(r.data.settings || {}));
  }, []);

  const handleChange = (key: string, val: string) => {
    setDirty((d) => ({ ...d, [key]: val }));
    setMsg(null);
  };

  const getValue = (key: string) =>
    dirty[key] !== undefined ? dirty[key] : (values[key] != null ? String(values[key]) : "");

  const handleSave = async () => {
    const items = Object.entries(dirty).map(([key, value]) => ({ key, value }));
    if (!items.length) return;
    setSaving(true);
    try {
      await axios.put("/api/settings", items);
      setValues((v) => ({ ...v, ...dirty }));
      setDirty({});
      setMsg({ text: "บันทึกแล้ว กด Reload Engine เพื่อใช้ค่าใหม่", ok: true });
    } catch {
      setMsg({ text: "บันทึกไม่สำเร็จ", ok: false });
    } finally {
      setSaving(false);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      await axios.post("/api/settings/reload");
      setMsg({ text: "Engine โหลดค่าใหม่แล้ว", ok: true });
    } catch (e: any) {
      setMsg({ text: e?.response?.data?.detail || "Reload ไม่สำเร็จ", ok: false });
    } finally {
      setReloading(false);
    }
  };

  const hasDirty = Object.keys(dirty).length > 0;

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      <Navbar connected={false} />
      <main className="flex-1 max-w-2xl mx-auto w-full px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-bold text-slate-100">Bot Settings</h1>
          {hasDirty && (
            <span className="text-xs text-warning px-2 py-1 bg-warning/10 rounded border border-warning/30">
              มีการเปลี่ยนแปลงที่ยังไม่บันทึก
            </span>
          )}
        </div>

        <div className="space-y-6">
          {SECTIONS.map((section) => (
            <div key={section.title} className="card space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2 pb-2 border-b border-border">
                <span>{section.icon}</span>
                {section.title}
              </h2>
              {section.fields.map((f) => {
                const current = getValue(f.key);
                const isSecret = f.type === "password";
                const revealed = showSecrets[f.key];
                return (
                  <div key={f.key}>
                    <label className="block text-xs font-medium text-slate-400 mb-1.5">
                      {f.label}
                      {isSecret && (
                        <span className="ml-2 text-success/70 text-[10px]">🔒 encrypted</span>
                      )}
                    </label>
                    <div className="relative">
                      {f.type === "select" ? (
                        <select
                          className="input"
                          value={current}
                          onChange={(e) => handleChange(f.key, e.target.value)}
                        >
                          {(f.options ?? []).map((o) => (
                            <option key={o} value={o} className="bg-slate-800">
                              {o}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          className="input pr-16"
                          type={isSecret && !revealed ? "password" : "text"}
                          placeholder={f.placeholder}
                          value={current}
                          onChange={(e) => handleChange(f.key, e.target.value)}
                          autoComplete="off"
                        />
                      )}
                      {isSecret && (
                        <button
                          type="button"
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted hover:text-slate-300 transition-colors px-1"
                          onClick={() => setShowSecrets((s) => ({ ...s, [f.key]: !s[f.key] }))}
                        >
                          {revealed ? "ซ่อน" : "แสดง"}
                        </button>
                      )}
                    </div>
                    {f.hint && (
                      <p className="text-[11px] text-muted mt-1">{f.hint}</p>
                    )}
                    {dirty[f.key] !== undefined && (
                      <p className="text-[11px] text-warning mt-0.5">● แก้ไขแล้ว</p>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {msg && (
          <div className={`mt-4 px-4 py-3 rounded-lg text-sm border ${
            msg.ok
              ? "bg-success/10 border-success/30 text-success"
              : "bg-danger/10 border-danger/30 text-danger"
          }`}>
            {msg.text}
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            className="btn-primary flex-1"
            onClick={handleSave}
            disabled={saving || !hasDirty}
          >
            {saving ? "กำลังบันทึก…" : `บันทึก${hasDirty ? ` (${Object.keys(dirty).length} รายการ)` : ""}`}
          </button>
          <button
            className="btn-secondary flex-1"
            onClick={handleReload}
            disabled={reloading}
          >
            {reloading ? "กำลัง Reload…" : "Reload Engine"}
          </button>
        </div>

        <p className="mt-4 text-xs text-muted text-center">
          API keys เข้ารหัสด้วย AES-256 (Fernet) ก่อนเก็บใน DB · แสดงเฉพาะ 4 ตัวแรก
        </p>
      </main>
    </div>
  );
}
