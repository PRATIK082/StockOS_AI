"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { VibeEvent } from "@/lib/api";
import { getAuthToken } from "@/lib/api";
import { VIBE_API_ORIGIN } from "@/lib/vibe";

export type DeepStageStatus = "done" | "skipped" | "error";

export interface DeepStageState {
  status: DeepStageStatus;
  data: Record<string, any>;
  symbol: string;
}

export interface DeepAnswer {
  answer: string;
  confidence: number;
  symbol: string;
  sources: string[];
}

export interface DeepRunState {
  plan: Array<{ key: string; label: string }>;
  stages: Record<string, DeepStageState>;
  answer: DeepAnswer | null;
  error: string | null;
}

export function emptyDeepRun(): DeepRunState {
  return { plan: [], stages: {}, answer: null, error: null };
}

function stageSymbol(key: string): string {
  return key.split("|")[0] ?? key;
}

function stageMeasure(key: string): string {
  const i = key.indexOf("|");
  return i === -1 ? key : key.slice(i + 1);
}

export function applyDeepEvent(run: DeepRunState, ev: any): DeepRunState {
  if (ev.type === "plan") {
    return { ...run, plan: ev.plan };
  }
  if (ev.type === "stage") {
    return {
      ...run,
      stages: {
        ...run.stages,
        [ev.key]: { status: ev.status, data: ev.data, symbol: stageSymbol(ev.key) },
      },
    };
  }
  if (ev.type === "answer") {
    return { ...run, answer: ev.data };
  }
  if (ev.type === "error") {
    return { ...run, error: ev.data?.detail ?? ev.data ?? "Deep analysis stream error", answer: null };
  }
  return run;
}

export interface DeepRunController {
  run: DeepRunState;
  streaming: boolean;
  start: (symbols: string[], question: string, opts?: { include?: string[]; provider?: string }) => Promise<DeepRunState>;
  cancel: () => void;
  reset: () => void;
}

export function useDeepAnalysis(): DeepRunController {
  const [run, setRun] = useState<DeepRunState>(emptyDeepRun);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => setRun(emptyDeepRun()), []);

  const start = useCallback(
    async (symbols: string[], question: string, opts?: { include?: string[]; provider?: string }) => {
      abortRef.current?.abort();
      setRun(emptyDeepRun());
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      let latest = emptyDeepRun();
      try {
        const res = await fetch(`${VIBE_API_ORIGIN}/api/analysis/deep`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
          },
          body: JSON.stringify({
            symbols,
            question,
            include: opts?.include ?? ["quote", "technical", "options", "prediction"],
            provider: opts?.provider ?? null,
            stream: true,
          }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw new Error(`Deep analysis failed (${res.status})`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            for (const line of chunk.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              let ev: VibeEvent;
              try {
                ev = JSON.parse(line.slice(6));
              } catch {
                continue;
              }
              setRun((r) => {
                const next = applyDeepEvent(r, ev);
                latest = next;
                return next;
              });
            }
          }
        }
      } catch (err: any) {
        if (err?.name !== "AbortError") {
          latest = { ...latest, error: err?.message ?? "Stream error" };
          setRun(latest);
        }
      } finally {
        setStreaming(false);
      }
      return latest;
    },
    [],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  return { run, streaming, start, cancel, reset };
}

export type { VibeEvent };
export { stageMeasure };