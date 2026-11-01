/**
 * Open shared locations in RouteMaker (v0.7.0; the owner, 2026-10-14 16:23 UTC: "In some links that share a
 * location it's possible to open in Google maps, waze, etc. Can this app be added to the list?").
 *
 * Three ways in, all ending in one destination for Go:
 * - Android's Share sheet: the manifest's share_target opens "/?share_title=…&share_text=…&share_url=…".
 * - Desktop Chrome and Edge: the manifest's protocol_handlers open geo: links as "/?geo=geo:…".
 * - Typing or pasting into the search box (everywhere, iPhone too): a map link, coordinates or a plus code.
 *
 * What is read, from the link alone (no request), each as [lon, lat]:
 * - coordinates: "38.8893, -77.0502", "38.8893 -77.0502", "38.8893° N, 77.0502° W" (latitude first, as
 *   map apps copy them; "-77.0502, 38.8893" is read the other way round, as this region is north and west), and
 *   degrees, minutes and seconds: "38°53'21.4\"N 77°03'00.6\"W", "N 38° 53.357 W 077° 03.010" (Stephen,
 *   2026-10-31: "add locations by latitude and longitude in the search");
 * - plus codes (lib/plusCode.ts): "87C4VXQ7+GV", or "VXQ7+GV Washington" near the start or the map's view;
 * - geo: links (RFC 5870): "geo:38.8893,-77.0502", with "?q=lat,lon(Label)" or "?q=an address";
 * - Google Maps: the place's own "!3d…!4d…" first, then "?q=", "query=", "destination=", "daddr=", "ll=",
 *   "/dir/…/lat,lon", then the view's "@lat,lon"; the name from "/place/<name>/";
 *   consent.google.com's "continue=" link is read for the link inside it;
 * - Apple Maps: "coordinate=", "ll=", "daddr=", "sll=", "q=lat,lon"; the name from "name=" or "q=";
 * - Waze: "ll=", "to=ll.lat,lon", and "waze.com/ul/h<geohash>" links (decoded here).
 * Short links (maps.app.goo.gl, goo.gl/maps, maps.apple) carry only an id: the server follows them
 * (POST /api/share/resolve) and the full link is read as above.
 */
import type { LonLat } from "./geo.ts";
import type { Place } from "./geocode.ts";
import { parsePlusCode } from "./plusCode.ts";

/**
 * `typed`: the point was typed rather than read from a link: coordinates, or a plus code (its `name`); the place is
 * then named by what was typed (sharedPlace), not "Shared location".
 */
export type Shared =
  | { kind: "point"; point: LonLat; name?: string; typed?: "coordinates" | "pluscode" }
  | { kind: "short"; url: string; name?: string }
  | { kind: "query"; text: string };

// Decimals required: "12 34" is more likely a street number than a place.
const NUM = String.raw`[-+]?\d{1,3}\.\d+`;
const PAIR = new RegExp(String.raw`^\s*(${NUM})\s*[,\s]\s*(${NUM})\s*$`);
// One latitude or longitude in degrees, minutes and seconds, as map apps and GPS units write it: a hemisphere letter
// before or after, or a sign; "38°53'21.4\"N", "N 38° 53.357'", "38° 53.357 N", "-77.0502°", "38.8893 N".
const DEG = String.raw`(\d{1,3}(?:\.\d+)?)`;
const MIN_SEC = String.raw`(?:\s*(\d{1,2}(?:\.\d+)?)\s*['′’]?(?:\s*(\d{1,2}(?:\.\d+)?)\s*(?:["″”]|''|′′)?)?)?`;
const MARK = String.raw`(°|º|˚|deg\b)?`;
// Seven groups each: letter before, sign, degrees, degree mark, minutes, seconds, letter after.
const LETTER_FIRST = String.raw`([NSEW])\s*()${DEG}\s*${MARK}${MIN_SEC}()`;
const LETTER_LAST = String.raw`()([-+])?${DEG}\s*${MARK}${MIN_SEC}\s*([NSEW])?`;
const DMS = [LETTER_FIRST, LETTER_LAST].map((one) => new RegExp(String.raw`^\s*${one}(?:\s*[,;/]\s*|\s+|(?<=[^\d.\s]))${one}\s*$`, "i"));
const SHORT_HOSTS: Record<string, string> = { "maps.app.goo.gl": "/", "goo.gl": "/maps/", "maps.apple": "/" };

