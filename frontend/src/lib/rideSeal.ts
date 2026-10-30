/**
 * End-to-end encryption of a ride's live data (Stephen 2026-10-29, asked "Would E2E encryption be hard/worth it?",
 * then "yes"): every ride the phone takes part in (Share ride, Broadcast, Roam's Broadcast, a Group or Mass Ride) is
 * sealed. Each phone seals its dot, its alerts and the leader's path before sending, and the server only holds the
 * sealed text for its 2 minutes (core.ride_presence, "sealed").
 *
 * - The ride's secret is 16 random bytes (128 bits), 22 base64url characters in the link's fragment (`k=`), which a
 *   browser never sends to any server (2026-10-29, shorter ride links; it was 32 bytes, 43 characters, and an older
 *   link's 43-character secret still opens its ride). The server learns neither the secret nor the key: it sees only
 *   the ride id, derived from the secret one way (HKDF, whose input may be of any length, so both sizes derive as
 *   before: the same 64-hex-digit ride id and AES-256 key, by the same labels).
 * - The key is AES-GCM 256 from the same secret (HKDF, another label), the browser's own Web Crypto. Each sealed text
 *   is a fresh 12-byte nonce and the ciphertext; what it is (a dot, a path, an alert) and the ride id are bound in as
 *   associated data, so one cannot be passed off as another, or on another ride.
 * - Positions are sealed as the phone has them (Stephen 2026-10-29: "Encrypted rides send GPS accurate numbers."), to
 *   6 decimals (about 0.1 m); one outside the map's area is not sent. Alerts that the server merged ("2 riders
 *   reported") are merged by each phone as it reads them (`mergeAlerts`, the same rule).
 * - Every ride has a secret (Stephen 2026-10-29: "All rides should have a key."): a ride link opened without one (an
 *   older link) becomes a new ride of the one who opened it, with a secret of its own. Nothing goes in plain numbers.
 */
import { insideCoverage, type LonLat } from "./geo.ts";
import { b64url, fromB64url } from "./linkCode.ts";

/** The link's fragment parameter that carries the ride's secret. */
export const SECRET_PARAM = "k";
/** A new secret's bytes: 128 bits, 22 characters. */
export const SECRET_BYTES = 16;
/** An older link's secret: 32 bytes, 43 characters, read for ever. */
const OLD_SECRET_BYTES = 32;
const SECRET_RE = /^(?:[A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43})$/;
const NONCE_BYTES = 12;
const enc = new TextEncoder();

export type SealedKind = "dot" | "path" | "alert";

/** A ride sealed end to end: the id the server knows it by, and the key only the link's holders have. */
export interface RideSeal {
  ride: string;
  key: CryptoKey;
}

/** A new ride's secret: 16 bytes from the browser's random source, 22 characters. */
export function newRideSecret(): string {
  const bytes = new Uint8Array(SECRET_BYTES);
  crypto.getRandomValues(bytes);
  return b64url(bytes);
}

export function isRideSecret(value: unknown): value is string {
  return typeof value === "string" && SECRET_RE.test(value);
}

/** The secret a link's fragment carries, or null (never read from the query: that reaches the server). */
export function secretFrom(hash: string): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get(SECRET_PARAM);
  return isRideSecret(value) ? value : null;
}

/** The link with its ride's secret in the fragment (replacing any it had); null leaves the link as it is. */
export function withSecret(link: string, secret: string | null): string {
  return secret ? replaceSecret(link, secret) : link;
}

/** The link with no secret: a ride link that went out without its own leaves no other ride's secret in it. */
export function withoutSecret(link: string): string {
  return replaceSecret(link, null);
}

function replaceSecret(link: string, secret: string | null): string {
  const at = link.indexOf("#");
  if (at < 0 && !secret) return link;
  const base = at < 0 ? link : link.slice(0, at);
  const params = (at < 0 ? "" : link.slice(at + 1)).split("&").filter((p) => p && !p.startsWith(`${SECRET_PARAM}=`));
  if (secret) params.push(`${SECRET_PARAM}=${secret}`);
  return `${base}#${params.join("&")}`;
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The ride id (64 hex digits, as core.ride_presence.RIDE_ID) and key, both from the secret; null for a bad secret. */
export async function rideSeal(secret: string): Promise<RideSeal | null> {
  const raw = isRideSecret(secret) ? fromB64url(secret) : null;
  // Either size: a new 16-byte secret, or an older link's 32 bytes (HKDF takes input keying material of any length).
  if (!raw || (raw.length !== SECRET_BYTES && raw.length !== OLD_SECRET_BYTES)) return null;
  const base = await crypto.subtle.importKey("raw", raw, "HKDF", false, ["deriveBits", "deriveKey"]);
  const salt = enc.encode("routemaker ride seal v1");
  const ride = hex(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info: enc.encode("ride id") }, base, 256));
  const key = await crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt, info: enc.encode("ride key") },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  return { ride, key };
}

