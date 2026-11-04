"use client"

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Inbox, Loader2, RefreshCw, TrendingUp } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, ApiError, fmt } from "@/lib/api"
import { cn } from "@/lib/utils"

// --------------------------------------------------------------------------- types

type RangeKey = "7d" | "30d" | "90d" | "1y" | "all"

interface RealizedBlock {
  total: number
  per_symbol: Record<string, number>
  wins: number
  losses: number
  flats: number
  sells: number
}

interface UnrealizedBlock {
  total: number
  positions: Array<{
    symbol: string
    quantity: string
    pnl: number
    live: boolean
  }>
}

interface PnlSummary {
  range: string
  fills: number
  realized: RealizedBlock
  unrealized: UnrealizedBlock
  total_pnl: number
}

interface EquityPoint {
  t: string
  realized: number
  unrealized?: number
  total?: number
  live?: boolean
}

interface EquityResp {
  range: string
  points: EquityPoint[]
  note: string | null
  // Tolerated for forward-compat: some revisions return the live snapshot
  // as a separate object instead of a live-flagged last point.
  final_live_point?: { t: string; realized: number } | null
}

// --------------------------------------------------------------------------- constants

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "90d", label: "90D" },
  { key: "1y", label: "1Y" },
  { key: "all", label: "All" },
]