const valid = (lat: number, lon: number): boolean =>
  Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0);

/** "lat,lon" (or "lat lon") as [lon, lat]; a first number past 90 is a longitude, so the pair is read the other way. */
export function parseCoordinates(text: string): LonLat | null {
  const plain = PAIR.exec(text);
  if (plain) {
    let a = Number(plain[1]);
    let b = Number(plain[2]);
    // A first number that cannot be a latitude is a longitude; so is a negative first number before a positive
    // second, as this map's region is north of the equator and west of Greenwich.
    if ((Math.abs(a) > 90 && Math.abs(b) <= 90) || (a < 0 && b > 0)) [a, b] = [b, a];
    return valid(a, b) ? [b, a] : null;
  }
  for (const form of DMS) {
    const dms = form.exec(text);
    if (dms) return dmsPoint(dms.slice(1, 8), dms.slice(8, 15));
  }
  return null;
}

/**
 * One half of a degrees-minutes-seconds pair, as [value, axis]: the axis from its hemisphere letter ("lat" for N or
 * S), or null without one. Null when it is not a coordinate: no degree mark or letter, a sign and a letter both,
 * minutes without a degree mark, or minutes or seconds of 60 or more.
 */
function dmsHalf(part: string[]): { value: number; axis: "lat" | "lon" | null } | null {
  const [before, sign, deg, mark, min, sec, after] = part;
  if (before && after) return null;
  const hemi = (before || after || undefined)?.toUpperCase();
  if (!hemi && !mark) return null;
  if (hemi && sign) return null;
  if (min !== undefined && !mark && !hemi) return null;
  // A letter first with a bare whole number ("E 4 N 5") is more likely words than a place.
  if (before && !mark && min === undefined && !deg.includes(".")) return null;
  const m = min === undefined ? 0 : Number(min);
  const s = sec === undefined ? 0 : Number(sec);
  if (m >= 60 || s >= 60) return null;
  // Minutes with a fraction take no seconds; whole degrees are needed under minutes.
  if ((min !== undefined && deg.includes(".")) || (sec !== undefined && min!.includes("."))) return null;
  const negative = sign === "-" || hemi === "S" || hemi === "W";
  const value = (Number(deg) + m / 60 + s / 3600) * (negative ? -1 : 1);
  return { value, axis: hemi === undefined ? null : hemi === "N" || hemi === "S" ? "lat" : "lon" };
}

function dmsPoint(first: string[], second: string[]): LonLat | null {
  const a = dmsHalf(first);
  const b = dmsHalf(second);
  if (!a || !b) return null;
  if (a.axis !== null && a.axis === b.axis) return null;
  // Latitude first, as written, unless a letter says otherwise; with signs only, the region's rule (see the pair).
  let swap = a.axis === "lon" || b.axis === "lat";
  if (a.axis === null && b.axis === null) swap = (Math.abs(a.value) > 90 && Math.abs(b.value) <= 90) || (a.value < 0 && b.value > 0);
  const [lat, lon] = swap ? [b.value, a.value] : [a.value, b.value];
  return valid(lat, lon) ? [lon, lat] : null;
}

const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";

/** A geohash's cell centre as [lon, lat]; null if it is not one. */
export function decodeGeohash(hash: string): LonLat | null {
  if (!hash || hash.length > 12) return null;
  let lat: [number, number] = [-90, 90];
  let lon: [number, number] = [-180, 180];
  let even = true;
  for (const c of hash.toLowerCase()) {
    const v = BASE32.indexOf(c);
    if (v < 0) return null;
    for (let bit = 4; bit >= 0; bit -= 1) {
      const on = (v >> bit) & 1;
      const range = even ? lon : lat;
      const mid = (range[0] + range[1]) / 2;
      if (on) range[0] = mid;
      else range[1] = mid;
      even = !even;
    }
  }
  return [(lon[0] + lon[1]) / 2, (lat[0] + lat[1]) / 2];
}

const words = (text: string | null | undefined): string | undefined => {
  const t = (text ?? "").replace(/\+/g, " ").replace(/\s+/g, " ").trim();
  return t ? t.slice(0, 120) : undefined;
};

