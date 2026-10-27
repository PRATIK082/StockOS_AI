"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Brain } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, getAuthToken } from "@/lib/api";

interface MemoryItem {
  key: string;
  value: unknown;
  kind?: string;
  scope?: string;
  updated_at?: string;
}

export default function LearningMemoryCard() {
  const [authenticated, setAuthenticated] = useState(false);
  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()));
  }, []);

  const { data } = useQuery({
    queryKey: ["memory", "all"],
    queryFn: () => api.get<MemoryItem[]>("/memory"),
    enabled: authenticated,
    retry: false,
  });

  const items = Array.isArray(data) ? data : [];

  const renderValue = (value: unknown): string => {
    if (typeof value === "string") return value;
    if (value == null) return "";
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Brain className="h-4 w-4 text-primary" /> AI Learning Memory
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!authenticated && (
          <p className="text-sm text-muted-foreground">Sign in to persist agent insights and self-learning notes.</p>
        )}
        {authenticated && items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No learned insights yet. Run the AI Trading Desk to seed memory.
          </p>
        )}
        {authenticated && items.length > 0 && (
          <ul className="space-y-2 max-h-48 overflow-auto">
            {items.slice(0, 8).map((m) => (
              <li key={m.key} className="rounded-md border border-border bg-muted/30 p-2 text-xs">
                <p className="font-medium text-foreground">{String(m.key)}</p>
                <pre className="line-clamp-6 whitespace-pre-wrap break-words text-muted-foreground">{renderValue(m.value)}</pre>
              </li>
            ))}
          </ul>
        )}
        {authenticated && items.length > 0 && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            {items.length} insight{items.length === 1 ? "" : "s"} stored · feeds future runs
          </p>
        )}
      </CardContent>
    </Card>
  );
}