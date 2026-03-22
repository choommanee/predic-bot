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
  mtf?: {
    bias_4h: string;
    structure_15m: string;
    aligned: boolean;
  } | null;
  regime?: {
    type: string;
    active_strategies: string[];
    description: string;
  } | null;
  aggSignal?: {
    direction: string;
    score: number;
    confidence: number;
    reasons: string[];
  } | null;
}

function biasBadge(bias: string) {
  if (bias === "BULLISH") return "badge-success";
  if (bias === "BEARISH") return "badge-danger";
  return "badge-neutral";
}

function regimeBadge(regime: string) {
  if (regime === "TRENDING_UP") return "badge-success";
  if (regime === "TRENDING_DOWN") return "badge-danger";
  if (regime === "RANGING") return "badge-neutral";
  return "badge-neutral";
}

function signalBadge(direction: string) {
  if (direction === "BUY") return "badge-success";
  if (direction === "SELL") return "badge-danger";
  return "badge-neutral";
}

export default function SMCPanel({ smc, ai, mtf, regime, aggSignal }: Props) {
  const biasColor = biasBadge(smc?.bias ?? "NEUTRAL");

  // Score bar width — score is -1 to +1, map to 0-100% centered
  const scoreAbs = Math.abs(aggSignal?.score ?? 0);
  const scoreBarWidth = Math.min(100, scoreAbs * 100);
  const scoreBarColor =
    (aggSignal?.direction === "BUY")
      ? "bg-success"
      : (aggSignal?.direction === "SELL")
      ? "bg-danger"
      : "bg-slate-500";

  return (
    <div className="card space-y-4">
      <h2 className="text-sm font-semibold text-slate-300">SMC Analysis</h2>

      {/* Existing SMC data */}
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

      {/* MTF Alignment */}
      {mtf && (
        <div className="border-t border-border pt-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-300">MTF Alignment</p>
            {mtf.aligned ? (
              <span className="badge badge-success text-xs">ALIGNED</span>
            ) : (
              <span className="badge badge-neutral text-xs">MIXED</span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <p className="text-muted mb-1">4H Bias</p>
              <span className={`badge ${biasBadge(mtf.bias_4h)}`}>{mtf.bias_4h}</span>
            </div>
            <div>
              <p className="text-muted mb-1">15m Structure</p>
              <span className={`badge ${biasBadge(mtf.structure_15m)}`}>{mtf.structure_15m}</span>
            </div>
          </div>
        </div>
      )}

      {/* Aggregated Signal */}
      {aggSignal && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-300">Aggregated Signal</p>
          <div className="flex items-center gap-2">
            <span className={`badge ${signalBadge(aggSignal.direction)}`}>
              {aggSignal.direction}
            </span>
            <span className="text-xs text-muted">{aggSignal.confidence.toFixed(1)}% conf</span>
          </div>
          {/* Score bar */}
          <div className="w-full bg-slate-700 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-1.5 rounded-full transition-all ${scoreBarColor}`}
              style={{ width: `${scoreBarWidth}%` }}
            />
          </div>
          <p className="text-xs text-muted">Score: {aggSignal.score.toFixed(3)}</p>
          {aggSignal.reasons.length > 0 && (
            <ul className="text-xs text-muted space-y-0.5">
              {aggSignal.reasons.slice(0, 4).map((r, i) => (
                <li key={i} className="flex items-center gap-1">
                  <span className="text-slate-500">•</span> {r}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Market Regime */}
      {regime && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-300">Market Regime</p>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`badge ${regimeBadge(regime.type)}`}>{regime.type}</span>
          </div>
          {regime.description && (
            <p className="text-xs text-muted">{regime.description}</p>
          )}
          {regime.active_strategies.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {regime.active_strategies.map((s) => (
                <span key={s} className="badge badge-neutral text-xs">{s}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Claude AI */}
      {ai && (
        <div className="border-t border-border pt-3 space-y-2">
          <p className="text-xs font-semibold text-slate-300">Claude AI</p>
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