// --------------------------------------------------------------------------- helpers

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.message} (HTTP ${err.status})`
  if (err instanceof Error) return err.message
  return fallback
}

type Tone = "default" | "positive" | "negative"

function toneOf(v: number | null | undefined): Tone {
  if (v == null || v === 0) return "default"
  return v > 0 ? "positive" : "negative"
}

function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—"
  return `₹${fmt(v)}`
}

/** Backend timestamps are naive UTC ISO strings — tag them as UTC before parsing. */
function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  const d = new Date(hasTz ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

function fmtDate(iso: string | null | undefined): string {
  const d = parseUtc(iso)
  return d ? d.toLocaleDateString() : "—"
}

function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string
  value: string
  hint?: string | null
  tone?: Tone
}) {
  const toneClass =
    tone === "positive"
      ? "text-positive"
      : tone === "negative"
        ? "text-negative"
        : "text-foreground"
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-lg font-semibold tabular-nums", toneClass)}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function ErrorBanner({ err }: { err: unknown }) {
  return (
    <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {errText(err, "Request failed.")}
    </div>
  )
}

function Loading() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading…
    </div>
  )
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
      <Inbox className="h-8 w-8 text-muted-foreground" />
      {children}
    </div>
  )
}

// --------------------------------------------------------------------------- equity chart (inline SVG, no chart lib)

interface CurvePoint {
  t: string
  value: number
  live: boolean
}

function EquityChart({ points }: { points: CurvePoint[] }) {
  const W = 600
  const H = 200
  const P = 14

  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const flat = min === max

  const x = (i: number) =>
    points.length === 1 ? W / 2 : P + (i * (W - 2 * P)) / (points.length - 1)
  const y = (v: number) =>
    flat ? H / 2 : H - P - ((v - min) / (max - min)) * (H - 2 * P)

  const poly = points.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")
  const liveIdx = points.findIndex((p) => p.live)
  const showZero = !flat && min < 0 && max > 0

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-48 w-full"
        role="img"
        aria-label="Equity curve of cumulative realized P&L"
      >
        {showZero ? (
          <line
            x1={P}
            x2={W - P}
            y1={y(0)}
            y2={y(0)}
            stroke="currentColor"
            strokeDasharray="4 4"
            strokeWidth={1}
            className="text-muted-foreground"
            opacity={0.5}
          />
        ) : null}
        <polyline
          points={poly}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          className="text-primary"
        />
        {points.map((p, i) =>
          p.live && liveIdx === i ? (
            <circle
              key={`live-${i}`}
              cx={x(i)}
              cy={y(p.value)}
              r={4}
              fill="currentColor"
              className="text-positive"
            />
          ) : null,
        )}
      </svg>
      <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{fmtDate(points[0]?.t)}</span>
        <span className="tabular-nums">
          {money(min)} … {money(max)}
        </span>
        <span>{fmtDate(points[points.length - 1]?.t)}</span>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- page

export default function PnlPage() {
  const [range, setRange] = useState<RangeKey>("30d")

  const summary = useQuery<PnlSummary>({
    queryKey: ["pnl", "summary", range],
    queryFn: () => api.get<PnlSummary>(`/pnl/summary?range=${range}`),
    retry: false,
  })

  const equity = useQuery<EquityResp>({
    queryKey: ["pnl", "equity", range],
    queryFn: () => api.get<EquityResp>(`/pnl/equity?range=${range}`),
    retry: false,
  })

  const curve: CurvePoint[] = useMemo(() => {
    const pts: CurvePoint[] = (equity.data?.points ?? []).map((p) => ({
      t: p.t,
      value: p.live && p.total != null ? p.total : p.realized,
      live: p.live === true,
    }))
    const extra = equity.data?.final_live_point
    if (extra) pts.push({ t: extra.t, value: extra.realized, live: true })
    return pts
  }, [equity.data])

  const historicalCount = curve.filter((p) => !p.live).length
  const noFills = (summary.data?.fills ?? 0) === 0
  const showEmpty =
    !summary.isLoading && !equity.isLoading && (noFills || historicalCount === 0)
  const anyError = summary.error ?? equity.error

  const realized = summary.data?.realized
  const unrealized = summary.data?.unrealized
  const perSymbol = useMemo(
    () =>
      Object.entries(realized?.per_symbol ?? {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])),
    [realized],
  )

  const refresh = () => {
    summary.refetch()
    equity.refetch()
  }

  return (
    <div className="container mx-auto space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">P&amp;L</h1>
          <p className="text-sm text-muted-foreground">
            Realized (FIFO) plus live unrealized P&amp;L, with an equity curve of cumulative
            realized gains at fill timestamps.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Tabs value={range} onValueChange={(v) => setRange(v as RangeKey)}>
            <TabsList>
              {RANGES.map((r) => (
                <TabsTrigger key={r.key} value={r.key}>
                  {r.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            disabled={summary.isFetching || equity.isFetching}
          >
            <RefreshCw
              className={cn(
                "mr-2 h-4 w-4",
                (summary.isFetching || equity.isFetching) && "animate-spin",
              )}
            />
            Refresh
          </Button>
        </div>
      </div>

      {anyError ? <ErrorBanner err={anyError} /> : null}

      {/* Stat tiles */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" /> Summary · {range}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {summary.isLoading ? (
            <Loading />
          ) : summary.data ? (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <Stat
                  label="Realized P&L"
                  value={money(realized?.total)}
                  hint={
                    realized
                      ? `${realized.sells} sells · ${realized.wins}W / ${realized.losses}L / ${realized.flats} flat`
                      : undefined
                  }
                  tone={toneOf(realized?.total)}
                />
                <Stat
                  label="Unrealized P&L"
                  value={money(unrealized?.total)}
                  hint="Live quotes for current holdings"
                  tone={toneOf(unrealized?.total)}
                />
                <Stat
                  label="Total P&L"
                  value={money(summary.data.total_pnl)}
                  hint={`${summary.data.fills} fills in range`}
                  tone={toneOf(summary.data.total_pnl)}
                />
              </div>
              {perSymbol.length > 0 ? (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Realized by symbol</h3>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead className="text-right">Realized P&amp;L</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {perSymbol.map(([sym, gain]) => (
                        <TableRow key={sym}>
                          <TableCell className="font-medium">{sym}</TableCell>
                          <TableCell
                            className={cn(
                              "text-right tabular-nums",
                              gain > 0
                                ? "text-positive"
                                : gain < 0
                                  ? "text-negative"
                                  : "",
                            )}
                          >
                            {money(gain)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : null}
            </>
          ) : null}
        </CardContent>
      </Card>

      {/* Equity curve */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" /> Equity curve · {range}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {equity.isLoading ? (
            <Loading />
          ) : showEmpty ? (
            <EmptyState>
              <p className="font-medium text-foreground">No fills yet</p>
              <p className="max-w-md text-xs">
                Execute paper orders first — the equity curve plots cumulative realized P&amp;L
                at each sell fill, so there is nothing to draw until then.
              </p>
            </EmptyState>
          ) : curve.length > 0 ? (
            <EquityChart points={curve} />
          ) : (
            <EmptyState>No equity points returned for this range.</EmptyState>
          )}
          {equity.data?.note ? (
            <p className="text-[11px] text-muted-foreground">{equity.data.note}</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
