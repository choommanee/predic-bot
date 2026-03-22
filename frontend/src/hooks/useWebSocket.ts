import { useEffect, useRef, useState } from "react";

export interface MarketEvent {
  type: string;
  ts?: string;
  symbol?: string;
  price?: number;
  balance?: { total: number; free: number };
  indicators?: Record<string, number>;
  smc?: {
    bias: string;
    bullish_bos: number;
    bearish_bos: number;
    bullish_obs: number;
    bearish_obs: number;
  };
  signals?: Array<{
    strategy: string;
    side: string;
    quantity: number;
    price: number;
    reason: string;
  }>;
  ai?: {
    direction: string;
    confidence: number;
    market_condition: string;
    analysis: string;
  };
  regime?: {
    type: string;
    active_strategies: string[];
    description: string;
  };
  mtf?: {
    bias_4h: string;
    structure_15m: string;
    aligned: boolean;
  };
  agg_signal?: {
    direction: string;
    score: number;
    confidence: number;
    reasons: string[];
  };
  message?: string;
}

export function useWebSocket() {
  const [lastEvent, setLastEvent] = useState<MarketEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.host}/ws`;

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 3s
        setTimeout(connect, 3000);
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as MarketEvent;
          setLastEvent(data);
        } catch (_) {}
      };
    }

    connect();
    return () => wsRef.current?.close();
  }, []);

  return { lastEvent, connected };
}
