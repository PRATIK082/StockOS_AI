"use client";

import { useEffect, useRef, useState } from "react";
import { AreaSeries, createChart, CrosshairMode, LineSeries, ColorType, type LineData, type AreaData, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { api } from "@/lib/api";

export interface PremiumPoint {
  time: string;
  spot: number;
  premium: number;
}

export interface OptionPremiumHistory {
  symbol: string;
  option_type: string;
  strike: number;
  expiry: string;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  spot_price: number;
  series: OptionPoint[];
  available_strikes?: number[];
  available_expiries?: string[];
}

interface OptionPoint {
  time: string;
  spot: number;
  premium: number;
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const sn = s / 100;
  const ln = l / 100;
  const c = (1 - Math.abs(2 * ln - 1)) * sn;
  const hp = ((((h % 360) + 360) % 360) / 60) % 6;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  const [r1, g1, b1] =
    hp < 1 ? [c, x, 0] : hp < 2 ? [x, c, 0] : hp < 3 ? [0, c, x] : hp < 4 ? [0, x, c] : hp < 5 ? [x, 0, c] : [c, 0, x];
  const m = ln - c / 2;
  return [Math.round((r1 + m) * 255), Math.round((g1 + m) * 255), Math.round((b1 + m) * 255)];
}

function themeColor(variable: string, alpha = 1): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  const parts = raw.split(/\s+/).map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return `rgba(128, 128, 128, ${alpha})`;
  const [h, s, l] = parts;
  const [r, g, b] = hslToRgb(h, s, l);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const timeOf = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) as Time;

export default function OptionPremiumChart({
  symbol,
  strike,
  expiry,
  optionType,
  variant = "area",
  onLoaded,
}: {
  symbol: string;
  strike: number | null;
  expiry?: string;
  optionType: "CE" | "PE";
  variant?: "area" | "line";
  onLoaded?: (data: OptionPremiumHistory) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<ISeriesApi<"Line"> | ISeriesApi<"Area"> | null>(null);
  const spotRef = useRef<ISeriesApi<"Line"> | null>(null);

  const [data, setData] = useState<OptionPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<OptionPremiumHistory | null>(null);

  useEffect(() => {
    if (strike == null || Number.isNaN(strike)) {
      setData([]);
      setMeta(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      strike: String(strike),
      option_type: optionType,
      interval: "1d",
      period: "1mo",
    });
    if (expiry) params.set("expiry", expiry.slice(0, 10));
    api
      .get<OptionPremiumHistory>(`/analysis/options/premium/${encodeURIComponent(symbol)}?${params}`)
      .then((res) => {
        setMeta(res);
        setData(res.series ?? []);
        onLoaded?.(res);
      })
      .catch((err: any) => {
        setError(err?.response?.data?.detail || String(err?.message || "Premium history unavailable."));
        setData([]);
      })
      .finally(() => setLoading(false));
  }, [symbol, strike, expiry, optionType]);

  // Create/recreate the premium chart on mount / meta change.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: themeColor("--muted-foreground"),
      },
      grid: { vertLines: { color: themeColor("--border", 0.5) }, horzLines: { color: themeColor("--border", 0.5) } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: themeColor("--border") },
      timeScale: { borderColor: themeColor("--border"), timeVisible: true },
      autoSize: true,
    });
    const main = variant === "line"
      ? chart.addSeries(LineSeries, {
          color: themeColor("--primary"),
          lineWidth: 2,
          lineStyle: 0,
        })
      : chart.addSeries(AreaSeries, {
          lineColor: themeColor("--primary"),
          topColor: themeColor("--primary", 0.35),
          bottomColor: "transparent",
          lineWidth: 2,
        });
    // Underlying spot overlaid in a muted color so the premium is clearly
    // distinct from (and aligned with) the underlying index/stock.
    const spot = chart.addSeries(LineSeries, {
      color: "rgba(148,163,184,0.75)",
      lineWidth: 1,
      lineStyle: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chartRef.current = chart;
    mainRef.current = main;
    spotRef.current = spot;
    return () => {
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
      spotRef.current = null;
    };
  }, [meta !== null, variant]);

  useEffect(() => {
    const main = mainRef.current;
    const spot = spotRef.current;
    if (!main || !spot) return;
    const line: (LineData<Time> | AreaData<Time>)[] = [];
    const spotLine: (LineData<Time> | AreaData<Time>)[] = [];
    for (const p of data) {
      const t = timeOf(p.time);
      if (Number.isNaN(t as number) || !Number.isFinite(p.premium)) continue;
      line.push({ time: t, value: p.premium });
      if (Number.isFinite(p.spot)) spotLine.push({ time: t, value: p.spot });
    }
    if (line.length) {
      main.setData(line as AreaData<Time>[]);
      spot.setData(spotLine as LineData<Time>[]);
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  if (strike == null && !loading) return null;

  return (
    <div className="w-full">
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="font-medium text-foreground">
          {optionType} {strike ?? ""}
          {expiry ? ` · ${expiry.slice(0, 10)}` : ""} — premium (₹)
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block h-0.5 w-4 bg-primary" /> premium
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block h-0 w-4 border-t border-dashed border-slate-400" /> underlying spot
        </span>
      </div>
      <div ref={containerRef} className="h-72 w-full" />
      {loading && <p className="py-3 text-center text-xs text-muted-foreground">Pricing {optionType} {strike}…</p>}
      {!loading && error && <p className="py-3 text-center text-xs text-destructive">{error}</p>}
      {!loading && meta && data.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            {meta.option_type} {meta.strike} @ {meta.expiry}
          </span>
          <span>IV {meta.iv.toFixed(1)}%</span>
          <span>Δ {meta.delta.toFixed(3)}</span>
          <span>Γ {meta.gamma.toFixed(4)}</span>
          <span>Θ {meta.theta.toFixed(4)}</span>
          <span>ν {meta.vega.toFixed(4)}</span>
          <span>Spot ₹{meta.spot_price.toFixed(2)}</span>
        </div>
      )}
      {meta && data.length > 0 && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">{meta.option_type} {meta.strike} @ {meta.expiry}</span> — theoretical
          premium estimated via Black-Scholes on real underlying history × live chain Greeks; the underlying spot is
          the dashed line. The free scanner publishes no historical option prices.
        </p>
      )}
    </div>
  );
}