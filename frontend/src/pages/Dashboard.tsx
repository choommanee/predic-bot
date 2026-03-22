import { useState, useEffect } from "react";
import Navbar from "../components/Navbar";
import EquityCard from "../components/EquityCard";
import TradingChart from "../components/TradingChart";
import BotControl from "../components/BotControl";
import SMCPanel from "../components/SMCPanel";
import SignalLog from "../components/SignalLog";
import { useWebSocket, MarketEvent } from "../hooks/useWebSocket";

export default function Dashboard() {
  const { lastEvent, connected } = useWebSocket();
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [latestMarket, setLatestMarket] = useState<MarketEvent | null>(null);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type === "market_update" || lastEvent.type === "status") {
      setLatestMarket(lastEvent);
      if (lastEvent.signals && lastEvent.signals.length > 0) {
        setEvents((prev) => [...prev.slice(-200), lastEvent]);
      }
    } else if (lastEvent.type === "price_update") {
      // Fast price-only update — keep other market data intact
      setLatestMarket((prev) =>
        prev ? { ...prev, price: lastEvent.price } : lastEvent
      );
    }
  }, [lastEvent]);

  const symbol = latestMarket?.symbol ?? "BTCUSDT";

  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <Navbar connected={connected} />

      <main className="flex-1 p-4 md:p-6 space-y-4">
        {/* Top row: equity metrics */}
        <EquityCard
          price={latestMarket?.price ?? 0}
          symbol={symbol}
          balance={latestMarket?.balance}
          indicators={latestMarket?.indicators}
          smcBias={latestMarket?.smc?.bias ?? "NEUTRAL"}
        />

        {/* Chart + SMC + BotControl */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <TradingChart symbol={symbol} />
          </div>
          <div className="space-y-4">
            <SMCPanel smc={latestMarket?.smc} ai={latestMarket?.ai} />
            <BotControl />
          </div>
        </div>

        {/* Signal log */}
        <SignalLog events={events} />
      </main>
    </div>
  );
}
