// Inline TOTP (RFC 6238, SHA-1, 30s steps). No new dependencies.
import { createHmac } from "crypto";

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.replace(/=+$/, "").toUpperCase();
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const ch of clean) {
    const idx = alphabet.indexOf(ch);
    if (idx < 0) throw new Error("Invalid base32 secret");
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((value >>> bits) & 0xff);
    }
  }
  return Buffer.from(bytes);
}

/** TOTP code for `secret` at `atMs` (default: now). */
export function totpCode(secret: string, atMs: number = Date.now()): string {
  const counter = Math.floor(atMs / 1000 / 30);
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", base32Decode(secret)).update(msg).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code =
    ((hmac[offset] & 0x7f) << 24) |
    (hmac[offset + 1] << 16) |
    (hmac[offset + 2] << 8) |
    hmac[offset + 3];
  return String(code % 1_000_000).padStart(6, "0");
}

/**
 * Candidate codes covering clock skew: current first, then prev/next 30s step.
 * Backend verifies with valid_window=1, so any of these is accepted.
 */
export function totpCandidates(secret: string, atMs: number = Date.now()): string[] {
  const codes = [
    totpCode(secret, atMs),
    totpCode(secret, atMs - 30_000),
    totpCode(secret, atMs + 30_000),
  ];
  return [...new Set(codes)];
}
