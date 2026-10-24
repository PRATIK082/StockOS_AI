"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Bot,
  ChevronRight,
  LayoutDashboard,
  Loader2,
  Radar,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import MarketChart from "@/components/stock/MarketChart";
import { OrderForm } from "@/components/trading/OrderForm";
import { PositionsTable } from "@/components/trading/PositionsTable";
import { StatCard } from "@/components/trading/StatCard";
import { RiskMeter } from "@/components/trading/RiskMeter";
import AgenticTradingPanel from "@/components/stock/AgenticTradingPanel";
import LearningMemoryCard from "@/components/stock/LearningMemoryCard";
import CommandBar from "@/components/trading/CommandBar";
import WorkspacePanel from "@/components/trading/WorkspacePanel";
import { TerminalProvider, useTerminal } from "@/lib/terminal-store";
import {
  fetchAutopilotState,
  fetchAutopilotRuns,
  runAutopilot,
  toggleAutopilot,
  toggleTradebot,
  executeTradebotSignal,
  type AutopilotState,
  type AutopilotRun,
  fmt,
  fmtCurrency,
  fmtPct,
  pnlFmt,
} from "@/lib/trading";

function TerminalCommandCenter() {
  const {
    symbol,
    setSymbol,
    analytics,
    positions,
    positionsSummary,
    orders,
    tradebot,
    loading,
    error,
    refresh,
  } = useTerminal();

  const [autopilot, setAutopilot] = useState<AutopilotState | null>(null);
  const [runs, setRuns] = useState<AutopilotRun[]>([]);
  const [missionBusy, setMissionBusy] = useState(false);

  const loadAgents = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([fetchAutopilotState(), fetchAutopilotRuns()]);
      setAutopilot(s);
      setRuns(r.runs);
    } catch {
      // keep terminal usable even if agent service is down
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const summary = analytics?.summary;
  const risk = analytics?.risk;

  if (loading && !analytics) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <LayoutDashboard className="h-5 w-5 text-primary" />
          <h1 className="text-xl font-semibold">Terminal Command Center</h1>
          <Badge variant="outline" className="text-positive">PAPER</Badge>
          <Badge variant="secondary" className="text-xs">
            {tradebot?.enabled ? "TradeBot live" : "TradeBot paused"}
          </Badge>
        </div>
        <Button variant="outline" size="sm" onClick={() => { refresh(); void loadAgents(); }}>
          <Activity className="h-4 w-4 mr-1" /> Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-negative/30 bg-negative/5 px-4 py-3 text-sm text-negative">
          {error}
        </div>
      )}

      {/* Unified command bar + KPIs */}
      <CommandBar />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Equity" value={fmtCurrency(summary?.current_equity)} sub={`Base ${fmtCurrency(summary?.base_capital)}`} accent="neutral" icon={<TrendingUp className="h-4 w-4" />} />
        <StatCard label="Total P&L" value={pnlFmt(summary?.total_pnl)} sub={fmtPct(summary?.pnl_pct)} accent={summary?.total_pnl && summary.total_pnl > 0 ? "positive" : summary?.total_pnl && summary.total_pnl < 0 ? "negative" : "muted"} icon={<Activity className="h-4 w-4" />} />
        <StatCard label="Open Positions" value={positionsSummary?.count ?? positions.length} sub={risk ? `Limit ${risk.max_open_positions}` : undefined} accent="neutral" icon={<Wallet className="h-4 w-4" />} />
        <StatCard label="Daily P&L" value={pnlFmt(risk?.daily_pnl_rupees)} sub={risk ? `Stop ${fmtCurrency(risk.max_daily_loss_rupees)}` : undefined} accent={risk?.daily_pnl_rupees && risk.daily_pnl_rupees > 0 ? "positive" : risk?.daily_pnl_rupees && risk.daily_pnl_rupees < 0 ? "negative" : "muted"} icon={<ShieldAlert className="h-4 w-4" />} />
      </div>

      {/* Main workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Left: market + positions/orders + risk */}
        <div className="space-y-4 xl:col-span-2">
          <WorkspacePanel title="Market & Chart">
            <div className="flex items-center gap-2 mb-3">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-48 h-8 text-xs">
                  <SelectValue placeholder="Symbol" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="NSE:NIFTY">NSE:NIFTY</SelectItem>
                  <SelectItem value="NSE:BANKNIFTY">NSE:BANKNIFTY</SelectItem>
                  <SelectItem value="NSE:RELIANCE">NSE:RELIANCE</SelectItem>
                  <SelectItem value="NSE:TCS">NSE:TCS</SelectItem>
                  <SelectItem value="NYSE:AAPL">NYSE:AAPL</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="h-[320px] w-full">
              {symbol ? <MarketChart symbol={symbol} /> : <div className="text-muted-foreground text-sm p-6">Select a symbol</div>}
            </div>
          </WorkspacePanel>

          <WorkspacePanel title="Positions & Orders">
            <PositionsTable positions={positions} className="border-0 rounded-none" />
            {orders.length > 0 && (
              <div className="mt-4">
                <h3 className="mb-2 text-xs font-medium uppercase text-muted-foreground">Recent orders</h3>
                <ul className="divide-y divide-border">
                  {orders.slice(0, 8).map((o) => (
                    <li key={o.id} className="flex items-center justify-between py-2 text-sm">
                      <span className="font-medium">{o.symbol}</span>
                      <span className={o.side === "BUY" ? "text-positive" : "text-negative"}>{o.side}</span>
                      <span className="tabular-nums text-muted-foreground">{o.quantity} @ {fmt(o.price)}</span>
                      <span className="text-xs text-muted-foreground">{(o.status || "").toUpperCase()}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </WorkspacePanel>

          <WorkspacePanel title="Risk Guardrails" defaultOpen={false}>
            <div className="space-y-3">
              <RiskMeter value={risk?.capital_deployed_pct ?? 0} max={risk?.max_capital_deployed_percent || 100} label="Capital deployed" sub={`of ${risk?.max_capital_deployed_percent ?? 0}% limit`} />
              <RiskMeter value={positions.length} max={risk?.max_open_positions || 20} label="Open positions" sub={`of ${risk?.max_open_positions ?? 20} max`} />
              <RiskMeter value={Math.abs(risk?.daily_pnl_rupees ?? 0)} max={risk?.max_daily_loss_rupees || 5000} label="Daily loss used" dangerThreshold={0.6} sub="against daily stop" />
            </div>
          </WorkspacePanel>
        </div>

        {/* Right: execution + AI workbench + agents */}
        <div className="space-y-4">
          <WorkspacePanel title="Execute Order">
            <OrderForm defaultSymbol={symbol} lastPrice={undefined} onFilled={refresh} />
          </WorkspacePanel>

          <WorkspacePanel title="AI Workbench">
            <AgenticTradingPanel defaultOpen />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" asChild>
                <Link href="/trading/backtest"><Zap className="mr-1 h-3.5 w-3.5" /> Backtest</Link>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link href="/trading/autopilot"><Sparkles className="mr-1 h-3.5 w-3.5" /> Autopilot</Link>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link href="/trading/desk"><Bot className="mr-1 h-3.5 w-3.5" /> Trading Desk</Link>
              </Button>
            </div>
          </WorkspacePanel>

          <WorkspacePanel title="TradeBot Signals" defaultOpen={false}>
            <div className="space-y-2">
              {(tradebot?.signals || []).length === 0 && (
                <p className="text-xs text-muted-foreground">No live signals right now. Refresh or run scanner.</p>
              )}
              {(tradebot?.signals || []).slice(0, 6).map((s) => (
                <div key={s.symbol} className="flex items-center justify-between rounded border border-border/60 px-2 py-1.5 text-xs">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{s.symbol}</div>
                    <div className="text-muted-foreground truncate">{s.name} · {s.criteria.join(", ")}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={s.change_pct >= 0 ? "text-positive" : "text-negative"}>{fmtPct(s.change_pct)}</span>
                    <Button size="sm" variant="outline" disabled={missionBusy || !tradebot?.enabled} onClick={async () => { setMissionBusy(true); try { await executeTradebotSignal({ symbol: s.symbol, side: "BUY", quantity: 1 }); refresh(); } finally { setMissionBusy(false); } }}>
                      Buy
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </WorkspacePanel>

          <WorkspacePanel title="AI Auto-Trading Cockpit">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm">
                Autopilot:{" "}
                <span className={autopilot?.enabled ? "text-positive font-medium" : "text-muted-foreground"}>
                  {autopilot?.enabled ? "ON" : "OFF"}
                </span>
              </span>
              <div className="flex gap-2">
                <Button size="sm" onClick={async () => { setMissionBusy(true); try { await toggleAutopilot(!(autopilot?.enabled)); await loadAgents(); } finally { setMissionBusy(false); } }}>
                  {missionBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  {autopilot?.enabled ? "Disable" : "Enable"} Autopilot
                </Button>
                <Button size="sm" variant="outline" disabled={missionBusy} onClick={async () => { setMissionBusy(true); try { await toggleTradebot(!(tradebot?.enabled)); refresh(); } finally { setMissionBusy(false); } }}>
                  {tradebot?.enabled ? "Pause" : "Start"} TradeBot
                </Button>
                <Button size="sm" variant="outline" disabled={missionBusy} onClick={async () => { setMissionBusy(true); try { await runAutopilot(false); await loadAgents(); refresh(); } finally { setMissionBusy(false); } }}>
                  Run mission
                </Button>
                <Button size="sm" variant="outline" disabled={missionBusy} onClick={async () => { setMissionBusy(true); try { await runAutopilot(true); await loadAgents(); } finally { setMissionBusy(false); } }}>
                  Monitor
                </Button>
              </div>
            </div>
            {autopilot?.last_review && (
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-muted/50 px-2 py-1">Score {(autopilot.last_review.score * 100).toFixed(0)}%</div>
                <div className="rounded bg-muted/50 px-2 py-1">Fills {autopilot.last_review.n_fills}/{autopilot.last_review.n_rejects} rej</div>
                <div className="rounded bg-muted/50 px-2 py-1">F&O {autopilot.last_review.n_option_tracks}</div>
                <div className="rounded bg-muted/50 px-2 py-1">P&L {pnlFmt(autopilot.last_review.realised_pnl)}</div>
              </div>
            )}
            {runs.length > 0 && (
              <ul className="mt-3 divide-y divide-border text-xs">
                {runs.slice(0, 5).map((r) => (
                  <li key={r.id} className="flex items-center justify-between py-1.5">
                    <span className="truncate">{r.mission}</span>
                    <Badge variant="outline" className={r.status === "completed" ? "text-positive" : "text-negative"}>{r.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </WorkspacePanel>

          <WorkspacePanel title="AI Learning Memory" defaultOpen={false}>
            <LearningMemoryCard />
          </WorkspacePanel>
        </div>
      </div>
    </div>
  );
}

export default function TradingPage() {
  return (
    <TerminalProvider>
      <TerminalCommandCenter />
    </TerminalProvider>
  );
}