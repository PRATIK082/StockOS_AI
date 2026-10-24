import * as React from "react"
import { cn } from "@/lib/utils"

interface RiskMeterProps {
  /** Current value between 0 and max */
  value: number
  /** Threshold at which risk turns orange (default 0.5*max) */
  max: number
  label?: string
  sub?: string
  dangerThreshold?: number
  className?: string
}

export function RiskMeter({ value, max, label, sub, dangerThreshold, className }: RiskMeterProps) {
  const safe = Math.max(0, Math.min(value, max))
  const pct = max > 0 ? (safe / max) * 100 : 0
  const danger = dangerThreshold ?? 0.75
  const color = pct >= danger * 100 ? "bg-negative" : pct >= 0.5 * 100 ? "bg-amber-500" : "bg-positive"
  return (
    <div className={cn("rounded-lg border bg-card p-4", className)}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-medium">
          {label ?? "Utilization"}
          {sub && <span className="ml-2 text-xs text-muted-foreground">{sub}</span>}
        </div>
        <div className="text-sm font-semibold tabular-nums">{pct.toFixed(0)}%</div>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground">
        <span>0</span>
        <span>{max.toLocaleString()}</span>
      </div>
    </div>
  )
}