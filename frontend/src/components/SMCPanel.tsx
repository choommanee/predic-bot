interface SMCData {
  bias: string;
  bullish_bos: number;
  bearish_bos: number;
  bullish_obs: number;
  bearish_obs: number;
}

interface Props {
  smc: SMCData | undefined;
  ai?: {
    direction: string;
    confidence: number;
    market_condition: string;
    analysis: string;
  } | null;
}

export default function SMCPanel({ smc, ai }: Props) {
  const biasColor =
    smc?.bias === "BULLISH"
      ? "badge-success"
      : smc?.bias === "BEARISH"
      ? "badge-danger"
      : "badge-neutral";

  return (
    <div className="card space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">SMC Analysis</h2>

      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <p className="text-muted mb-1">Bias</p>
          <span className={`badge ${biasColor}`}>{smc?.bias ?? "—"}</span>
        </div>
        <div>
          <p className="text-muted mb-1">Bullish BOS</p>
          <p className="text-success font-semibold">{smc?.bullish_bos ?? 0}</p>
        </div>
        <div>
          <p className="text-muted mb-1">Bearish BOS</p>
          <p className="text-danger font-semibold">{smc?.bearish_bos ?? 0}</p>
        </div>
        <div>
          <p className="text-muted mb-1">Order Blocks</p>
          <p className="text-slate-300">
            <span className="text-success">{smc?.bullish_obs ?? 0}↑</span>{" "}
            <span className="text-danger">{smc?.bearish_obs ?? 0}↓</span>
          </p>
        </div>
      </div>

      {ai && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-300">🧠 Claude AI</p>
          <div className="flex gap-2">
            <span
              className={`badge ${
                ai.direction === "BUY"
                  ? "badge-success"
                  : ai.direction === "SELL"
                  ? "badge-danger"
                  : "badge-neutral"
              }`}
            >
              {ai.direction}
            </span>
            <span className="badge badge-neutral">{ai.confidence}%</span>
            <span className="badge badge-neutral">{ai.market_condition}</span>
          </div>
          {ai.analysis && (
            <p className="text-xs text-muted leading-relaxed line-clamp-3">{ai.analysis}</p>
          )}
        </div>
      )}
    </div>
  );
}
