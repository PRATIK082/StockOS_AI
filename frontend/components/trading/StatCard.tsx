import * as React from "react"
import { cn } from "@/lib/utils"

interface StatCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  accent?: "positive" | "negative" | "neutral" | "muted"
  icon?: React.ReactNode
}

const accentClasses: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-foreground",
  muted: "text-muted-foreground",
}

export function StatCard({ label, value, sub, accent = "neutral", icon, className, ...props }: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4 flex flex-col gap-1.5 min-w-0",
        className
      )}
      {...props}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide truncate">
          {label}
        </span>
        {icon ? <span className="text-muted-foreground shrink-0">{icon}</span> : null}
      </div>
      <div className={cn("text-2xl font-semibold tabular-nums truncate", accentClasses[accent])}>{value}</div>
      {sub ? <div className="text-xs text-muted-foreground truncate">{sub}</div> : null}
    </div>
  )
}