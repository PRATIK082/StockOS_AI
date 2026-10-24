"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, Save, Settings2, ShieldCheck } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { fetchSettings, updateSettings, fmtCurrency } from "@/lib/trading"

interface TermSettings {
  execution_mode: string
  selected_execution_broker: string
  selected_market_data_source: string
  max_order_risk_rupees: number
  max_daily_loss_rupees: number
  max_open_positions: number
  max_capital_deployed_percent: number
  max_fno_lots: number
  daily_pnl_rupees: number
}

const initial: TermSettings = {
  execution_mode: "PAPER",
  selected_execution_broker: "paper",
  selected_market_data_source: "yahoo",
  max_order_risk_rupees: 2000,
  max_daily_loss_rupees: 5000,
  max_open_positions: 20,
  max_capital_deployed_percent: 50,
  max_fno_lots: 10,
  daily_pnl_rupees: 0,
}

export default function TradingSettingsPage() {
  const [form, setForm] = useState<TermSettings>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [flash, setFlash] = useState("")

  const load = useCallback(async () => {
    try {
      const s = await fetchSettings()
      setForm({
        execution_mode: (s.execution_mode as string) ?? "PAPER",
        selected_execution_broker: (s.selected_execution_broker as string) ?? "paper",
        selected_market_data_source: (s.selected_market_data_source as string) ?? "yahoo",
        max_order_risk_rupees: (s.max_order_risk_rupees as number) ?? 2000,
        max_daily_loss_rupees: (s.max_daily_loss_rupees as number) ?? 5000,
        max_open_positions: (s.max_open_positions as number) ?? 20,
        max_capital_deployed_percent: (s.max_capital_deployed_percent as number) ?? 50,
        max_fno_lots: (s.max_fno_lots as number) ?? 10,
        daily_pnl_rupees: (s.daily_pnl_rupees as number) ?? 0,
      })
    } catch (err) {
      setError((err as Error).message || "Failed to load settings")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const set = <K extends keyof TermSettings>(k: K, v: TermSettings[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  async function handleSave() {
    setSaving(true)
    setError("")
    setFlash("")
    try {
      await updateSettings({
        execution_mode: form.execution_mode,
        selected_execution_broker: form.selected_execution_broker,
        selected_market_data_source: form.selected_market_data_source,
        max_order_risk_rupees: form.max_order_risk_rupees,
        max_daily_loss_rupees: form.max_daily_loss_rupees,
        max_open_positions: form.max_open_positions,
        max_capital_deployed_percent: form.max_capital_deployed_percent,
        max_fno_lots: form.max_fno_lots,
      })
      setFlash("Settings saved. Risk guards now use the new limits.")
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Save failed")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5 max-w-2xl">
      <div className="flex items-center gap-2">
        <Settings2 className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Trading Settings</h1>
      </div>

      {flash && <p className="text-sm text-positive">{flash}</p>}
      {error && <p className="text-sm text-negative">{error}</p>}

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Execution</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Execution mode</Label>
            <select
              value={form.execution_mode}
              onChange={(e) => set("execution_mode", e.target.value)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
            >
              <option value="PAPER">PAPER (simulated)</option>
              <option value="REQUIRE_APPROVAL">REQUIRE_APPROVAL</option>
              <option value="LIVE_ENABLED">LIVE_ENABLED</option>
            </select>
            <p className="text-xs text-muted-foreground">
              {form.execution_mode === "PAPER"
                ? "All orders are simulated through PaperBroker. Never sends live orders."
                : form.execution_mode === "REQUIRE_APPROVAL"
                ? "Simulated but requires manual approval before execution."
                : "LIVE mode — only enable with real broker credentials configured."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Broker</Label>
              <select
                value={form.selected_execution_broker}
                onChange={(e) => set("selected_execution_broker", e.target.value)}
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
              >
                <option value="paper">paper</option>
                <option value="zerodha">zerodha</option>
                <option value="angelone">angelone</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>Market data source</Label>
              <select
                value={form.selected_market_data_source}
                onChange={(e) => set("selected_market_data_source", e.target.value)}
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-1 text-sm"
              >
                <option value="yahoo">yahoo</option>
                <option value="tradingview">tradingview</option>
                <option value="nse">nse</option>
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" /> Risk limits
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="s-risk">Max order risk (₹)</Label>
            <Input
              id="s-risk"
              type="number"
              min={1}
              value={form.max_order_risk_rupees}
              onChange={(e) => set("max_order_risk_rupees", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-loss">Max daily loss (₹)</Label>
            <Input
              id="s-loss"
              type="number"
              min={1}
              value={form.max_daily_loss_rupees}
              onChange={(e) => set("max_daily_loss_rupees", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-pos">Max open positions</Label>
            <Input
              id="s-pos"
              type="number"
              min={1}
              max={200}
              value={form.max_open_positions}
              onChange={(e) => set("max_open_positions", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-cap">Max capital deployed (%)</Label>
            <Input
              id="s-cap"
              type="number"
              min={1}
              max={100}
              value={form.max_capital_deployed_percent}
              onChange={(e) => set("max_capital_deployed_percent", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-fno">Max F&O lots</Label>
            <Input
              id="s-fno"
              type="number"
              min={1}
              max={100}
              value={form.max_fno_lots}
              onChange={(e) => set("max_fno_lots", Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5 flex items-end">
            <div className="w-full rounded-md bg-muted/50 px-3 py-2 text-sm flex items-center justify-between">
              <span className="text-muted-foreground">Today's P&L (UTC)</span>
              <span className="tabular-nums font-medium">{fmtCurrency(form.daily_pnl_rupees)}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Button onClick={handleSave} disabled={saving} className="w-full sm:w-auto">
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        Save settings
      </Button>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Status</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-2 text-sm">
          <Badge variant={form.execution_mode === "PAPER" ? "positive" : "negative"}>
            {form.execution_mode}
          </Badge>
          <span className="text-muted-foreground">
            {form.execution_mode === "PAPER"
              ? "Safe — nothing can reach a real exchange."
              : "Live-capable — broker must be verified before trading."}
          </span>
        </CardContent>
      </Card>
    </div>
  )
}