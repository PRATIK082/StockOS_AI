export interface Candle {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

export function ema(values: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = [];
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (prev === null) {
      prev = values[i];
    } else {
      prev = values[i] * k + prev * (1 - k);
    }
    out.push(prev);
  }
  return out;
}

export function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 0; i < values.length; i++) {
    if (i === 0) {
      out.push(null);
      continue;
    }
    const delta = values[i] - values[i - 1];
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);
    if (i <= period) {
      avgGain += gain;
      avgLoss += loss;
      if (i === period) {
        avgGain /= period;
        avgLoss /= period;
      }
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
    }
    if (i < period) {
      out.push(null);
      continue;
    }
    if (avgLoss === 0) {
      out.push(avgGain === 0 ? 50 : 100);
    } else {
      const rs = avgGain / avgLoss;
      out.push(100 - 100 / (1 + rs));
    }
  }
  return out;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): { macd: (number | null)[]; signal: (number | null)[]; hist: (number | null)[] } {
  const eFast = ema(values, fast);
  const eSlow = ema(values, slow);
  const macdLine = eFast.map((f, i) => (f != null && eSlow[i] != null ? f - (eSlow[i] as number) : null));
  const signalLine = ema(macdLine.map((m) => m ?? 0), signal).map((v, i) => (macdLine[i] == null ? null : v));
  const hist = macdLine.map((m, i) => (m != null && signalLine[i] != null ? m - (signalLine[i] as number) : null));
  return { macd: macdLine, signal: signalLine, hist };
}

export interface SignalSnapshot {
  last_close: number | null;
  ema_9: number | null;
  ema_21: number | null;
  ema_50: number | null;
  rsi_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  trend: "bullish" | "bearish";
  support: number | null;
  resistance: number | null;
}

export function latestSignals(candles: Candle[]): SignalSnapshot {
  const closes = candles.map((c) => c.close);
  const last = (arr: (number | null)[]) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i] != null) return arr[i];
    }
    return null;
  };
  const e9 = last(ema(closes, 9));
  const e21 = last(ema(closes, 21));
  const e50 = last(ema(closes, 50));
  const r = last(rsi(closes));
  const m = macd(closes);
  const recent = candles.slice(-20);
  const highs = recent.map((c) => c.high).filter((h) => h != null);
  const lows = recent.map((c) => c.low).filter((l) => l != null);
  return {
    last_close: last(closes),
    ema_9: e9 != null ? Math.round(e9 * 100) / 100 : null,
    ema_21: e21 != null ? Math.round(e21 * 100) / 100 : null,
    ema_50: e50 != null ? Math.round(e50 * 100) / 100 : null,
    rsi_14: r != null ? Math.round(r * 100) / 100 : null,
    macd: last(m.macd) != null ? Math.round((last(m.macd) as number) * 100) / 100 : null,
    macd_signal: last(m.signal) != null ? Math.round((last(m.signal) as number) * 100) / 100 : null,
    trend: e9 != null && e21 != null && e9 > e21 ? "bullish" : "bearish",
    support: lows.length ? Math.min(...lows) : null,
    resistance: highs.length ? Math.max(...highs) : null,
  };
}