const aad = (seal: RideSeal, kind: SealedKind) => enc.encode(`${kind}|${seal.ride}`);

/**
 * Each kind is padded with spaces (which JSON ignores) to a whole number of these bytes before sealing, so the sealed
 * text's length does not tell the server a dot's role, an alert's kind or how long its words are.
 */
export const PAD_BYTES: Record<SealedKind, number> = { dot: 128, alert: 512, path: 4096 };

export function padded(kind: SealedKind, value: unknown): Uint8Array<ArrayBuffer> {
  const json = enc.encode(JSON.stringify(value));
  const size = Math.max(1, Math.ceil(json.length / PAD_BYTES[kind])) * PAD_BYTES[kind];
  const out = new Uint8Array(size).fill(0x20);
  out.set(json);
  return out;
}

/** The value as sealed text: base64url of the nonce and the ciphertext. */
export async function sealValue(seal: RideSeal, kind: SealedKind, value: unknown): Promise<string> {
  const iv = new Uint8Array(NONCE_BYTES);
  crypto.getRandomValues(iv);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(seal, kind) }, seal.key, padded(kind, value)));
  const out = new Uint8Array(iv.length + ct.length);
  out.set(iv);
  out.set(ct, iv.length);
  return b64url(out);
}

/** The value a sealed text holds, or null when it is not one this ride's key sealed as this kind. */
export async function openValue(seal: RideSeal, kind: SealedKind, text: unknown): Promise<unknown> {
  const bytes = typeof text === "string" ? fromB64url(text) : null;
  if (!bytes || bytes.length <= NONCE_BYTES) return null;
  try {
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes.slice(0, NONCE_BYTES), additionalData: aad(seal, kind) },
      seal.key,
      bytes.slice(NONCE_BYTES),
    );
    return JSON.parse(new TextDecoder().decode(plain)) as unknown;
  } catch {
    return null;
  }
}

// ---- what the server checked on plain numbers, checked before sealing ---------------------------------

/** A position to 6 decimals (about 0.1 m): the phone's own reading, kept short so each kind stays in its padding. */
export function sealedSpot([lon, lat]: LonLat): LonLat {
  return [Math.round(lon * 1e6) / 1e6, Math.round(lat * 1e6) / 1e6];
}

/** A position fit to send: a finite one inside the map's area, to 6 decimals; else null (the server refused those). */
export function sendable(p: LonLat): LonLat | null {
  return Number.isFinite(p[0]) && Number.isFinite(p[1]) && insideCoverage(p) ? sealedSpot(p) : null;
}

/** A line as the server kept it (core.ride_presence._line): its points inside the area, to 6 decimals, no repeats. */
export function sendableLine(line: readonly LonLat[]): LonLat[] {
  const out: LonLat[] = [];
  for (const p of line) {
    const q = sendable(p);
    if (!q) continue;
    const last = out[out.length - 1];
    if (!last || last[0] !== q[0] || last[1] !== q[1]) out.push(q);
  }
  return out;
}

// ---- alerts, merged by the phone as the server merged plain ones ----------------------------------------

/** core.ride_presence.MERGE_WITHIN_S and MERGE_WITHIN_M. */
export const MERGE_WITHIN_S = 120;
export const MERGE_WITHIN_M = 200;

export interface OpenedAlert {
  id: string;
  kind: string;
  text: string;
  lon: number;
  lat: number;
  age_s: number;
  mine: boolean;
}

function metres(a: { lon: number; lat: number }, b: { lon: number; lat: number }): number {
  const kx = 111_195 * Math.cos((((a.lat + b.lat) / 2) * Math.PI) / 180);
  return Math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * 111_195);
}

/**
 * The same issue near the same spot within 2 minutes is one alert, "2 riders reported" (core.ride_presence.send_alert):
 * oldest first, each joins the first earlier one of its kind (and words, for Other) within MERGE_WITHIN_M of its spot,
 * sent at most MERGE_WITHIN_S after that one's latest report. One's own alerts stay apart, so Clear clears only them.
 */
export function mergeAlerts(alerts: readonly OpenedAlert[]): (OpenedAlert & { count: number })[] {
  const groups: (OpenedAlert & { count: number })[] = [];
  for (const a of [...alerts].sort((x, y) => y.age_s - x.age_s)) {
    const into = a.mine
      ? undefined
      : groups.find(
          (g) =>
            !g.mine &&
            g.kind === a.kind &&
            (a.kind !== "other" || g.text === a.text) &&
            g.age_s - a.age_s <= MERGE_WITHIN_S &&
            metres(g, a) <= MERGE_WITHIN_M,
        );
    if (into) {
      into.count += 1;
      into.age_s = Math.min(into.age_s, a.age_s);
    } else groups.push({ ...a, count: 1 });
  }
  return groups;
}
