interface Props {
  price: number;
  symbol: string;
  balance: { total: number; free: number } | undefined;
  indicators: Record<string, number> | undefined;
  smcBias: string;
}

export default function EquityCard({ price, symbol, balance, indicators, smcBias }: Props) {
  const rsi = indicators?.rsi ?? 0;
  const adx = indicators?.adx ?? 0;

  const biasColor =
    smcBias === "BULLISH" ? "text-success" : smcBias === "BEARISH" ? "text-danger" : "text-muted";

  return (
    <div className="card grid grid-cols-2 md:grid-cols-4 gap-4">
      <Metric label="Price" value={`$${price.toLocaleString("en", { minimumFractionDigits: 2 })}`} />
      <Metric label="Balance" value={`$${balance?.total.toFixed(2) ?? "—"}`} sub={`Free: $${balance?.free.toFixed(2) ?? "—"}`} />
      <Metric label="SMC Bias" value={smcBias} valueClass={biasColor} />
      <Metric label="RSI / ADX" value={`${rsi.toFixed(1)} / ${adx.toFixed(1)}`} />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  valueClass = "text-slate-100",
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className={`text-lg font-semibold ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
    </div>
  );
}
