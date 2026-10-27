/**
 * Share as image (v0.7.0; the owner, 2026-10-16: "the plan has the intent to have a shareable map as an image in
 * standard social media resolutions with an optional QR code. Can that be enabled?"; and "Show an elevation profile,
 * optionally on the map."). A first, client-side version of PLAN.md's social share card: the page draws the card
 * itself (app/ShareCardDialog.tsx renders the map offscreen at the card's size), where PLAN has the worker render
 * and cache it. This module is the card's plain arithmetic and words, so node --test can hold them:
 *
 * - the four sizes PLAN names, Square the default;
 * - the layout: the map, the elevation profile in its own band below it (shown by default; "Draw it on the map"
 *   moves it to a see-through strip over the map's lower part), and the footer: the route's name if it has one,
 *   the distance and the climb (US first, metric in brackets), "RouteMaker", the QR code when asked for, and the
 *   OpenStreetMap and base map credits drawn into the image, legible at its size (PLAN: the image travels without
 *   the page's attribution);
 * - privacy: start, finish and stops only, with no place's name drawn; when the route starts, ends or stops at the
 *   rider's Home, nothing of the line and no pin is drawn within 0.2 mi (320 m) of it (a blank circle round it,
 *   moved off Home so its edge does not point at it; "Hide the part near Home", checked each time the dialog
 *   opens, can turn this off); a route that only passes Home is drawn whole, since a gap there would point at
 *   Home (the owner, 2026-10-16: "If it doesn't start, end, or stop at home keep showing the route. Also, make
 *   this an option, default to censor."); nothing is ever labelled Home;
 * - when the QR code can be had: it encodes the route's shared link (lib/sharedRoutes.ts), made as Share makes it.
 */
import type { RouteProfile } from "./api.ts";
import { t } from "./i18n.ts";
import { formatClimb, formatDistance, METRES_PER_MILE } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import type { Home } from "./myGo.ts";

// ---- Words ----------------------------------------------------------------------------------------

/** The button beside Share in Plan's More, and the dialog's heading. */
export const SHARE_IMAGE_LABEL = "Share as image";
export const SIZE_LABEL = "Size";
export const QR_LABEL = "QR code";
export const PROFILE_LABEL = "Elevation profile";
export const PROFILE_ON_MAP_LABEL = "Draw it on the map";
export const DOWNLOAD_LABEL = "Download";
export const SHARE_FILE_LABEL = "Share image";
export const CLOSE_LABEL = t("Close");
export const BRAND = "RouteMaker";

export const IMAGE_MAKING = "Making the image.";
export const IMAGE_READY = "Image ready.";
export const IMAGE_FAILED = "Could not make the image. Try again, or use Copy link.";
export const IMAGE_DOWNLOADED = "Image downloaded.";
export const IMAGE_SHARE_FAILED = "Could not open the share sheet. Use Download instead.";

export const QR_NEEDS_CONNECTION = "Needs a connection: the QR code opens the shared link, made online.";
export const QR_WAITS_FOR_ROUTE = "Available once the route has finished planning.";
export const QR_HOME_END = "Not available: this route starts, ends or stops at Home, and its link would show where.";
export const QR_LINK_FAILED = "Could not make the shared link, so the QR code is left out. Try again when online.";
export const PROFILE_ON_MAP_OFF = "Turn on Elevation profile to draw it on the map.";
export const PROFILE_NONE = "Not available: this route has no elevation data.";
export const HOME_TOO_SHORT = "This route is too short to draw without showing Home.";
/** The dialog's one Home choice, shown only when the route starts, ends or stops at Home; checked each time it opens. */
export const HIDE_HOME_LABEL = "Hide the part near Home";

// ---- Sizes ----------------------------------------------------------------------------------------

export type CardSizeId = "square" | "portrait" | "story" | "landscape";
export interface CardSize {
  id: CardSizeId;
  label: string;
  width: number;
  height: number;
}
/** PLAN.md's four: square, portrait, story, and landscape (the OpenGraph size). */
export const CARD_SIZES: readonly CardSize[] = [
  { id: "square", label: "Square, 1080 × 1080", width: 1080, height: 1080 },
  { id: "portrait", label: "Portrait, 1080 × 1350", width: 1080, height: 1350 },
  { id: "story", label: "Story, 1080 × 1920", width: 1080, height: 1920 },
  { id: "landscape", label: "Landscape, 1200 × 630", width: 1200, height: 630 },
];
export const CARD_SIZE_DEFAULT: CardSizeId = "square";

