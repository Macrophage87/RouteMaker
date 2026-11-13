/**
 * The barriers on a Cargo or Tandem route (core/barriers.py; backlog 2026-11-12 item 12, OWNER-DECISIONS 345). For a
 * cargo bike or tandem one barrier can end the trip, and the router knew of it while the rider did not. Two lines, only
 * on those two ride types (`BARRIER_PRESETS`):
 *
 * - a warning where the route still crosses a barrier they cannot pass (a stile, kissing gate, turnstile, steps or a
 *   gap mapped under 1.0 m) because no way round was found;
 * - a hint listing every barrier on the route otherwise ("On this route: gate, bollard ×2 (width not mapped)."), said
 *   only when there is one. A gap with no width mapped is said as unmapped, never as clear.
 *
 * The map marks each one on the route (the owner, 2026-11-12: "Make those noticeable on the map"): an octagon, a shape
 * no other route mark uses (hazards are circles, junctions triangles and diamonds, steep grades squares). Red with a
 * white bar (a no-entry sign) where a cargo bike or tandem cannot pass, amber with a dark "!" and rim for the others,
 * each a little larger than the other route marks, and named beside it ("stile") from zoom 13 for the red ones and 15
 * for the rest. Never the mark alone: the line says the same.
 *
 * Nothing is said where the answer has no barrier list (`data` false): silence must never read as "none mapped".
 * Plurals are written "×2" after the word, so no language needs a plural form of it.
 */
import type { BarrierItem, RouteResponse } from "./api.ts";
import { t } from "./i18n.ts";
import { LABEL_FONT } from "./railLayer.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

/** The ride types the barrier lines show on: Cargo and Tandem (core/barriers.py PRESETS). */
export const BARRIER_PRESETS: ReadonlySet<string> = new Set([
  "cargo",
  "tandem",
]);

type Word = BarrierItem["word"];

/** Each word as the rider reads it, in the order the list gives them: the impassable ones first. */
function label(word: Word): string {
  switch (word) {
    case "stile":
      return t("stile");
    case "kissing_gate":
      return t("kissing gate");
    case "turnstile":
      return t("turnstile");
    case "steps":
      return t("steps");
    case "narrow_gap":
      return t("narrow gap");
    case "bollard":
      return t("bollard");
    case "cycle_barrier":
      return t("cycle barrier");
    case "gate":
      return t("gate");
    default:
      return t("other barrier");
  }
}

const ORDER: readonly Word[] = [
  "stile",
  "kissing_gate",
  "turnstile",
  "steps",
  "narrow_gap",
  "cycle_barrier",
  "bollard",
  "gate",
  "other",
];

/** "gate, bollard ×2 (width not mapped)": each kind once, with its count past one; mapped and unmapped gaps apart. */
export function barrierList(
  items: readonly Pick<BarrierItem, "word" | "width_mapped">[],
): string {
  const groups = new Map<
    string,
    { word: Word; unmapped: boolean; n: number }
  >();
  for (const item of items) {
    const unmapped = item.width_mapped === false;
    const key = `${item.word}:${unmapped}`;
    const group = groups.get(key) ?? { word: item.word, unmapped, n: 0 };
    group.n += 1;
    groups.set(key, group);
  }
  return [...groups.values()]
    .sort(
      (a, b) =>
        ORDER.indexOf(a.word) - ORDER.indexOf(b.word) ||
        Number(a.unmapped) - Number(b.unmapped),
    )
    .map(
      (g) =>
        `${label(g.word)}${g.n > 1 ? ` ×${g.n}` : ""}${g.unmapped ? ` ${t("(width not mapped)")}` : ""}`,
    )
    .join(", ");
}

export interface BarrierNote {
  /** A warning (impassable barrier still on the route) or a hint (the list). */
  warn: boolean;
  text: string;
  short: string;
}

/** The line for a Cargo or Tandem route's barriers, or null where nothing is said. "No way round found" only where the
 * barrier round looked and found none (`barrier_round.limited` no_way_round); by one of the rider's own points where it
 * would not exclude one there (at_stop); else, as on a drawn or followed line or a round cut short, plainly. */
export function barrierNote(
  route:
    | Pick<RouteResponse, "preset" | "barriers" | "barrier_round">
    | null
    | undefined,
): BarrierNote | null {
  if (!route || !BARRIER_PRESETS.has(route.preset)) return null;
  const reading = route.barriers;
  if (!reading?.data || reading.items.length === 0) return null;
  const blocking = reading.items.filter((item) => item.impassable);
  if (blocking.length > 0) {
    const list = barrierList(blocking);
    const limited = route.barrier_round?.limited;
    const text =
      limited === "no_way_round"
        ? t(
            "No way round found: {list} on this route. A cargo bike or tandem may not get through.",
            { list },
          )
        : limited === "at_stop"
          ? t(
              "{list} by your start, a stop or the end. A cargo bike or tandem may not get through.",
              { list },
            )
          : t(
              "{list} on this route. A cargo bike or tandem may not get through.",
              { list },
            );
    return { warn: true, text, short: t("Barrier in the way.") };
  }
  return {
    warn: false,
    text: t("On this route: {list}.", { list: barrierList(reading.items) }),
    short: t("Barriers on this route."),
  };
}

