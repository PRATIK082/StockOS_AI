"use client";

import { useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  ColorType,
  type AreaData,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type IPriceFormatter,
  type ISeriesApi,
  type LineData,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";
import { BarChart3, CandlestickChart, LineChart as LineIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { api, type History } from "@/lib/api";

export type ChartKind = "candlestick" | "line" | "area";
const INTERVALS = ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"] as const;
const PERIODS = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"] as const;

// yfinance caps how far back an intraday interval can go (1m = 7d max).
const INTERVAL_PERIOD_LIMIT: Partial<Record<(typeof INTERVALS)[number], (typeof PERIODS)[number]>> = {
  "1m": "5d",
  "5m": "1mo",
  "15m": "1mo",
  "1h": "1y",
};

function defaultPeriodFor(interval: (typeof INTERVALS)[number]): (typeof PERIODS)[number] {
  return INTERVAL_PERIOD_LIMIT[interval] ?? "6mo";
}

const CHART_ICON: Record<ChartKind, typeof CandlestickChart> = {
  candlestick: CandlestickChart,
  line: LineIcon,
  area: BarChart3,
};

const timeOf = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) as Time;

// lightweight-charts renders colors on a <canvas>, which cannot resolve CSS
// `var(...)` values — those silently no-op (or throw for gradient stops). Resolve
// the theme's HSL triple to an explicit rgba() string instead.
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

export default function MarketChart({
  symbol,
  priceLine,
  priceLineLabel,
}: {
  symbol: string;
  /** Optional horizontal reference line (e.g. a selected option strike). */
  priceLine?: number | null;
  priceLineLabel?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainRef = useRef<ISeriesApi<keyof import("lightweight-charts").SeriesOptionsMap> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const [kind, setKind] = useState<ChartKind>("candlestick");
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>("1d");
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("6mo");
  // When the interval changes, clamp the period to the intraday limit for 1m/5m/15m.
  useEffect(() => {
    setPeriod((prev) => {
      const cap = defaultPeriodFor(interval);
      return PERIODS.indexOf(prev) > PERIODS.indexOf(cap) ? cap : prev;
    });
  }, [interval]);
  const [candles, setCandles] = useState<History["candles"]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get<History>(`/market/history/${encodeURIComponent(symbol)}?interval=${interval}&period=${period}`)
      .then((h) => setCandles(h.candles ?? []))
      .catch(() => setCandles([]))
      .finally(() => setLoading(false));
  }, [symbol, interval, period]);

  // Create/recreate chart on mount and when the chart kind changes.
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
      timeScale: {
        borderColor: themeColor("--border"),
        timeVisible: interval === "1d" || interval === "1m" || interval === "5m" || interval === "15m" || interval === "1h",
        secondsVisible: false,
      },
      autoSize: true,
    });

    let main: ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | ISeriesApi<"Area">;
    if (kind === "candlestick") {
      main = chart.addSeries(CandlestickSeries, {
        upColor: themeColor("--positive"),
        downColor: themeColor("--negative"),
        wickUpColor: themeColor("--positive"),
        wickDownColor: themeColor("--negative"),
        borderVisible: false,
      });
    } else if (kind === "area") {
      main = chart.addSeries(AreaSeries, {
        lineColor: themeColor("--primary"),
        topColor: themeColor("--primary", 0.35),
        bottomColor: "transparent",
        lineWidth: 2,
      });
    } else {
      main = chart.addSeries(LineSeries, { color: themeColor("--primary"), lineWidth: 2 });
    }

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", priceLineVisible: false });
    volume.applyOptions({ color: themeColor("--muted-foreground", 0.4) });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    if (typeof priceLine === "number" && Number.isFinite(priceLine)) {
      main.createPriceLine({
        price: priceLine,
        color: themeColor("--primary"),
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: priceLineLabel || "Strike",
      });
    }

    chartRef.current = chart;
    mainRef.current = main as unknown as ISeriesApi<keyof import("lightweight-charts").SeriesOptionsMap>;
    volRef.current = volume;

    return () => {
      chart.remove();
      chartRef.current = null;
      mainRef.current = null;
      volRef.current = null;
    };
  }, [kind, interval, priceLine, priceLineLabel]);

  // Push data into the series.
  useEffect(() => {
    if (!mainRef.current || !volRef.current) return;

    const candlesData: (CandlestickData<Time> | WhitespaceData<Time>)[] = [];
    const lineData: (LineData<Time> | AreaData<Time> | WhitespaceData<Time>)[] = [];
    const volumeData: (HistogramData<Time> | WhitespaceData<Time>)[] = [];
    for (const c of candles) {
      const time = timeOf(c.ts);
      const o = c.open;
      const h = c.high;
      const l = c.low;
      const cl = c.close;
      const validPrice = (n: number | null | undefined) => typeof n === "number" && Number.isFinite(n);
      if (Number.isNaN(time as number) || !validPrice(o) || !validPrice(h) || !validPrice(l) || !validPrice(cl)) continue;
      const volume = validPrice(c.volume) ? c.volume : 0;
      candlesData.push({ time, open: o, high: h, low: l, close: cl });
      lineData.push({ time, value: cl });
      volumeData.push({
        time,
        value: volume,
        color: cl >= o ? themeColor("--positive", 0.4) : themeColor("--negative", 0.4),
      });
    }

    const main = mainRef.current;
    if (kind === "candlestick") (main as unknown as ISeriesApi<"Candlestick">).setData(candlesData);
    else if (kind === "area") (main as unknown as ISeriesApi<"Area">).setData(lineData as AreaData<Time>[]);
    else (main as unknown as ISeriesApi<"Line">).setData(lineData as LineData<Time>[]);
    volRef.current.setData(volumeData);
    chartRef.current?.timeScale().fitContent();
  }, [candles, kind]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          {(Object.keys(CHART_ICON) as ChartKind[]).map((k) => {
            const Icon = CHART_ICON[k];
            return (
              <Button key={k} variant="ghost" size="sm" className={cn("h-7 px-2", kind === k && "bg-accent")} onClick={() => setKind(k)} aria-label={`${k} chart`}>
                <Icon className="h-4 w-4" />
              </Button>
            );
          })}
        </div>
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          {INTERVALS.map((i) => (
            <Button key={i} variant="ghost" size="sm" className={cn("h-7 px-2 text-xs", interval === i && "bg-accent")} onClick={() => setInterval(i)}>
              {i}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          {PERIODS.map((p) => (
            <Button key={p} variant="ghost" size="sm" className={cn("h-7 px-2 text-xs", period === p && "bg-accent")} onClick={() => setPeriod(p)}>
              {p}
            </Button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">last {candles.length} bars</span>
      </div>

      <div ref={containerRef} className="h-80 w-full" />
      {loading && <p className="py-4 text-center text-xs text-muted-foreground">Loading…</p>}
      {!loading && candles.length === 0 && (
        <p className="flex h-80 items-center justify-center text-sm text-muted-foreground">No data for {symbol}</p>
      )}
    </div>
  );
}