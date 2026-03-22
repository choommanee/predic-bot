import { useEffect, useState } from "react";
import axios from "axios";

interface Trade {
  id: string;
  strategy: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  level: number;
  reason: string;
  status: string;
  exit_price: number | null;
  pnl: number | null;
  opened_at: string;
  closed_at: string | null;
}

function sideColor(side: string) {
  return side === "BUY" ? "text-success" : "text-danger";
}

function pnlColor(pnl: number | null) {
  if (pnl === null) return "text-muted";
  return pnl >= 0 ? "text-success" : "text-danger";
}

function fmtTime(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString();
}

export default function OpenPositions({
  refreshTrigger,
}: {
  refreshTrigger?: number;
}) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tab, setTab] = useState<"open" | "recent">("open");
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const endpoint = tab === "open" ? "/api/trades/open" : "/api/trades?limit=20";
      const r = await axios.get(endpoint, { withCredentials: true });
      setTrades(r.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [tab, refreshTrigger]);

  return (
    <div className="card space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">Positions</h2>
        <div className="flex gap-1">
          {(["open", "recent"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-xs px-3 py-1 rounded border transition-colors ${
                tab === t
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-border text-muted hover:border-slate-500"
              }`}
            >
              {t === "open" ? "Open" : "History"}
            </button>
          ))}
          <button
            onClick={load}
            className="text-xs px-2 py-1 rounded border border-border text-muted hover:border-slate-500 ml-1"
          >
            ↻
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-xs text-muted animate-pulse py-4 text-center">Loading…</div>
      ) : trades.length === 0 ? (
        <div className="text-xs text-muted py-4 text-center">
          {tab === "open" ? "ไม่มี open positions" : "ยังไม่มีประวัติ"}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted border-b border-border">
                <th className="text-left py-1 pr-2">Strategy</th>
                <th className="text-left py-1 pr-2">Side</th>
                <th className="text-right py-1 pr-2">Qty</th>
                <th className="text-right py-1 pr-2">Entry</th>
                <th className="text-right py-1 pr-2">SL</th>
                <th className="text-right py-1 pr-2">TP</th>
                {tab === "recent" && <th className="text-right py-1">PnL</th>}
                <th className="text-right py-1">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {trades.map((t) => (
                <tr key={t.id} className="hover:bg-card/80">
                  <td className="py-1.5 pr-2 capitalize">{t.strategy}</td>
                  <td className={`py-1.5 pr-2 font-medium ${sideColor(t.side)}`}>{t.side}</td>
                  <td className="py-1.5 pr-2 text-right">{t.quantity}</td>
                  <td className="py-1.5 pr-2 text-right">{t.entry_price.toFixed(2)}</td>
                  <td className="py-1.5 pr-2 text-right text-danger/80">
                    {t.stop_loss ? t.stop_loss.toFixed(2) : "—"}
                  </td>
                  <td className="py-1.5 pr-2 text-right text-success/80">
                    {t.take_profit ? t.take_profit.toFixed(2) : "—"}
                  </td>
                  {tab === "recent" && (
                    <td className={`py-1.5 text-right font-medium ${pnlColor(t.pnl)}`}>
                      {t.pnl !== null
                        ? `${t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(4)}`
                        : "—"}
                    </td>
                  )}
                  <td className="py-1.5 text-right text-muted">
                    {fmtTime(t.opened_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