// ---- The map marks ----

export const BARRIER_SOURCE = "route-barriers";
export const BARRIER_LAYER = "route-barrier-marks";
/** A little larger than the steep-grade squares (18 px), so a barrier stands out on the route. Our default. */
export const BARRIER_ICON_PX = 22;
export const BARRIER_LABEL_ZOOM = 13;
export const BARRIER_LABEL_ZOOM_OTHERS = 15;

/** Red with a white bar and rim (6.5:1) where a cargo bike or tandem cannot pass; amber with a dark "!" and rim (8.3:1)
 * for the rest, the dark rim keeping its outline on a light map (amber alone is under 3:1 there). */
export const BARRIER_COLOURS = {
  blocked: { fill: "#b91c1c", mark: "#ffffff", edge: "#ffffff" },
  noted: { fill: "#f59e0b", mark: "#111827", edge: "#111827" },
} as const;

export type BarrierLevel = keyof typeof BARRIER_COLOURS;

export function barrierIconName(level: BarrierLevel): string {
  return `barrier-${level}`;
}

export const BARRIER_LEVELS: readonly BarrierLevel[] = ["blocked", "noted"];

/** Inside a regular octagon of circumradius r, flat sides up and down, centred at (c, c). */
function inOctagon(x: number, y: number, c: number, r: number): boolean {
  const dx = Math.abs(x - c);
  const dy = Math.abs(y - c);
  const apothem = r * Math.cos(Math.PI / 8);
  return dx <= apothem && dy <= apothem && dx + dy <= apothem * Math.SQRT2;
}

/** The mark: an octagon with a rim; across it a bar for "can't pass" (a no-entry sign), an "!" for the rest, so the two
 * are told apart by shape as well as colour before their names show (the v0.26.0 release review, P3). */
export function barrierIcon(
  level: BarrierLevel,
  pixelRatio = 2,
  cssSize = BARRIER_ICON_PX,
): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const c = size / 2;
  const r = size / 2 - 0.5;
  const rim = 1.5 * pixelRatio;
  const fill: Rgb = hexToRgb(BARRIER_COLOURS[level].fill);
  const mark: Rgb = hexToRgb(BARRIER_COLOURS[level].mark);
  const edge: Rgb = hexToRgb(BARRIER_COLOURS[level].edge);
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    if (!inOctagon(x, y, c, r)) return null;
    if (!inOctagon(x, y, c, r - rim)) return edge;
    if (level === "blocked") {
      const inBar =
        Math.abs(y - c) <= 0.11 * size && Math.abs(x - c) <= 0.3 * size;
      return inBar ? mark : fill;
    }
    const inStroke =
      Math.abs(x - c) <= 0.075 * size && y >= 0.22 * size && y <= 0.58 * size;
    const inDot = Math.hypot(x - c, y - 0.73 * size) <= 0.085 * size;
    return inStroke || inDot ? mark : fill;
  });
}

/** The marks' layer, over the route line: one at each barrier, its name beside it as it is zoomed in. */
export function barrierLayer(): Record<string, unknown> {
  return {
    id: BARRIER_LAYER,
    type: "symbol",
    source: BARRIER_SOURCE,
    layout: {
      "icon-image": ["concat", "barrier-", ["get", "level"]],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-rotation-alignment": "viewport",
      // The red ones on top where two meet.
      "symbol-sort-key": ["case", ["==", ["get", "level"], "blocked"], 1, 0],
      "text-field": [
        "step",
        ["zoom"],
        "",
        BARRIER_LABEL_ZOOM,
        ["case", ["==", ["get", "level"], "blocked"], ["get", "label"], ""],
        BARRIER_LABEL_ZOOM_OTHERS,
        ["get", "label"],
      ],
      "text-font": [LABEL_FONT],
      "text-size": 13,
      "text-anchor": "left",
      "text-offset": [1.1, 0],
      "text-rotation-alignment": "viewport",
      "text-optional": true,
    },
    paint: {
      "text-color": "#111827",
      "text-halo-color": "#ffffff",
      "text-halo-width": 2,
    },
  };
}

type BarrierFeature = {
  type: "Feature";
  properties: { level: BarrierLevel; label: string };
  geometry: { type: "Point"; coordinates: [number, number] };
};

/** Each barrier on a Cargo or Tandem route as a point; empty on every other ride type, with none, or with no list. */
export function barrierFeatures(
  route: Pick<RouteResponse, "preset" | "barriers"> | null,
) {
  const features: BarrierFeature[] = [];
  const reading = route?.barriers;
  if (!route || !BARRIER_PRESETS.has(route.preset) || !reading?.data)
    return { type: "FeatureCollection" as const, features };
  for (const item of reading.items) {
    features.push({
      type: "Feature",
      properties: {
        level: item.impassable ? "blocked" : "noted",
        label: barrierList([item]),
      },
      geometry: { type: "Point", coordinates: [item.lon, item.lat] },
    });
  }
  return { type: "FeatureCollection" as const, features };
}
