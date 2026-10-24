"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickData,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramData,
  HistogramSeries,
  LineData,
  LineSeries,
  Time,
  WhitespaceData,
  type ISeriesApi,
  type SeriesMarker,
} from "lightweight-charts";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface IndicatorSeries {
  symbol: string;
  interval: string;
  period: string;
  candles: { ts: string; open: number; high: number; low: number; close: number; volume: number }[];
  sma20: (number | null)[];
  sma50: (number | null)[];
  ema20: (number | null)[];
  rsi: (number | null)[];
  macd: (number | null)[];
  macd_signal: (number | null)[];
  macd_hist: (number | null)[];
  bb_upper: (number | null)[];
  bb_middle: (number | null)[];
  bb_lower: (number | null)[];
  stoch?: { "%K": (number | null)[]; "%D": (number | null)[] };
  supertrend?: { value: (number | null | string)[]; trend: (string | null)[] };
  adx?: (number | null)[];
  plus_di?: (number | null)[];
  minus_di?: (number | null)[];
  cci?: (number | null)[];
  mfi?: (number | null)[];
  williams_r?: (number | null)[];
  obv?: (number | null)[];
  sar?: (number | null)[];
  ichimoku?: { tenkan?: (number | null)[]; kijun?: (number | null)[]; senkou_a?: (number | null)[]; senkou_b?: (number | null)[] };
  atr: number;
  vwap: number;
  latest: Record<string, { name: string; value: unknown; signal: string; strength: number }>;
  signals?: Array<{ time: string; type: "buy" | "sell"; reason: string; price: number }>;
}

const timeOf = (iso: string): Time => {
  const t = Math.floor(new Date(iso).getTime() / 1000);
  return Number.isNaN(t) ? (0 as Time) : (t as Time);
};

