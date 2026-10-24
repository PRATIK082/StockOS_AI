"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type SearchResult } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface Props {
  placeholder?: string;
  market?: "india" | "us";
  value?: SearchResult | null;
  onSelect: (result: SearchResult) => void;
  autoFocus?: boolean;
}

export default function SymbolSearch({ placeholder, market, value, onSelect, autoFocus }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["search", query, market],
    queryFn: () =>
      api.get<{ results: SearchResult[] }>(
        `/instruments/search?q=${encodeURIComponent(query)}&limit=8${market ? `&market=${market}` : ""}`,
      ),
    enabled: query.length >= 1 || open,
  });

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const results = data?.results ?? [];

  return (
    <div ref={boxRef} className="relative flex-1">
      <Input
        autoFocus={autoFocus}
        value={value ? value.symbol : query}
        placeholder={placeholder ?? "Search India & US markets…"}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results.length > 0) {
            e.preventDefault();
            onSelect(results[0]);
            setQuery("");
            setOpen(false);
          }
        }}
      />
      {open && results.length > 0 && (
        <ul className="absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-lg">
          {results.map((r) => (
            <li key={r.symbol}>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent"
                onClick={() => {
                  onSelect(r);
                  setQuery("");
                  setOpen(false);
                }}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className={cn("font-medium", r.index && "text-muted-foreground")}>{r.symbol}</span>
                  <span className="truncate text-xs text-muted-foreground">{r.name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <Badge variant="secondary">{r.market === "india" ? "India" : "US"}</Badge>
                  <Badge variant="outline">{r.currency}</Badge>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}