export function cardSize(id: CardSizeId): CardSize {
  return CARD_SIZES.find((s) => s.id === id) ?? CARD_SIZES[0];
}

// ---- Layout ---------------------------------------------------------------------------------------

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export type ProfilePlace = "off" | "band" | "map";

export interface CardLayout {
  width: number;
  height: number;
  /** The map, from the top. */
  map: Rect;
  /** The elevation profile: its band below the map, or a strip over the map's lower part; null when off. */
  profile: Rect | null;
  /** The footer, under the map (and the band). */
  footer: Rect;
  /** The QR code's square in the footer's right, with its white margin inside; null without one. */
  qr: Rect | null;
  /** Inside the footer, left of the QR code. */
  text: Rect;
  /** Pixel sizes of the footer's lines. */
  font: { name: number; stats: number; brand: number; credit: number; profile: number };
  pad: number;
}

/** The smallest the credits and the profile's labels are drawn, in image pixels, so they stay readable. */
export const MIN_SMALL_TEXT_PX = 18;
/** The smallest a QR code is drawn, margin included, so a phone camera reads it off another screen. */
export const MIN_QR_PX = 160;

/**
 * Where everything goes. Sizes scale with the card's shorter side (1080 at Square), the small text never below
 * MIN_SMALL_TEXT_PX and the QR code never below MIN_QR_PX.
 */
export function cardLayout(size: Pick<CardSize, "width" | "height">, opts: { name: boolean; qr: boolean; profile: ProfilePlace }): CardLayout {
  const { width, height } = size;
  const u = Math.min(width, height) / 1080;
  const r = (n: number) => Math.round(n);
  const pad = r(40 * u);
  const font = {
    name: r(52 * u),
    stats: r(40 * u),
    brand: r(34 * u),
    credit: Math.max(MIN_SMALL_TEXT_PX, r(22 * u)),
    profile: Math.max(MIN_SMALL_TEXT_PX, r(24 * u)),
  };
  const line = (px: number) => r(px * 1.3);
  const textH = (opts.name ? line(font.name) : 0) + line(font.stats) + line(font.brand) + line(font.credit) * 2;
  const qrSide = opts.qr ? Math.max(MIN_QR_PX, r(240 * u)) : 0;
  const footerH = Math.max(textH, qrSide) + pad * 2;
  const bandH = opts.profile === "band" ? Math.max(r(150 * u), font.profile * 4) : 0;
  const mapH = height - footerH - bandH;
  const map = { x: 0, y: 0, w: width, h: mapH };
  let profile: Rect | null = null;
  if (opts.profile === "band") profile = { x: 0, y: mapH, w: width, h: bandH };
  if (opts.profile === "map") {
    const stripH = Math.max(r(170 * u), font.profile * 4);
    profile = { x: pad, y: mapH - pad - stripH, w: width - pad * 2, h: stripH };
  }
  const footer = { x: 0, y: height - footerH, w: width, h: footerH };
  const qr = opts.qr ? { x: width - pad - qrSide, y: footer.y + pad, w: qrSide, h: qrSide } : null;
  const text = { x: pad, y: footer.y + pad, w: width - pad * 2 - (qr ? qrSide + pad : 0), h: footerH - pad * 2 };
  return { width, height, map, profile, footer, qr, text, font, pad };
}

// ---- Footer words ---------------------------------------------------------------------------------

/** "12.4 mi (20.0 km)", and "· 1,234 ft (376 m) climb" where the route has a climb. */
export function statsLine(distanceM: number, climbM: number | null | undefined): string {
  const climb = climbM != null && Number.isFinite(climbM) && climbM >= 1 ? ` · ${formatClimb(climbM)} climb` : "";
  return `${formatDistance(distanceM)}${climb}`;
}