const cssColor = (variable: string, alpha = 1): string => {
  if (typeof window === "undefined") return "rgba(128,128,128,1)";
  const raw = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  const m = raw.match(/^([\d.]+)(?:\s+([\d.]+))?(?:\s+([\d.]+))?(?:\s*\/\s*([\d.]+))?$/);
  if (!m) return `rgba(128,128,128,${alpha})`;
  const [r, g, b] = [m[1] ?? 128, m[2] ?? m[1] ?? 66, m[3] ?? m[1] ?? 66];
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const INTERVALS = ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"] as const;
const PERIODS = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"] as const;
type Interval = (typeof INTERVALS)[number];
type Period = (typeof PERIODS)[number];

const INTERVAL_PERIOD_LIMIT: Partial<Record<Interval, Period>> = {
  "1m": "5d",
  "5m": "1mo",
  "15m": "1mo",
  "1h": "1y",
};

function defaultPeriodFor(interval: Interval): Period {
  return INTERVAL_PERIOD_LIMIT[interval] ?? "3mo";
}

export default function TechnicalChart({ symbol, height = 620 }: { symbol: string; height?: number }) {
  const [data, setData] = useState<IndicatorSeries | null>(null);
  const [interval, setInterval] = useState<Interval>("1d");
  const [period, setPeriod] = useState<Period>("3mo");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);

  useEffect(() => {
    setPeriod((prev) => {
      const cap = defaultPeriodFor(interval);
      return PERIODS.indexOf(prev) > PERIODS.indexOf(cap) ? cap : prev;
    });
  }, [interval]);

  const fetchIndicators = useCallback(
    (opts?: { quiet?: boolean }) => {
      if (!symbol) return;
      let cancelled = false;
      if (!opts?.quiet) {
        setLoading(true);
        setError(null);
      }
      api
        .get<IndicatorSeries>(`/analysis/technical/${encodeURIComponent(symbol)}?interval=${interval}&period=${period}`)
        .then((res) => {
          if (cancelled) return;
          setData(res);
          setLastRefreshed(new Date().toLocaleTimeString());
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
              "Indicator data unavailable for this symbol.",
          );
          setData(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    },
    [symbol, interval, period],
  );

  useEffect(() => {
    const cancel = fetchIndicators();
    return cancel;
  }, [fetchIndicators, interval, period]);

  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => fetchIndicators({ quiet: true }), 30_000);
    fetchIndicators({ quiet: true });
    return () => window.clearInterval(t);
  }, [live, fetchIndicators]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {symbol} · Technical indicators
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-md border p-0.5">
            {INTERVALS.map((i) => (
              <Button
                key={i}
                variant="ghost"
                size="sm"
                className={cn("h-7 px-2 text-xs", interval === i && "bg-accent text-accent-foreground")}
                onClick={() => setInterval(i)}
              >
                {i}
              </Button>
            ))}
          </div>
          <div className="flex items-center gap-0.5 rounded-md border p-0.5">
            {PERIODS.map((p) => (
              <Button
                key={p}
                variant="ghost"
                size="sm"
                className={cn("h-7 px-2 text-xs", period === p && "bg-accent text-accent-foreground")}
                onClick={() => setPeriod(p)}
              >
                {p}
              </Button>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            className={cn("h-9 px-3 text-xs", live && "border-positive text-positive")}
            onClick={() => setLive((v) => !v)}
          >
            {live ? "Live · on" : "Live refresh"}
          </Button>
        </div>
      </div>
      {lastRefreshed && (
        <p className="text-right text-[11px] text-muted-foreground">updated {lastRefreshed}</p>
      )}

      {loading && <p className="py-6 text-center text-sm text-muted-foreground">Loading technical indicators…</p>}
      {!loading && error && <p className="py-6 text-center text-sm text-destructive">{error}</p>}
      {!loading && !error && data && (
        <>
          <PricePanel data={data} height={Math.max(height - 220, 300)} />
          <RsiPanel data={data} />
          <MacdPanel data={data} />
          <StochasticPanel data={data} />
          <div className="flex flex-wrap gap-2">
            <Chip label="RSI(14)" value={fmt(data.latest.RSI?.value)} tone={data.latest.RSI?.signal} />
            <Chip label="MACD hist" value={fmt(data.latest.MACD?.value, 3)} tone={data.latest.MACD?.signal} />
            <Chip label="Bollinger" value={bbRange(data.latest.BollingerBands?.value)} tone={data.latest.BollingerBands?.signal} />
            <Chip label="ATR(14)" value={fmt(data.atr)} />
            <Chip label="VWAP" value={fmt(data.vwap)} />
            <Chip label="Stoch %K" value={fmt(data.stoch?.["%K"]?.at(-1))} />
            <Chip label="ADX" value={fmt(data.adx?.at(-1))} />
            <Chip
              label="Supertrend"
              value={data.supertrend?.trend?.at(-1) ?? "—"}
              tone={data.supertrend?.trend?.at(-1) ?? undefined}
            />
            <Chip label="CCI" value={fmt(data.cci?.at(-1))} />
            <Chip label="MFI" value={fmt(data.mfi?.at(-1))} />
            <Chip label="W%R" value={fmt(data.williams_r?.at(-1))} />
            <Chip label="Last close" value={fmt(data.candles.at(-1)?.close ?? null)} />
          </div>
          {data.signals && data.signals.length > 0 && (
            <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
              <p className="text-xs font-medium text-muted-foreground mb-1">Recent signal markers ({data.signals.length})</p>
              <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                {data.signals.slice(-20).map((s, i) => (
                  <span
                    key={i}
                    className={cn(
                      "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono",
                      s.type === "buy"
                        ? "bg-positive/10 text-positive border border-positive/30"
                        : "bg-negative/10 text-negative border border-negative/30",
                    )}
                  >
                    {s.type === "buy" ? "▲" : "▼"} {s.reason}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

type OverlayKey = "candles" | "sma20" | "sma50" | "ema20" | "bollinger" | "supertrend";

const OVERLAYS: { key: OverlayKey; label: string; color: string }[] = [
  { key: "candles", label: "Candles", color: "#e2e8f0" },
  { key: "sma20", label: "SMA20", color: "#38bdf8" },
  { key: "sma50", label: "SMA50", color: "#f472b6" },
  { key: "ema20", label: "EMA20", color: "#a78bfa" },
  { key: "bollinger", label: "Bollinger", color: "#94a3b8" },
  { key: "supertrend", label: "Supertrend", color: "#facc15" },
];

function PricePanel({ data, height }: { data: IndicatorSeries; height: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState<Record<OverlayKey, boolean>>({
    candles: true,
    sma20: true,
    sma50: true,
    ema20: true,
    bollinger: true,
    supertrend: true,
  });
  const seriesRef = useRef<Record<string, ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>>({});

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssColor("--muted-foreground"),
      },
      grid: { vertLines: { color: cssColor("--border", 0.4) }, horzLines: { color: cssColor("--border", 0.4) } },
      rightPriceScale: { borderColor: cssColor("--border") },
      timeScale: { borderColor: cssColor("--border"), timeVisible: true },
      autoSize: true,
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "rgba(34,197,94,0.95)",
      downColor: "rgba(239,68,68,0.95)",
      wickUpColor: "rgba(34,197,94,0.95)",
      wickDownColor: "rgba(239,68,68,0.95)",
      borderVisible: false,
    });
    const cd: (CandlestickData<Time> | WhitespaceData<Time>)[] = [];
    for (let i = 0; i < data.candles.length; i++) {
      const c = data.candles[i];
      cd.push({ time: timeOf(c.ts), open: c.open, high: c.high, low: c.low, close: c.close });
    }
    candles.setData(cd as CandlestickData<Time>[]);
    seriesRef.current.candles = candles;

    // --- overlays -----------------------------------------------------------
    const overlay = (
      key: Exclude<OverlayKey, "candles">,
      arr: (number | null)[],
      color: string,
      width: 1 | 2 | 3 | 4 = 1,
    ) => {
      const line = chart.addSeries(LineSeries, { color, lineWidth: width, lastValueVisible: false, priceLineVisible: false });
      const pts: (LineData<Time> | WhitespaceData<Time>)[] = [];
      data.candles.forEach((c, i) => {
        if (arr[i] == null) return;
        pts.push({ time: timeOf(c.ts), value: arr[i] as number });
      });
      line.setData(pts as LineData<Time>[]);
      seriesRef.current[key] = line;
    };
    overlay("sma20", data.sma20, "#38bdf8", 2);
    overlay("sma50", data.sma50, "#f472b6", 2);
    overlay("ema20", data.ema20, "#a78bfa", 2);
    const bbLine = (key: "bb_upper" | "bb_lower", arr: (number | null)[], color: string) => {
      const line = chart.addSeries(LineSeries, { color, lineWidth: 1, lastValueVisible: false, priceLineVisible: false });
      const pts: (LineData<Time> | WhitespaceData<Time>)[] = [];
      data.candles.forEach((c, i) => {
        if (arr[i] == null) return;
        pts.push({ time: timeOf(c.ts), value: arr[i] as number });
      });
      line.setData(pts as LineData<Time>[]);
      seriesRef.current.bollinger = seriesRef.current.bollinger ?? (line as ISeriesApi<"Line">);
      void key;
    };
    bbLine("bb_upper", data.bb_upper, "rgba(148,163,184,0.7)");
    bbLine("bb_lower", data.bb_lower, "rgba(148,163,184,0.7)");

    // Supertrend
    if (data.supertrend) {
      const stLine = chart.addSeries(LineSeries, {
        color: "#facc15",
        lineWidth: 2,
        lastValueVisible: false,
        priceLineVisible: false,
      });
      const pts: (LineData<Time> | WhitespaceData<Time>)[] = [];
      data.candles.forEach((c, i) => {
        const v = data.supertrend?.value?.[i];
        if (typeof v === "number") {
          pts.push({ time: timeOf(c.ts), value: v });
        }
      });
      stLine.setData(pts as LineData<Time>[]);
      seriesRef.current.supertrend = stLine;
    }

    // --- signal markers (v5 createSeriesMarkers) ---------------------------
    if (data.signals && data.signals.length > 0) {
      const markers: SeriesMarker<Time>[] = data.signals.map((s) => ({
        time: timeOf(s.time),
        position: s.type === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
        color: s.type === "buy" ? "#22c55e" : "#ef4444",
        shape: s.type === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
        text: s.type === "buy" ? "B" : "S",
      }));
      createSeriesMarkers(candles, markers as SeriesMarker<Time>[]);
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  // Toggle overlays without rebuilding the chart (preserves zoom/scroll).
  useEffect(() => {
    for (const { key } of OVERLAYS) {
      const s = seriesRef.current[key];
      s?.applyOptions({ visible: visible[key] });
    }
  }, [visible]);

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2">
      <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
        {OVERLAYS.map((o) => (
          <label
            key={o.key}
            className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground select-none"
          >
            <input
              type="checkbox"
              checked={visible[o.key]}
              onChange={(e) => setVisible((v) => ({ ...v, [o.key]: e.target.checked }))}
              className="h-3.5 w-3.5 accent-primary"
            />
            <span className={cn(visible[o.key] && "text-foreground")}>
              <span
                className="mr-1 inline-block h-0 w-3 border-t-2"
                style={{ borderColor: o.color }}
              />
              {o.label}
            </span>
          </label>
        ))}
        <span className="ml-auto text-[11px] text-muted-foreground">▲ buy · ▼ sell markers · tick to show / hide</span>
      </div>
      <div ref={ref} style={{ height }} className="w-full" />
    </div>
  );
}

function RsiPanel({ data }: { data: IndicatorSeries }) {
  const ref = useRef<HTMLDivElement>(null);
  const hasData = (data.rsi ?? []).some((v) => v != null);
  useEffect(() => {
    if (!ref.current || !hasData) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("--muted-foreground") },
      grid: { vertLines: { color: cssColor("--border", 0.4) }, horzLines: { color: cssColor("--border", 0.4) } },
      rightPriceScale: { borderColor: cssColor("--border") },
      timeScale: { borderColor: cssColor("--border"), timeVisible: true },
      autoSize: true,
    });
    const area = chart.addSeries(AreaSeries, {
      lineColor: "#f59e0b",
      topColor: "rgba(245,158,11,0.22)",
      bottomColor: "transparent",
      lineWidth: 2,
    });
    const pts: (LineData<Time> | WhitespaceData<Time>)[] = [];
    data.candles.forEach((c, i) => {
      if (data.rsi?.[i] == null) return;
      pts.push({ time: timeOf(c.ts), value: data.rsi[i] as number });
    });
    area.setData(pts as LineData<Time>[]);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2">
      <p className="mb-1 px-1 text-xs text-muted-foreground">RSI(14) — overbought &gt;70 · oversold &lt;30</p>
      {hasData ? (
        <div ref={ref} className="h-32 w-full" />
      ) : (
        <p className="flex h-32 items-center justify-center text-xs text-muted-foreground">
          Not enough candles to compute RSI — pick a longer period.
        </p>
      )}
    </div>
  );
}

function MacdPanel({ data }: { data: IndicatorSeries }) {
  const ref = useRef<HTMLDivElement>(null);
  const hasData = (data.macd_hist ?? []).some((v) => v != null);
  useEffect(() => {
    if (!ref.current || !hasData) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("--muted-foreground") },
      grid: { vertLines: { color: cssColor("--border", 0.4) }, horzLines: { color: cssColor("--border", 0.4) } },
      rightPriceScale: { borderColor: cssColor("--border") },
      timeScale: { borderColor: cssColor("--border"), timeVisible: true },
      autoSize: true,
    });
    const hist = chart.addSeries(HistogramSeries, { priceFormat: { type: "price" } });
    const hd: (HistogramData<Time> | WhitespaceData<Time>)[] = [];
    data.candles.forEach((c, i) => {
      const v = data.macd_hist?.[i];
      if (v == null) return;
      hd.push({ time: timeOf(c.ts), value: v, color: v >= 0 ? "rgba(34,197,94,0.55)" : "rgba(239,68,68,0.55)" });
    });
    hist.setData(hd as HistogramData<Time>[]);

    const line = (arr: (number | null)[], color: string) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1 });
      const pts: (LineData<Time> | WhitespaceData<Time>)[] = [];
      data.candles.forEach((c, i) => {
        if (arr?.[i] == null) return;
        pts.push({ time: timeOf(c.ts), value: arr[i] as number });
      });
      s.setData(pts as LineData<Time>[]);
    };
    line(data.macd, cssColor("--primary"));
    line(data.macd_signal, "#f472b6");
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2">
      <p className="mb-1 px-1 text-xs text-muted-foreground">
        MACD(12,26,9) · line <span className="text-primary">—</span> · signal <span className="text-pink-400">—</span>{" "}
        · histogram <span className="text-positive">▮</span>
        <span className="text-negative">▮</span>
      </p>
      {hasData ? (
        <div ref={ref} className="h-32 w-full" />
      ) : (
        <p className="flex h-32 items-center justify-center text-xs text-muted-foreground">
          Not enough candles to compute MACD — pick a longer period (MACD needs 26+ bars).
        </p>
      )}
    </div>
  );
}

function StochasticPanel({ data }: { data: IndicatorSeries }) {
  const ref = useRef<HTMLDivElement>(null);
  const stoch = data.stoch;
  const hasData = stoch ? (stoch["%K"] ?? []).some((v) => v != null) : false;

  useEffect(() => {
    if (!ref.current || !hasData || !stoch) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssColor("--muted-foreground") },
      grid: { vertLines: { color: cssColor("--border", 0.4) }, horzLines: { color: cssColor("--border", 0.4) } },
      rightPriceScale: { borderColor: cssColor("--border") },
      timeScale: { borderColor: cssColor("--border"), timeVisible: true },
      autoSize: true,
    });

    // Overbought/oversold zones via histogram (subtle fills)
    const zone = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "price" },
      priceScaleId: "",
      color: "rgba(100,116,139,0.06)",
    });
    const zd: (HistogramData<Time> | WhitespaceData<Time>)[] = [];
    data.candles.forEach((c, i) => {
      if (stoch["%K"]?.[i] == null) return;
      zd.push({ time: timeOf(c.ts), value: 100, color: "rgba(100,116,139,0.04)" });
    });
    zone.setData(zd as HistogramData<Time>[]);

    const kLine = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2 });
    const dLine = chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 1 });
    const ptsK: (LineData<Time> | WhitespaceData<Time>)[] = [];
    const ptsD: (LineData<Time> | WhitespaceData<Time>)[] = [];
    data.candles.forEach((c, i) => {
      const kv = stoch["%K"]?.[i];
      const dv = stoch["%D"]?.[i];
      if (kv != null) ptsK.push({ time: timeOf(c.ts), value: kv });
      if (dv != null) ptsD.push({ time: timeOf(c.ts), value: dv });
    });
    kLine.setData(ptsK as LineData<Time>[]);
    dLine.setData(ptsD as LineData<Time>[]);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return (
    <div className="rounded-md border border-border bg-muted/20 p-2">
      <p className="mb-1 px-1 text-xs text-muted-foreground">
        Stochastic(14,3) · <span className="text-yellow-400">— %K</span> · <span className="text-sky-400">— %D</span> · overbought &gt;80 · oversold &lt;20
      </p>
      {hasData ? (
        <div ref={ref} className="h-32 w-full" />
      ) : (
        <p className="flex h-32 items-center justify-center text-xs text-muted-foreground">
          Not enough candles to compute Stochastic — pick a longer period.
        </p>
      )}
    </div>
  );
}

function Chip({ label, value, tone }: { label: string; value: string | null; tone?: string }) {
  const color = tone === "buy" ? "text-positive" : tone === "sell" ? "text-negative" : "text-muted-foreground";
  return (
    <span className="rounded-md border border-border bg-muted/30 px-2 py-1 text-xs">
      <span className="text-muted-foreground">{label}:</span>{" "}
      <span className={color}>{tone === "buy" ? "▲ " : tone === "sell" ? "▼ " : ""}{value ?? "—"}</span>
    </span>
  );
}

function fmt(v: unknown, digits = 2): string | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  if (Math.abs(v) >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toFixed(digits);
}

function bbRange(v: unknown): string | null {
  if (typeof v !== "object" || v == null) return null;
  const o = v as Record<string, unknown>;
  if (typeof o.lower === "number" && typeof o.upper === "number") {
    return `${o.lower.toFixed(0)}–${o.upper.toFixed(0)}`;
  }
  return null;
}