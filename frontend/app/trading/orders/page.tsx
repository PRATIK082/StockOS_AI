"use client"

import { useCallback, useEffect, useState } from "react"
import { BookOpenCheck, Loader2, OctagonX, SquareX, ZapOff } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { StatCard } from "@/components/trading/StatCard"
import { api } from "@/lib/api-client"
import { fetchOrders, fmt, type OrderRecord } from "@/lib/trading"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [result, setResult] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setOrders(await fetchOrders())
    } catch (err) {
      setError((err as Error).message || "Failed to load orders")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const nFilled = orders.filter((o) => o.status === "filled").length
  const notional = orders
    .filter((o) => o.status === "filled")
    .reduce((s, o) => s + o.price * o.quantity, 0)

  async function runAction(action: "kill-switch" | "cancel-all" | "square-off") {
    setBusy(action)
    setError("")
    setResult("")
    try {
      const { data } = await api.post(`/api/v1/orders/${action}`)
      const payload = Object.values(data)[0] as Record<string, unknown> | undefined
      const closed = (payload?.closed_order_ids as string[] | undefined)?.length ?? 0
      setResult(`${action} done — ${closed} order(s) closed.`)
      load()
    } catch (err) {
      setError((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Action failed")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpenCheck className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Orders</h1>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <StatCard label="Total orders" value={orders.length} />
        <StatCard label="Filled" value={nFilled} accent="positive" />
        <StatCard label="Notional (filled)" value={`₹${fmt(notional, 0)}`} />
      </div>

      <div className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-sm font-medium mr-1">Bulk actions</span>
          <Button
            variant="outline"
            size="sm"
            disabled={!!busy}
            onClick={() => runAction("square-off")}
          >
            {busy === "square-off" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ZapOff className="h-4 w-4" />}
            Square off all
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!!busy}
            onClick={() => runAction("cancel-all")}
          >
            {busy === "cancel-all" ? <Loader2 className="h-4 w-4 animate-spin" /> : <SquareX className="h-4 w-4" />}
            Cancel all
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={!!busy}
            onClick={() => runAction("kill-switch")}
          >
            {busy === "kill-switch" ? <Loader2 className="h-4 w-4 animate-spin" /> : <OctagonX className="h-4 w-4" />}
            Kill switch
          </Button>
        </div>
        {result && <p className="mt-2 text-sm text-positive">{result}</p>}
        {error && <p className="mt-2 text-sm text-negative">{error}</p>}
        <p className="mt-2 text-xs text-muted-foreground">
          Paper mode — these actions simulate emergency closes at market prices; nothing hits a real exchange.
        </p>
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm font-medium">Order history</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">Notional</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      No orders yet. Place one from the dashboard.
                    </TableCell>
                  </TableRow>
                ) : (
                  orders.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell className="font-medium">{o.symbol}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={o.side === "BUY" ? "text-positive" : "text-negative"}>
                          {o.side}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{o.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(o.price)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(o.price * o.quantity, 0)}</TableCell>
                      <TableCell
                        className={cn(
                          "text-xs font-medium",
                          o.status === "filled" ? "text-positive" : o.status === "cancelled" ? "text-negative" : "text-muted-foreground"
                        )}
                      >
                        {(o.status || "").toUpperCase()}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}