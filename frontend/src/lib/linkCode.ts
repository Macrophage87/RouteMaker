/**
 * The short forms a link's fragment carries (Stephen 2026-10-29, "yes" to shorter ride links): the stops as one
 * run of link-safe characters, and the leader mark and the ride's secret as base64url. Every character here is one
 * URLSearchParams leaves as it is (A-Z a-z 0-9 - _), so nothing is escaped on the way into a link.
 *
 * - Stops (`q=`): each point's longitude then latitude to 5 decimals (about 1 m, as the older `p=` wrote them), as
 *   whole numbers of 1e-5 degrees; the first point as it is, each after as the change from the one before. Each
 *   number is zigzagged (0, -1, 1, -2 ... to 0, 1, 2, 3 ...) and written 5 bits at a time, lowest first, each 5 bits
 *   with a sixth that says another follows, as one base64url character: the encoded-polyline scheme with the link's
 *   own alphabet. Two stops in the DC area are about 16 characters, against about 50 for `p=`.
 * - The leader mark (`lead=`): the 16 bytes of the leader key (32 hex digits, lib/rideGroup.ts leaderKey) as 22
 *   base64url characters. The page and the server keep the 32 hex digits; only the link has the short form.
 */
import type { LonLat } from "./geo.ts";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const VALUE = new Map([...ALPHABET].map((c, i) => [c, i]));

export function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function fromB64url(text: string): Uint8Array<ArrayBuffer> | null {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) return null;
  try {
    const s = atob(text.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (text.length % 4)) % 4));
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i += 1) out[i] = s.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

/** A coordinate as whole 1e-5 degrees, rounded as `toFixed(5)` rounds it (the older `p=`), so both forms agree. */
function units(value: number): number {
  return Math.round(Number(value.toFixed(5)) * 1e5);
}

function writeNumber(n: number, out: string[]): void {
  let z = n < 0 ? -2 * n - 1 : 2 * n;
  while (z >= 32) {
    out.push(ALPHABET[32 + (z % 32)]);
    z = Math.floor(z / 32);
  }
  out.push(ALPHABET[z]);
}

/** The points in `q=`'s form; "" for none. */
export function encodePoints(points: readonly LonLat[]): string {
  const out: string[] = [];
  let lon = 0;
  let lat = 0;
  for (const [x, y] of points) {
    const ux = units(x);
    const uy = units(y);
    writeNumber(ux - lon, out);
    writeNumber(uy - lat, out);
    lon = ux;
    lat = uy;
  }
  return out.join("");
}

/**
 * The points a `q=` value holds, to 5 decimals; up to the first character that is not one of the form's (or a
 * number left unfinished), so a link cut short opens with the points it still has whole.
 */
export function decodePoints(text: string): LonLat[] {
  const numbers: number[] = [];
  let z = 0;
  let scale = 1;
  for (const c of text) {
    const v = VALUE.get(c);
    if (v === undefined) break;
    z += (v % 32) * scale;
    scale *= 32;
    // More than 53 bits is no coordinate: stop there.
    if (scale > 2 ** 53) break;
    if (v >= 32) continue;
    numbers.push(z % 2 === 1 ? -(z + 1) / 2 : z / 2);
    z = 0;
    scale = 1;
  }
  const points: LonLat[] = [];
  let lon = 0;
  let lat = 0;
  for (let i = 0; i + 1 < numbers.length; i += 2) {
    lon += numbers[i];
    lat += numbers[i + 1];
    points.push([lon / 1e5, lat / 1e5]);
  }
  return points;
}

const HEX32 = /^[0-9a-f]{32}$/;
const MARK22 = /^[A-Za-z0-9_-]{22}$/;

/** The leader key (32 hex digits) as the link writes it, 22 base64url characters; null for anything else. */
export function leadMark(key: string | null | undefined): string | null {
  if (!key || !HEX32.test(key)) return null;
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 16; i += 1) bytes[i] = parseInt(key.slice(i * 2, i * 2 + 2), 16);
  return b64url(bytes);
}

/**
 * The leader key (32 hex digits) a link's `lead=` names: the 22-character form, or the 32 hex digits an older link
 * wrote; null for anything else.
 */
export function leadKeyOfMark(mark: string | null | undefined): string | null {
  if (!mark) return null;
  if (HEX32.test(mark)) return mark;
  if (!MARK22.test(mark)) return null;
  const bytes = fromB64url(mark);
  if (!bytes || bytes.length !== 16) return null;
  const key = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  // One form per key: a mark whose last character carries stray bits names no leader.
  return b64url(bytes) === mark ? key : null;
}
