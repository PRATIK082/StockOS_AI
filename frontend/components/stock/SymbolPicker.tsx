"use client";

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "@/lib/api-client";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface PickerResult {
  symbol: string;
  name: string;
  market?: "india" | "us";
  currency?: string;
  index?: boolean;
}

interface SymbolPickerProps {
  values: string[];
  onChange: (values: string[]) => void;
  single?: boolean;
  placeholder?: string;
  market?: "india" | "us";
  className?: string;
}

export default function SymbolPicker({ values, onChange, single, placeholder, market, className }: SymbolPickerProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PickerResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(async () => {
      const q = query.trim();
      if (!q) {
        setResults([]);
        return;
      }
      setLoading(true);
      try {
        const res = await api.get<{ results: PickerResult[] }>("/api/instruments/search", {
          params: { q, limit: 8, ...(market ? { market } : {}) },
        });
        setResults(res.data.results ?? []);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, market]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const add = (symbol: string) => {
    if (!symbol) return;
    if (single) {
      onChange([symbol]);
    } else if (!values.includes(symbol)) {
      onChange([...values, symbol]);
    }
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const remove = (symbol: string) => {
    onChange(values.filter((v) => v !== symbol));
  };

  return (
    <div ref={boxRef} className={cn("space-y-1.5", className)}>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <Badge key={v} variant="secondary" className="gap-1 pr-1">
              <span className="font-mono text-[11px]">{v}</span>
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => remove(v)}
                className="rounded-full p-0.5 hover:bg-muted-foreground/20"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          placeholder={placeholder ?? "Search India & US markets…"}
          className="pl-9"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results.length > 0) {
              e.preventDefault();
              add(results[0].symbol);
            }
          }}
        />
        {open && query.trim().length > 0 && (
          <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-lg">
            {loading ? (
              <div className="p-3 text-center text-sm text-muted-foreground">Searching…</div>
            ) : results.length > 0 ? (
              results.map((r) => (
                <button
                  key={r.symbol}
                  type="button"
                  className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent"
                  onClick={() => add(r.symbol)}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={cn("font-medium", r.index && "text-muted-foreground")}>{r.symbol}</span>
                    <span className="truncate text-xs text-muted-foreground">{r.name}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    <Badge variant="secondary">{r.market === "india" ? "India" : "US"}</Badge>
                    {r.currency && <Badge variant="outline">{r.currency}</Badge>}
                  </span>
                </button>
              ))
            ) : (
              <div className="p-3 text-center text-sm text-muted-foreground">No matches — type an exchange-prefixed ticker (e.g. NSE:RELIANCE)</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
