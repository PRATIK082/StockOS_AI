"use client"

import * as React from "react"
import { useState } from "react"
import { Loader2, Zap } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { submitOrder } from "@/lib/trading"
import { cn } from "@/lib/utils"
import { SymbolSearch } from "@/components/stock/symbol-search"

interface OrderFormProps {
  defaultSymbol?: string
  lastPrice?: number | null
  onFilled?: (msg: string) => void
  className?: string
}

export function OrderForm({ defaultSymbol = "", lastPrice, onFilled, className }: OrderFormProps) {
  const [symbol, setSymbol] = useState(defaultSymbol)
  const [side, setSide] = useState<"BUY" | "SELL">("BUY")
  const [quantity, setQuantity] = useState("10")
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET")
  const [limitPrice, setLimitPrice] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  const effectivePrice = orderType === "LIMIT" && limitPrice ? Number(limitPrice) : lastPrice || 0
  const notional = (Number(quantity) || 0) * (effectivePrice || 0)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setSuccess("")
    if (!symbol) {
      setError("Pick a symbol first")
      return
    }
    const qty = Number(quantity)
    if (isNaN(qty) || qty <= 0) {
      setError("Quantity must be a positive number")
      return
    }
    setSubmitting(true)
    try {
      const res = await submitOrder({
        symbol,
        side,
        quantity: qty,
        order_type: orderType,
        price: orderType === "LIMIT" && limitPrice ? Number(limitPrice) : undefined,
      })
      const msg = `Order filled @ ${(res.fill_price ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}  (${side} ${qty})`
      setSuccess(msg)
      onFilled?.(msg)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Order failed"
      setError(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className={cn("space-y-4", className)}>
      <div className="space-y-1.5">
        <Label htmlFor="of-symbol">Symbol</Label>
        <SymbolSearch
          onSelect={(s) => {
            setSymbol(s)
            setError("")
          }}
          placeholder="Search symbol…"
        />
      </div>

      <Tabs value={side} onValueChange={(v) => setSide(v as "BUY" | "SELL")}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="BUY" className="text-positive data-[state=active]:text-positive">
            BUY
          </TabsTrigger>
          <TabsTrigger value="SELL" className="text-negative data-[state=active]:text-negative">
            SELL
          </TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="of-qty">Quantity</Label>
          <Input
            id="of-qty"
            type="number"
            min={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Order type</Label>
          <Tabs value={orderType} onValueChange={(v) => setOrderType(v as "MARKET" | "LIMIT")}>
            <TabsList className="grid w-full grid-cols-2 h-9">
              <TabsTrigger value="MARKET">MKT</TabsTrigger>
              <TabsTrigger value="LIMIT">LMT</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      {orderType === "LIMIT" && (
        <div className="space-y-1.5">
          <Label htmlFor="of-limit">Limit price</Label>
          <Input
            id="of-limit"
            type="number"
            step="any"
            placeholder={lastPrice ? String(lastPrice) : "0.00"}
            value={limitPrice}
            onChange={(e) => setLimitPrice(e.target.value)}
          />
        </div>
      )}

      <div className="rounded-md bg-muted/50 px-3 py-2 text-sm">
        <div className="flex justify-between text-muted-foreground">
          <span>Est. price</span>
          <span className="tabular-nums">
            {effectivePrice
              ? effectivePrice.toLocaleString(undefined, { maximumFractionDigits: 2 })
              : "—"}
          </span>
        </div>
        <div className="flex justify-between text-muted-foreground">
          <span>Notional</span>
          <span className="tabular-nums">
            {notional ? `₹${notional.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—"}
          </span>
        </div>
      </div>

      {error && <p className="text-sm text-negative">{error}</p>}
      {success && <p className="text-sm text-positive">{success}</p>}

      <Button type="submit" disabled={submitting} className="w-full" variant={side === "BUY" ? "default" : "secondary"}>
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
        {side === "BUY" ? "Buy / Open" : "Sell / Close"} {symbol ? `· ${symbol}` : ""}
      </Button>
    </form>
  )
}