/** "1600 Elm Street", "12 N Main St": a house number then, within a few words, a street word. */
const STREET_ADDRESS =
  /\b\d+[a-z]?\s+(?:[\w.'-]+\s+){0,4}(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|court|ct|place|pl|boulevard|blvd|way|terrace|ter|circle|cir|parkway|pkwy|highway|hwy|row|alley|square|sq)\b\.?/i;

/**
 * The name drawn, or null: an opened file's or saved route's own name, never a planned route's "<start> to <end>"
 * (made from place names, which can be Home or a saved place). A name holding the word Home, or Home's own label,
 * is left out too, and so is one that reads as a street address (a file named after where someone lives); a
 * name that only looks like one ("10 mi Beach Drive") is left out with them, on the safe side.
 */
export function cardName(name: string | null | undefined, home: Home | null): string | null {
  const n = (name ?? "").trim();
  if (!n) return null;
  if (/\bhome\b/i.test(n)) return null;
  if (STREET_ADDRESS.test(n)) return null;
  const label = home?.label.trim().toLowerCase();
  if (label && label.length >= 3 && n.toLowerCase().includes(label)) return null;
  return n.slice(0, 80);
}

/** Drawn into the image (PLAN: OpenStreetMap and the base map, legible); USGS 3DEP too when the profile is drawn. */
export function cardAttribution(profile: boolean): string {
  return ["Map: © OpenStreetMap contributors (ODbL)", "Protomaps", ...(profile ? ["Elevation: USGS 3DEP"] : [])].join(" · ");
}

/** The preview's text alternative: what the image shows, in the order it shows it. */
export function cardAlt(opts: {
  name: string | null;
  distanceM: number;
  climbM: number | null | undefined;
  stops: number;
  startShown: boolean;
  finishShown: boolean;
  profile: ProfileStrip | null;
  qr: boolean;
}): string {
  const parts = [`Route map${opts.name ? `, "${opts.name}"` : ""}, ${statsLine(opts.distanceM, opts.climbM).replace(" · ", ", ")}.`];
  const marks = [opts.startShown ? "start" : null, opts.stops > 0 ? `${opts.stops} ${opts.stops === 1 ? "stop" : "stops"}` : null, opts.finishShown ? "finish" : null].filter(Boolean);
  parts.push(marks.length ? `Marked: ${marks.join(", ")}.` : "No points marked.");
  if (opts.profile) parts.push(`Elevation profile from ${opts.profile.minLabel} to ${opts.profile.maxLabel}.`);
  if (opts.qr) parts.push("QR code to the shared link.");
  parts.push(`${BRAND}. ${cardAttribution(opts.profile !== null)}.`);
  return parts.join(" ");
}

// ---- Privacy: Home -------------------------------------------------------------------------------

/** No part of the line, and no pin, is drawn within this of Home: 0.2 mi. */
export const HOME_TRIM_M = 0.2 * METRES_PER_MILE;
/** The hidden circle's centre is moved this far from Home (and its radius grown by as much), so its edge does not point at Home. */
export const ZONE_SHIFT_MIN_M = 60;
export const ZONE_SHIFT_MAX_M = 150;
/** The hidden circle's radius, the same however far its centre moved, so the gap's size says nothing of the shift. */
export const ZONE_RADIUS_M = HOME_TRIM_M + ZONE_SHIFT_MAX_M + 1;

/** The circle the card leaves blank: around Home, moved, and large enough to hold everything within HOME_TRIM_M of it. */
export interface HomeZone {
  centre: LonLat;
  radiusM: number;
}

const M_PER_DEG = (6_371_008.8 * Math.PI) / 180;

/**
 * Home's hidden circle. A gap cut by an exact circle round Home would give Home away (three points on its edge
 * fix its centre), so the centre is moved `shift` metres in a direction, both from `jitter` (two numbers from 0 to
 * 1, kept per device so cards do not average it out), and the radius is ZONE_RADIUS_M whatever the shift, so every
 * point within HOME_TRIM_M of Home is still inside and the gap's size gives nothing away.
 */
export function homeZone(home: Home | null, jitter: readonly [number, number]): HomeZone | null {
  if (!home) return null;
  const shift = ZONE_SHIFT_MIN_M + Math.min(Math.max(jitter[1], 0), 1) * (ZONE_SHIFT_MAX_M - ZONE_SHIFT_MIN_M);
  const angle = jitter[0] * 2 * Math.PI;
  const [lon, lat] = home.point;
  const centre: LonLat = [lon + (Math.cos(angle) * shift) / (M_PER_DEG * Math.cos((lat * Math.PI) / 180)), lat + (Math.sin(angle) * shift) / M_PER_DEG];
  return { centre, radiusM: ZONE_RADIUS_M };
}

const inZone = (p: LonLat | undefined, zone: HomeZone | null) => !!p && !!zone && haversineM(p, zone.centre) <= zone.radiusM;

/**
 * Whether the route starts, ends or stops at Home: its line's ends, or any of `points`, inside Home's circle. Only
 * then is the circle cut out (cardRoute) and the QR code refused (qrAvailability), unless the rider unchecks "Hide
 * the part near Home" in the dialog to show it; a route that only passes by is
 * drawn whole, as if no Home were set, since a gap there would point at Home.
 */
export const homeEnd = (line: readonly LonLat[], points: readonly LonLat[], zone: HomeZone | null): boolean =>
  inZone(line[0], zone) || inZone(line[line.length - 1], zone) || points.some((p) => inZone(p, zone));

export interface CardRoute {
  /** The line to draw: one piece, or several where it passes through Home's circle. */
  pieces: LonLat[][];
  /** The parts of the route drawn, as shares of its length (0 to 1), so the profile is cut alike. */
  visible: [number, number][];
  start: LonLat | null;
  finish: LonLat | null;
  /** The stops between, none of them in Home's circle. */
  stops: LonLat[];
}

/** The shortest drawn line a card is made of: less would show little but where Home's circle is. */
export const MIN_DRAWN_M = HOME_TRIM_M / 2;

/**
 * What the card draws of the route: start, finish and stops only, no names, and, when it starts, ends or stops at
 * Home (homeEnd, `also` checked too), nothing inside Home's circle (homeZone): the line is cut where it enters and
 * leaves it, into separate pieces, and a pin inside it is not drawn. Otherwise, or with no circle (no Home, or
 * "Hide the part near Home" unchecked), the whole route. Null when what is left is under MIN_DRAWN_M (HOME_TOO_SHORT).
 */
export function cardRoute(
  line: readonly LonLat[],
  points: readonly LonLat[],
  homeCircle: HomeZone | null,
  also: readonly LonLat[] = [],
): CardRoute | null {
  if (line.length < 2) return null;
  const zone = homeEnd(line, [...points, ...also], homeCircle) ? homeCircle : null;
  // Metres east and north of the circle's centre: a segment is cut where it crosses the circle's edge.
  const [clon, clat] = zone?.centre ?? [0, 0];
  const kx = M_PER_DEG * Math.cos((clat * Math.PI) / 180);
  const xy = (p: LonLat) => [(p[0] - clon) * kx, (p[1] - clat) * M_PER_DEG] as const;
  const r2 = zone ? zone.radiusM ** 2 : -1;
  let total = 0;
  const parts: { a: LonLat; b: LonLat; from: number; to: number; out: boolean }[] = [];
  for (let i = 1; i < line.length; i += 1) {
    const a = line[i - 1];
    const b = line[i];
    const len = haversineM(a, b);
    const [ax, ay] = xy(a);
    const [bx, by] = xy(b);
    const dx = bx - ax;
    const dy = by - ay;
    const qa = dx * dx + dy * dy;
    const qb = 2 * (ax * dx + ay * dy);
    const qc = ax * ax + ay * ay - r2;
    const ts = [0, 1];
    const disc = qb * qb - 4 * qa * qc;
    if (zone && qa > 0 && disc > 0) {
      for (const t of [(-qb - Math.sqrt(disc)) / (2 * qa), (-qb + Math.sqrt(disc)) / (2 * qa)]) if (t > 0 && t < 1) ts.push(t);
    }
    ts.sort((x, y) => x - y);
    const at = (t: number): LonLat => (t === 0 ? a : t === 1 ? b : [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    for (let k = 1; k < ts.length; k += 1) {
      const mid = (ts[k - 1] + ts[k]) / 2;
      const mx = ax + dx * mid;
      const my = ay + dy * mid;
      parts.push({ a: at(ts[k - 1]), b: at(ts[k]), from: total + len * ts[k - 1], to: total + len * ts[k], out: !zone || mx * mx + my * my > r2 });
    }
    total += len;
  }
  const pieces: LonLat[][] = [];
  const visible: [number, number][] = [];
  let drawnM = 0;
  let piece: LonLat[] | null = null;
  for (const part of parts) {
    if (!part.out) {
      piece = null;
      continue;
    }
    drawnM += part.to - part.from;
    if (!piece) {
      piece = [part.a];
      pieces.push(piece);
      visible.push([part.from, part.to]);
    }
    piece.push(part.b);
    visible[visible.length - 1][1] = part.to;
  }
  if (pieces.length === 0 || drawnM < MIN_DRAWN_M) return null;
  const first = line[0];
  const last = line[line.length - 1];
  const hide = (p: LonLat | undefined) => inZone(p, zone);
  return {
    pieces,
    visible: visible.map(([f, t]) => [total > 0 ? f / total : 0, total > 0 ? t / total : 1]),
    start: hide(first) || hide(points[0]) ? null : first,
    finish: hide(last) || hide(points[points.length - 1]) ? null : last,
    stops: points.slice(1, -1).filter((p) => !hide(p)),
  };
}

// ---- The QR code ----------------------------------------------------------------------------------

export type QrAvailability = { ok: true } | { ok: false; why: string };

/**
 * Whether the QR code can be turned on. It opens the shared link, made as Share makes it (the exact line kept on
 * the server), so it needs a connection and a settled route. A route that starts, ends or stops at Home is refused:
 * the card hides Home, and the link's line and points would show it.
 */
export function qrAvailability(opts: { online: boolean; settled: boolean; homeEnd: boolean }): QrAvailability {
  if (opts.homeEnd) return { ok: false, why: QR_HOME_END };
  if (!opts.online) return { ok: false, why: QR_NEEDS_CONNECTION };
  if (!opts.settled) return { ok: false, why: QR_WAITS_FOR_ROUTE };
  return { ok: true };
}

/** The QR code's modules as a square of booleans, from any encoder with qrcode-generator's shape. */
export function qrModules(qr: { getModuleCount(): number; isDark(row: number, col: number): boolean }): boolean[][] {
  const n = qr.getModuleCount();
  return Array.from({ length: n }, (_, row) => Array.from({ length: n }, (_, col) => qr.isDark(row, col)));
}

/** The module size in whole pixels and the offset that centres the code, with the 4-module quiet zone inside `side`. */
export function qrFit(modules: number, side: number): { cell: number; offset: number } {
  const cell = Math.max(1, Math.floor(side / (modules + 8)));
  return { cell, offset: Math.floor((side - cell * modules) / 2) };
}

// ---- The elevation profile ------------------------------------------------------------------------

export interface ProfileStrip {
  /** The line's runs in image pixels; a gap in the data splits it. */
  runs: [number, number][][];
  minM: number;
  maxM: number;
  /** "120 ft (37 m)": the lowest and highest drawn. */
  minLabel: string;
  maxLabel: string;
}

/**
 * The route's elevation (the same samples the route's chart draws, RouteResponse.profile) scaled into `box`:
 * the drawn parts only (`visible`, shares of the route's length, as CardRoute has them: a gap where the line is
 * cut round Home), the lowest at the box's bottom and the highest at its top; a flat route sits in the middle.
 * Null with fewer than two samples.
 */
export function profileStrip(profile: RouteProfile, box: Rect, visible: readonly (readonly [number, number])[] = [[0, 1]]): ProfileStrip | null {
  const total = profile.m[profile.m.length - 1] ?? 0;
  if (!(total > 0) || visible.length === 0) return null;
  const ranges = visible.map(([f, t]) => [f * total, t * total] as const);
  const from = ranges[0][0];
  const to = ranges[ranges.length - 1][1];
  if (!(to > from)) return null;
  const samples: (readonly [number, number] | null)[] = [];
  for (let i = 0; i < profile.m.length; i += 1) {
    const m = profile.m[i];
    const e = profile.elevation_m[i];
    if (m < from || m > to) continue;
    const shown = ranges.some(([f, t]) => m >= f && m <= t);
    samples.push(!shown || e === null || !Number.isFinite(e) ? null : [m, e]);
  }
  const known = samples.filter((s): s is readonly [number, number] => s !== null);
  if (known.length < 2) return null;
  const minM = Math.min(...known.map((s) => s[1]));
  const maxM = Math.max(...known.map((s) => s[1]));
  const span = maxM - minM;
  const x = (m: number) => box.x + ((m - from) / (to - from)) * box.w;
  const y = (e: number) => (span < 1 ? box.y + box.h / 2 : box.y + box.h - ((e - minM) / span) * box.h);
  const runs: [number, number][][] = [];
  let run: [number, number][] = [];
  for (const s of samples) {
    if (s === null) {
      if (run.length > 1) runs.push(run);
      run = [];
    } else run.push([x(s[0]), y(s[1])]);
  }
  if (run.length > 1) runs.push(run);
  return { runs, minM, maxM, minLabel: formatClimb(minM), maxLabel: formatClimb(maxM) };
}

/** The file's name: "routemaker-square.png". */
export const cardFileName = (size: CardSizeId) => `routemaker-${size}.png`;
