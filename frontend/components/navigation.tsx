"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import {
  Home,
  TrendingUp,
  Target,
  DollarSign,
  Search,
  Eye,
  Briefcase,
  MessageSquare,
  Layers,
  Bot,
  Menu,
  X,
  BarChart3,
  Sigma,
  CalendarClock,
  Settings,
  Activity,
  Sparkles,
  ChevronDown,
} from "lucide-react"
import { useState, useEffect, useRef } from "react"

type NavItem = { href: string; label: string; icon: typeof Home }
type NavGroup = { label: string; icon: typeof Home; items: NavItem[] }

const groups: NavGroup[] = [
  {
    label: "Market",
    icon: TrendingUp,
    items: [
      { href: "/", label: "Dashboard", icon: Home },
      { href: "/scanner", label: "Scanner", icon: TrendingUp },
      { href: "/sectors", label: "Sectors", icon: Layers },
      { href: "/screener", label: "Screener", icon: Search },
      { href: "/intraday", label: "Intraday", icon: Activity },
    ],
  },
  {
    label: "Analytics",
    icon: BarChart3,
    items: [
      { href: "/prediction", label: "Prediction", icon: Target },
      { href: "/factors", label: "Factor Lab", icon: Sigma },
      { href: "/backtest", label: "Backtest", icon: BarChart3 },
      { href: "/scheduled", label: "Scheduled", icon: CalendarClock },
    ],
  },
  {
    label: "Trading",
    icon: Bot,
    items: [
      { href: "/trading", label: "Terminal", icon: Bot },
      { href: "/trading/autopilot", label: "AI Agent", icon: Sparkles },
      { href: "/options", label: "Options", icon: DollarSign },
      { href: "/portfolio", label: "Portfolio", icon: Briefcase },
    ],
  },
  {
    label: "AI",
    icon: MessageSquare,
    items: [
      { href: "/chat", label: "AI Chat", icon: MessageSquare },
      { href: "/watchlist", label: "Watchlist", icon: Eye },
    ],
  },
  {
    label: "Manage",
    icon: Settings,
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/broker-management", label: "Broker Mgmt", icon: Settings },
    ],
  },
]

export function Navigation() {
  const pathname = usePathname()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [now, setNow] = useState<string | null>(null)
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const navRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setNow(new Date().toLocaleTimeString())
    const t = setInterval(() => setNow(new Date().toLocaleTimeString()), 1000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setOpenGroup(null)
    }
    document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [])

  const isActiveGroup = (g: NavGroup) => g.items.some((i) => pathname === i.href)

  return (
    <nav className="sticky top-0 z-40 border-b border-border bg-card/70 backdrop-blur-xl">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6">
        <div className="flex h-14 items-center gap-4">
          <Link href="/" className="flex items-center gap-2 shrink-0">
            <TrendingUp className="h-6 w-6 text-primary" />
            <span className="font-bold text-lg tracking-tight">StockOS AI</span>
          </Link>

          <div ref={navRef} className="hidden lg:flex items-center gap-1">
            {groups.map((g) => {
              const active = isActiveGroup(g)
              const Icon = g.icon
              const open = openGroup === g.label
              return (
                <div key={g.label} className="relative">
                  <button
                    type="button"
                    onClick={() => setOpenGroup(open ? null : g.label)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors whitespace-nowrap",
                      active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {g.label}
                    <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
                  </button>
                  {open && (
                    <div className="absolute left-0 top-full mt-1 min-w-[180px] rounded-md border border-border bg-popover shadow-lg p-1 z-50">
                      {g.items.map((item) => {
                        const ItemIcon = item.icon
                        const isActive = pathname === item.href
                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            onClick={() => setOpenGroup(null)}
                            className={cn(
                              "flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium transition-colors",
                              isActive ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                            )}
                          >
                            <ItemIcon className="h-3.5 w-3.5" />
                            {item.label}
                          </Link>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="hidden sm:block text-[11px] text-muted-foreground">
              {now ?? ""}
            </div>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="lg:hidden inline-flex items-center justify-center p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent"
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>

      {mobileMenuOpen && (
        <div className="lg:hidden border-t border-border bg-card/95 max-h-[70vh] overflow-y-auto">
          <div className="px-4 py-3 space-y-3">
            {groups.map((g) => (
              <div key={g.label}>
                <div className="px-2 py-1 text-[10px] font-semibold uppercase text-muted-foreground">{g.label}</div>
                <div className="grid grid-cols-2 gap-1">
                  {g.items.map((item) => {
                    const isActive = pathname === item.href
                    const Icon = item.icon
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={cn(
                          "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                          isActive ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        )}
                        onClick={() => setMobileMenuOpen(false)}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </nav>
  )
}