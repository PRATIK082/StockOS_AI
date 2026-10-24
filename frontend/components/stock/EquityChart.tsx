"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType, CrosshairMode, LineSeries, type IChartApi, type Time, type LineData } from "lightweight-charts";

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

export interface EquitySeries {
  label: string;
  color?: string;
  data: { time: string; value: number }[];
}

export default function EquityChart({ series, height = 320 }: { series: EquitySeries[]; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<(import("lightweight-charts").ISeriesApi<"Line"> | null)[]>([]);

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
    chartRef.current = chart;
    seriesRef.current = [];
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    seriesRef.current.forEach((s) => s && chart.removeSeries(s));
    seriesRef.current = series.map((ser, i) => {
      const colors = [themeColor("--primary"), themeColor("--positive"), themeColor("--negative"), themeColor("--warning", 0.9)];
      const color = ser.color ?? colors[i % colors.length];
      const line = chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: i === 0,
        lastValueVisible: true,
      });
      const pts: LineData<Time>[] = [];
      for (const p of ser.data) {
        const t = timeOf(p.time);
        if (Number.isNaN(t as number) || !Number.isFinite(p.value)) continue;
        pts.push({ time: t, value: p.value });
      }
      if (pts.length) line.setData(pts);
      return line;
    });
    if (series.length && series[0].data.length) chart.timeScale().fitContent();
  }, [series]);

  return (
    <div className="w-full">
      {series.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {series.map((s, i) => (
            <span key={`${s.label}-${i}`} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color ?? undefined }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <div ref={containerRef} style={{ height }} className="w-full" />
    </div>
  );
}
