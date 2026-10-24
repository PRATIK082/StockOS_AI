"use client"

import Link from "next/link"
import { TerminalPosition } from "@/lib/trading"
import { fmt, fmtCurrency, fmtPct, pnlClass, pnlFmt } from "@/lib/trading"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

interface PositionsTableProps {
  positions: TerminalPosition[]
  className?: string
  onSelect?: (symbol: string) => void
  selectedSymbol?: string
}

export function PositionsTable({ positions, className, onSelect, selectedSymbol }: PositionsTableProps) {
  return (
    <div className={cn("rounded-lg border bg-card", className)}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Avg</TableHead>
            <TableHead className="text-right">LTP</TableHead>
            <TableHead className="text-right">Value</TableHead>
            <TableHead className="text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                No open positions. Place a paper order to start.
              </TableCell>
            </TableRow>
          ) : (
            positions.map((p) => (
              <TableRow
                key={p.symbol}
                className={cn("cursor-pointer", selectedSymbol === p.symbol && "bg-accent/50")}
                onClick={() => onSelect?.(p.symbol)}
              >
                <TableCell className="font-medium">
                  <Link
                    href={`/stock/${encodeURIComponent(p.symbol)}`}
                    onClick={(e) => e.stopPropagation()}
                    className="hover:underline"
                  >
                    {p.symbol}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">{p.quantity}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(p.average_price)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(p.last_price)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtCurrency(p.market_value)}</TableCell>
                <TableCell
                  className={cn(
                    "text-right tabular-nums whitespace-nowrap",
                    pnlClass(p.unrealised_pnl)
                  )}
                >
                  <span className="block">{pnlFmt(p.unrealised_pnl)}</span>
                  <span className="block text-xs opacity-80">{fmtPct(p.unrealised_pnl_pct)}</span>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}