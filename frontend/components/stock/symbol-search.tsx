"use client"

import { useState, useEffect, useCallback } from "react"
import { Search } from "lucide-react"
import { api } from "@/lib/api-client"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

interface SymbolSearchProps {
  onSelect: (symbol: string) => void
  placeholder?: string
  className?: string
  /** Controlled input text. When omitted the component manages its own state. */
  value?: string
  /** Fires on every keystroke in controlled mode (and on suggestion pick). */
  onChange?: (value: string) => void
}

interface SearchResult {
  symbol: string
  name: string
  exchange?: string
  sector?: string
  index?: boolean
}

export function SymbolSearch({ onSelect, placeholder = "Search stocks...", className, value, onChange }: SymbolSearchProps) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<SearchResult[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const text = value !== undefined ? value : query

  const handleInput = (v: string) => {
    if (onChange) onChange(v)
    else setQuery(v)
    setIsOpen(true)
  }

  const searchSymbols = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setResults([])
      return
    }

    setLoading(true)
    try {
      const response = await api.get("/api/instruments/search", {
        params: { q: searchQuery, limit: 10 }
      })
      setResults(response.data.results || [])
    } catch (error) {
      console.error("Search failed:", error)
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      searchSymbols(text)
    }, 300)

    return () => clearTimeout(timer)
  }, [text, searchSymbols])

  const handleSelect = (symbol: string) => {
    onSelect(symbol)
    if (onChange) onChange(symbol)
    else setQuery(symbol)
    setIsOpen(false)
  }

  return (
    <div className={cn("relative", className)}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
        <Input
          type="text"
          value={text}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => setIsOpen(true)}
          placeholder={placeholder}
          className="pl-10"
        />
      </div>

      {isOpen && (text.length > 0) && (
        <div className="absolute z-50 w-full mt-1 bg-popover border border-border rounded-md shadow-lg max-h-60 overflow-auto">
          {loading ? (
            <div className="p-4 text-center text-sm text-muted-foreground">Searching...</div>
          ) : results.length > 0 ? (
            results.map((result) => (
              <button
                key={result.symbol}
                onClick={() => handleSelect(result.symbol)}
                className="w-full text-left px-4 py-2 hover:bg-accent hover:text-accent-foreground border-b border-border last:border-0"
              >
                <div className="flex justify-between items-start gap-2">
                  <div className="min-w-0">
                    <div className="font-medium flex items-center gap-1.5">
                      <span className="truncate">{result.symbol}</span>
                      {result.index && (
                        <span className="shrink-0 inline-flex rounded px-1 py-0 text-[10px] font-medium bg-primary/10 text-primary">
                          INDEX
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-muted-foreground truncate">{result.name}</div>
                  </div>
                  {result.exchange && (
                    <div className="text-xs text-muted-foreground shrink-0">{result.exchange}</div>
                  )}
                </div>
              </button>
            ))
          ) : (
            <div className="p-4 text-center text-sm text-muted-foreground">No results found</div>
          )}
        </div>
      )}
    </div>
  )
}