function decode(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/** A geo: link: its point (and label), or an address to search for. */
function parseGeo(uri: string): Shared | null {
  const m = /^geo:([^?]*)(?:\?(.*))?$/i.exec(uri.trim());
  if (!m) return null;
  const coords = m[1].split(";")[0];
  const q = new URLSearchParams(m[2] ?? "").get("q");
  if (q) {
    const labelled = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(q);
    const point = parseCoordinates(labelled ? labelled[1] : q);
    if (point) return { kind: "point", point, name: words(labelled?.[2]) };
  }
  const point = parseCoordinates(coords.replace(",", ", "));
  if (point) return { kind: "point", point };
  if (q) return { kind: "query", text: words(q) ?? "" };
  return null;
}

function fromParams(params: URLSearchParams, keys: readonly string[]): LonLat | null {
  for (const key of keys) {
    const value = params.get(key);
    if (!value) continue;
    const point = parseCoordinates(value.replace(/^ll\./, ""));
    if (point) return point;
  }
  return null;
}

function parseGoogle(url: URL): Shared | null {
  if (url.hostname === "consent.google.com") {
    const inner = url.searchParams.get("continue");
    return inner ? parseShared(inner) : null;
  }
  const path = decode(url.pathname);
  const name = words(/\/place\/([^/]+)/.exec(path)?.[1]);
  const place = /!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/.exec(url.href);
  if (place) {
    const point = parseCoordinates(`${place[1]},${place[2]}`);
    if (point) return { kind: "point", point, name };
  }
  const query = fromParams(url.searchParams, ["q", "query", "destination", "daddr", "ll", "center"]);
  if (query) return { kind: "point", point: query, name };
  // Directions: the last stop that is a pair of numbers.
  const dir = /\/dir\/(.*)$/.exec(path);
  if (dir) {
    const stops = dir[1].split("/").filter((s) => s && !s.startsWith("@") && !s.startsWith("data="));
    for (let i = stops.length - 1; i >= 0; i -= 1) {
      const point = parseCoordinates(stops[i]);
      if (point) return { kind: "point", point };
    }
  }
  const at = /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/.exec(path);
  if (at) {
    const point = parseCoordinates(`${at[1]},${at[2]}`);
    if (point) return { kind: "point", point, name };
  }
  const q = url.searchParams.get("q") ?? url.searchParams.get("query");
  if (q) return { kind: "query", text: words(q) ?? "" };
  if (name) return { kind: "query", text: name };
  return null;
}

function parseApple(url: URL): Shared | null {
  const p = url.searchParams;
  const name = words(p.get("name") ?? undefined) ?? (parseCoordinates(p.get("q") ?? "") ? undefined : words(p.get("q")));
  const point = fromParams(p, ["coordinate", "ll", "daddr", "q", "sll"]);
  if (point) return { kind: "point", point, name };
  const text = p.get("address") ?? p.get("q") ?? p.get("daddr");
  return text ? { kind: "query", text: words(text) ?? "" } : null;
}

function parseWaze(url: URL): Shared | null {
  const hash = /^\/ul\/h([0-9a-z]+)$/i.exec(url.pathname);
  if (hash) {
    const point = decodeGeohash(hash[1]);
    if (point) return { kind: "point", point };
  }
  const point = fromParams(url.searchParams, ["ll", "to", "latlng"]);
  if (point) return { kind: "point", point };
  const q = url.searchParams.get("q");
  return q ? { kind: "query", text: words(q) ?? "" } : null;
}

const isShort = (url: URL): boolean => {
  const prefix = SHORT_HOSTS[url.hostname];
  return url.protocol === "https:" && prefix !== undefined && url.pathname.startsWith(prefix) && url.pathname.length > prefix.length;
};

/**
 * One link, a pair of coordinates or a plus code, read for a place; null if it holds none RouteMaker can read.
 * `near`: where a short plus code ("VXQ7+GV") is looked for (lib/plusCode.ts); the middle of the map without it.
 */
export function parseShared(input: string, near?: LonLat): Shared | null {
  const text = input.trim();
  if (!text) return null;
  const point = parseCoordinates(text);
  if (point) return { kind: "point", point, typed: "coordinates" };
  const plus = parsePlusCode(text, near);
  if (plus) return { kind: "point", point: plus.point, name: plus.code, typed: "pluscode" };
  if (/^geo:/i.test(text)) return parseGeo(text);
  // A shared text: words and a link ("Lincoln Memorial https://maps.app.goo.gl/…"); the link is read.
  const link = /\b(?:https?:\/\/|geo:)\S+/i.exec(text);
  if (!link) return null;
  const before = words(text.slice(0, link.index).replace(/[\s:,-]+$/, ""));
  if (/^geo:/i.test(link[0])) return withName(parseGeo(link[0]), before);
  let url: URL;
  try {
    url = new URL(link[0]);
  } catch {
    return null;
  }
  if (isShort(url)) return { kind: "short", url: url.href, name: before };
  const host = url.hostname.replace(/^www\./, "");
  let found: Shared | null = null;
  if (host === "consent.google.com" || ((host === "google.com" || host === "maps.google.com" || /^google\.[a-z.]+$/.test(host)) && (host === "maps.google.com" || url.pathname.startsWith("/maps")))) {
    found = parseGoogle(url);
  } else if (host === "maps.apple.com") found = parseApple(url);
  else if (host === "waze.com" || host === "ul.waze.com") found = parseWaze(url);
  return withName(found, before);
}

function withName(found: Shared | null, name: string | undefined): Shared | null {
  if (!found || !name || found.kind === "query" || found.name) return found;
  return { ...found, name };
}

/** What a share to RouteMaker opened with (the share_target's and geo: handler's parameters); null if none. */
export function launchShare(search: string): string | null {
  const params = new URLSearchParams(search);
  const geo = params.get("geo");
  if (geo) return geo;
  const parts = ["share_title", "share_text", "share_url"].map((k) => params.get(k)?.trim()).filter(Boolean) as string[];
  return parts.length ? [...new Set(parts)].join(" ") : null;
}

/** The address bar without the share's parameters (so a reload does not open it again). */
export function withoutShare(href: string): string {
  const url = new URL(href);
  for (const key of ["geo", "share_title", "share_text", "share_url"]) url.searchParams.delete(key);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * A shared or typed point as the search's place, its coordinates as its label: typed coordinates are named by
 * themselves, a plus code by the code, a link's point by the name the share gave it, else "Shared location".
 */
export function sharedPlace(point: LonLat, name?: string, typed?: "coordinates" | "pluscode"): Place {
  const label = `${point[1].toFixed(5)}, ${point[0].toFixed(5)}`;
  if (typed === "coordinates") return { name: label, label, lon: point[0], lat: point[1], kind: "coordinates" };
  if (typed === "pluscode") return { name: name ?? label, label, lon: point[0], lat: point[1], kind: "pluscode" };
  return { name: name ?? "Shared location", label, lon: point[0], lat: point[1], kind: "shared" };
}

export const SHARED_OPENING = "Opening the shared link…";
export const SHARED_UNREADABLE = "That link has no place RouteMaker can read. Type the place instead.";
export const SHARED_FAILED = "That link could not be opened just now; try again shortly.";

type FetchLike = (url: string, init: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }>;

/** A short link followed by the server, then read; null when it could not be followed or read. */
export async function resolveShort(url: string, fetchImpl: FetchLike = (u, init) => fetch(u, init)): Promise<Shared | null> {
  try {
    const response = await fetchImpl("/api/share/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { url?: unknown };
    if (typeof body?.url !== "string") return null;
    const found = parseShared(body.url);
    return found && found.kind !== "short" ? found : null;
  } catch {
    return null;
  }
}

/** A share or a paste, read to the end: the place, an address to search for, or why not. */
export async function readShared(
  text: string,
  fetchImpl?: FetchLike,
  near?: LonLat,
): Promise<{ place: Place } | { query: string } | { error: string }> {
  let found = parseShared(text, near);
  if (found?.kind === "short") {
    const name = found.name;
    found = await resolveShort(found.url, fetchImpl);
    if (!found) return { error: SHARED_FAILED };
    found = withName(found, name);
  }
  if (!found) return { error: SHARED_UNREADABLE };
  if (found.kind === "query") return found.text ? { query: found.text } : { error: SHARED_UNREADABLE };
  if (found.kind === "point") return { place: sharedPlace(found.point, found.name, found.typed) };
  return { error: SHARED_UNREADABLE };
}
