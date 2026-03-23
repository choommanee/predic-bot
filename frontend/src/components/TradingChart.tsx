import { useEffect, useRef } from "react";
import { createChart, IChartApi, CandlestickData, Time } from "lightweight-charts";
import axios from "axios";

interface Props {
  symbol: string;
}

export default function TradingChart({ symbol }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let isMounted = true;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#1e293b" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#334155" },
        horzLines: { color: "#334155" },
      },
      crosshair: { mode: 1 },
      timeScale: { timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: 320,
    });

    chartRef.current = chart;
    const series = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    // Fetch initial OHLCV
    axios
      .get("/api/trading/ohlcv?timeframe=5m&limit=150", { withCredentials: true })
      .then((r) => {
        if (!isMounted) return;
        const candles: CandlestickData[] = r.data.map((c: any) => ({
          time: (new Date(c.timestamp).getTime() / 1000) as Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }));
        series.setData(candles);
        chart.timeScale().fitContent();
      })
      .catch(console.error);

    const handleResize = () => {
      if (containerRef.current) {
        chart.resize(containerRef.current.clientWidth, 320);
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      isMounted = false;
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [symbol]);

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">{symbol} Chart (5m)</h2>
      <div ref={containerRef} />
    </div>
  );
}
