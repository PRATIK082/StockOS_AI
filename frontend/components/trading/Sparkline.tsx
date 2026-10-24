import { useMemo } from "react"
import { cn } from "@/lib/utils"

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  positive?: boolean | null
  className?: string
  strokeWidth?: number
}

export function Sparkline({
  data,
  width = 120,
  height = 36,
  positive: forcePositive,
  className,
  strokeWidth = 1.5,
}: SparklineProps) {
  const { path, area, color } = useMemo(() => {
    if (!data || data.length < 2) {
      return { path: "", area: "", color: "var(--muted-foreground)" }
    }
    const min = Math.min(...data)
    const max = Math.max(...data)
    const range = max - min || 1
    const step = width / (data.length - 1)
    const pts = data.map((v, i) => {
      const x = i * step
      const y = height - ((v - min) / range) * (height - 4) - 2
      return [x, y] as const
    })
    const d = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ")
    const a = `${d} L${width},${height} L0,${height} Z`
    const last = data[data.length - 1]
    const first = data[0]
    const up = last >= first
    const c = forcePositive != null && forcePositive !== up ? (forcePositive ? "var(--positive)" : "var(--negative)") : up ? "var(--positive)" : "var(--negative)"
    return { path: d, area: a, color: c }
  }, [data, width, height, forcePositive])

  if (!path) return <svg width={width} height={height} className={className} />

  return (
    <svg width={width} height={height} className={className} aria-hidden>
      <path d={area} fill={color} opacity={0.12} />
      <path d={path} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function SparklineFromPoints({
  points,
  valueKey,
  ...rest
}: {
  points: Array<Record<string, unknown>>
  valueKey: string
} & Omit<SparklineProps, "data">) {
  const data = useMemo(
    () => (points || []).map((p) => (p[valueKey] as number) ?? 0),
    [points, valueKey]
  )
  return <Sparkline data={data} {...rest} />
}

export function PnLChip({ value, className }: { value: number | null | undefined; className?: string }) {
  const cls = cn(
    "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium tabular-nums",
    value == null
      ? "text-muted-foreground"
      : value > 0
      ? "bg-positive/10 text-positive"
      : value < 0
      ? "bg-negative/10 text-negative"
      : "text-muted-foreground",
    className
  )
  const sign = value != null && value > 0 ? "+" : ""
  return <span className={cls}>{value == null ? "—" : `${sign}${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}</span>
}