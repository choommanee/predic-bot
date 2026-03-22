import { MarketEvent } from "../hooks/useWebSocket";

interface Props {
  events: MarketEvent[];
}

export default function SignalLog({ events }: Props) {
  const signals = events
    .flatMap((e) =>
      (e.signals ?? []).map((s) => ({
        ...s,
        ts: e.ts ?? new Date().toISOString(),
        ai: e.ai,
      }))
    )
    .slice(-50)
    .reverse();

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">Signal Log</h2>
      {signals.length === 0 ? (
        <p className="text-xs text-muted">No signals yet...</p>
      ) : (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {signals.map((s, i) => (
            <div key={i} className="flex items-start gap-3 text-xs border-b border-border pb-2">
              <span className={s.side === "BUY" ? "text-success font-bold" : "text-danger font-bold"}>
                {s.side}
              </span>
              <div className="flex-1">
                <span className="text-slate-300 font-medium capitalize">{s.strategy}</span>
                <span className="text-muted ml-2">@ ${s.price.toFixed(2)}</span>
                <span className="text-muted ml-2">{s.quantity}</span>
                <p className="text-muted mt-0.5">{s.reason}</p>
              </div>
              <span className="text-muted shrink-0">
                {new Date(s.ts).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
