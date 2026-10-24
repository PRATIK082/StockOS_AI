"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  fetchAnalytics,
  fetchPositions,
  fetchOrders,
  fetchTradebot,
  type TerminalAnalytics,
  type PositionState,
  type OrderRecord,
  type TradebotState,
} from "@/lib/trading";

export interface TerminalSnapshot {
  symbol: string;
  setSymbol: (s: string) => void;
  analytics: TerminalAnalytics | null;
  positions: PositionState["positions"];
  positionsSummary: PositionState["summary"] | null;
  orders: OrderRecord[];
  tradebot: TradebotState | null;
  loading: boolean;
  error: string;
  refresh: () => void;
}

const TerminalContext = createContext<TerminalSnapshot | null>(null);

export function TerminalProvider({ children }: { children: React.ReactNode }) {
  const [symbol, setSymbol] = useState("NSE:NIFTY");
  const [analytics, setAnalytics] = useState<TerminalAnalytics | null>(null);
  const [positions, setPositions] = useState<PositionState["positions"]>([]);
  const [positionsSummary, setPositionsSummary] = useState<PositionState["summary"] | null>(null);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [tradebot, setTradebot] = useState<TradebotState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [a, p, o] = await Promise.all([
        fetchAnalytics(),
        fetchPositions(),
        fetchOrders(),
      ]);
      setAnalytics(a);
      setPositions(p.positions);
      setPositionsSummary(p.summary);
      setOrders(o);
      setSymbol((prev) => prev || p.positions[0]?.symbol || "NSE:NIFTY");
      // Tradebot signals are best-effort and must never block the terminal.
      void (async () => {
        try {
          const t = await Promise.race([
            fetchTradebot(),
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error("tradebot timeout")), 20000),
            ),
          ]);
          setTradebot(t);
        } catch {
          // keep whatever signals we already have
        }
      })();
    } catch (err) {
      setError((err as Error).message || "Failed to load terminal");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  // Single shared poller for the whole command center (replaces per-tab polling).
  useEffect(() => {
    const id = window.setInterval(() => setRefreshKey((k) => k + 1), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const value = useMemo<TerminalSnapshot>(
    () => ({
      symbol,
      setSymbol,
      analytics,
      positions,
      positionsSummary,
      orders,
      tradebot,
      loading,
      error,
      refresh: () => setRefreshKey((k) => k + 1),
    }),
    [symbol, analytics, positions, positionsSummary, orders, tradebot, loading, error],
  );

  return <TerminalContext.Provider value={value}>{children}</TerminalContext.Provider>;
}

export function useTerminal(): TerminalSnapshot {
  const ctx = useContext(TerminalContext);
  if (!ctx) throw new Error("useTerminal must be used inside TerminalProvider");
  return ctx;
}