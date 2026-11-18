/**
 * The Intervals map layer. The owner, 2026-11-16: "I'd want a layer that could identify interval-capable segments.
 * Basically we're looking for long segments that have limited turns, no intersections, and are either flat or
 * uphill. We'd have this in the Plan panel and available for the MCP."
 *
 * One switch in Plan's Trails and terrain section, beside Climbs, off by default and kept on this device; not in Go. The stretches are found once
 * per map build (`manage.py build_intervals`, src/pipeline/interval_layer.py: what counts is there) and shipped as
 * interval-data/intervals.json, fetched the first time the layer is turned on. Each is drawn as a wide pink
 * highlight under the stress line (the stress colour stays on top), with arrows along it where it holds one way
 * only (flat or uphill that way). Nothing here changes a route. Written with createElement
 * so a test renders it.
 */
import { createElement as h, type ReactElement } from "react";
import { t } from "./i18n.ts";
import { withDarkPaint } from "./darkPaint.ts";
import { METRES_PER_MILE } from "./format.ts";

/*
 * The layer's words are in English and Spanish only, as Plan is (i18n.ts planStaysEnglish; the v0.27.3 review found them
 * English on a Spanish page). Each English is kept in a constant not exported, as lib/terrainSection.ts does its Plan
 * title, so the Go and Ride catalogs' check (Sheets.tsx imports this module) does not ask the other 18 languages for it.
 */
const LABEL = "Interval stretches";
const HINT = "3 minutes or more with no stops, busy crossings or sharp turns, flat or uphill.";
const MINUTES_LABEL = "Show intervals from";
const UNAVAILABLE = "Interval stretches are unavailable for now.";
const NONE = "No interval stretches yet: they arrive with the next map data update.";
const LEGEND_TEXT = "Pink glow: an interval stretch, deeper for longer efforts. Arrows: ride it that way only (the other way goes downhill).";
const LEGEND_NAME = "Interval stretches legend";
const BAND = "{from} to {to} min";
const BAND_LAST = "{from} min or more";

export const INTERVALS_LABEL = t(LABEL);
/** Read on every focus, so one short line. */
export const INTERVALS_HINT = t(HINT);
/**
 * The owner, 2026-11-17: "filter by time, essentially a 3', 5', 8', etc interval stretch ... 3 minutes is the minimum".
 * Minutes at 18 mph on the flat, slowed on a climb (the file's `t`; src/pipeline/interval_layer.py).
 */
export const INTERVALS_MINUTES_LABEL = t(MINUTES_LABEL);
// 20: the owner, 2026-11-17, "go up to 20, thats a common interval".
export const INTERVALS_MINUTES_OPTIONS = [3, 5, 8, 12, 20] as const;
export type IntervalsMinutes = (typeof INTERVALS_MINUTES_OPTIONS)[number];
export const INTERVALS_MINUTES_KEY = "routemaker.intervalsMinutes";
/** The build's pace and climb slowing, for a file written before it carried `t`. */
const PACE_MPH = 18;
const CLIMB_SLOWING = 0.12;
export const INTERVALS_UNAVAILABLE = t(UNAVAILABLE);
/** The file ships empty until the build host fills it (interval-data/README.md). */
export const INTERVALS_NONE = t(NONE);
export const INTERVALS_PREF_KEY = "routemaker.intervalsLayer";

/** Deep pink: not a stress colour, not the Scenic teal, the rails' violet nor the route's blue. 6:1 on white. */
/** Drawn at this opacity: at least 3:1 on white, the land colour and the dark map as drawn (WCAG 1.4.11; v0.27.2 review). */
export const INTERVALS_OPACITY = 0.7;
export const INTERVALS_COLOUR = "#be185d";
export const INTERVALS_DARK_COLOUR = "#f472b6";
/**
 * Shaded by how long a stretch takes (the owner, 2026-11-18: "color code by time length of the intervals"): pink for
 * the shortest, deepening through magenta to plum for the longest, never toward maroon or red, so no shade reads as a
 * stress colour (each stays clear of every stress style's colours, intervals.test.tsx). A band starts at its
 * minutes (the picker's own steps). Every shade keeps 3:1 against the map at the drawn opacity (WCAG 1.4.11). On the
 * dark map "deep" is brighter (lib/darkPaint.ts holds the same ramp).
 */
export const INTERVALS_BANDS = [3, 5, 8, 12, 20] as const;
export const INTERVALS_RAMP = [INTERVALS_COLOUR, "#b0157a", "#9c1477", "#7a1a80", "#601466"] as const;
export const INTERVALS_DARK_RAMP = [INTERVALS_DARK_COLOUR, "#e879f9", "#f0abfc", "#f5c2fd", "#fad5ff"] as const;

/** A step expression on a stretch's minutes (`t`): the first shade below 5 minutes, the last from 20. */
export function intervalsColour(ramp: readonly string[]): unknown[] {
  const out: unknown[] = ["step", ["to-number", ["get", "t"], 0], ramp[0]];
  INTERVALS_BANDS.slice(1).forEach((m, i) => out.push(m, ramp[i + 1]));
  return out;
}

/** "3 to 5 min" ... "20 min or more": the key's words for each band. */
export function intervalsBandLabel(i: number): string {
  const from = INTERVALS_BANDS[i];
  const to = INTERVALS_BANDS[i + 1];
  return to === undefined ? t(BAND_LAST, { from }) : t(BAND, { from, to });
}
export const INTERVALS_SOURCE = "intervals";
export const INTERVALS_LINE_LAYER = "intervals-line";
export const INTERVALS_ARROW_LAYER = "intervals-arrows";
export const INTERVALS_LAYERS = [INTERVALS_LINE_LAYER, INTERVALS_ARROW_LAYER] as const;
export const INTERVALS_MIN_ZOOM = 9;
/** The base map's glyphs include this face (scripts/fetch_basemap.sh), as the climbs' labels use. */
const FONT = "Noto Sans Medium";

export interface IntervalStretch {
  id: string;
  lengthM: number;
  riseM: number;
  gradePct: number;
  line: [number, number][];
  bothWays: boolean;
  name: string | null;
  surface: "road" | "path" | "gravel";
  busy: boolean;
  /** Minutes to ride it at the build's pace (the quicker way where it holds both). */
  minutes: number;
  /** Bollards or blocks it passes, ridden through (the file's `k`). */
  bollards: number;
}

function effortMinutes(lengthM: number, riseM: number, bothWays: boolean): number {
  const grade = bothWays ? 0 : Math.max(0, (riseM / lengthM) * 100);
  return (lengthM / METRES_PER_MILE / (PACE_MPH / (1 + CLIMB_SLOWING * grade))) * 60;
}

export type IntervalsStatus = "loading" | "ready" | "empty" | "unavailable";

/** The file's stretches; null where it is not the file's shape. An entry without a line is left out. */
export function parseIntervals(doc: unknown): IntervalStretch[] | null {
  if (!doc || typeof doc !== "object") return null;
  const { version, intervals } = doc as { version?: unknown; intervals?: unknown };
  if (version !== 1 || !Array.isArray(intervals)) return null;
  const out: IntervalStretch[] = [];
  for (const row of intervals as Record<string, unknown>[]) {
    const line = Array.isArray(row?.line) ? (row.line as unknown[]).filter((p): p is [number, number] => Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number")) : [];
    const lengthM = Number(row?.l);
    if (typeof row?.id !== "string" || line.length < 2 || !(lengthM > 0)) continue;
    const bothWays = row.w === 1;
    const riseM = Number(row.r) || 0;
    const t = Number(row.t);
    out.push({
      id: row.id,
      lengthM,
      riseM,
      gradePct: Number(row.g) || 0,
      line,
      bothWays,
      name: typeof row.n === "string" && row.n ? row.n : null,
      surface: row.s === "p" ? "path" : row.s === "g" ? "gravel" : "road",
      busy: row.b === 1,
      minutes: t > 0 ? t : Math.round(effortMinutes(lengthM, riseM, bothWays) * 10) / 10,
      bollards: Number(row.k) > 0 ? Number(row.k) : 0,
    });
  }
  return out;
}

export async function loadIntervals(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<IntervalStretch[] | null> {
  try {
    const response = await fetcher(url);
    return response.ok ? parseIntervals(await response.json()) : null;
  } catch {
    return null;
  }
}

/** The stretches that take at least `minutes` to ride. */
export function intervalsAtLeast(stretches: readonly IntervalStretch[], minutes: number): IntervalStretch[] {
  return stretches.filter((s) => s.minutes >= minutes);
}

/** The map's source: each stretch as a line in its riding direction, `one` where it holds one way only. */
export function intervalsGeoJson(stretches: readonly IntervalStretch[]): object {
  return {
    type: "FeatureCollection",
    features: stretches.map((s) => ({ type: "Feature", properties: { id: s.id, one: !s.bothWays, n: s.name ?? "", l: s.lengthM, r: s.riseM, t: s.minutes, k: s.bollards, x0: s.line[0][0], y0: s.line[0][1], x1: s.line[s.line.length - 1][0], y1: s.line[s.line.length - 1][1] }, geometry: { type: "LineString", coordinates: s.line } })),
  };
}

/** The highlight (under the stress lines) and the one-way arrows (over them). */
export function intervalsLayers(dark?: boolean): Record<string, unknown>[] {
  const line = {
    id: INTERVALS_LINE_LAYER,
    type: "line",
    source: INTERVALS_SOURCE,
    minzoom: INTERVALS_MIN_ZOOM,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": intervalsColour(INTERVALS_RAMP), "line-opacity": INTERVALS_OPACITY, "line-width": ["interpolate", ["linear"], ["zoom"], INTERVALS_MIN_ZOOM, 5, 14, 12, 17, 18] },
  };
  const arrows = {
    id: INTERVALS_ARROW_LAYER,
    type: "symbol",
    source: INTERVALS_SOURCE,
    minzoom: 12,
    filter: ["==", ["get", "one"], true],
    layout: { "symbol-placement": "line", "symbol-spacing": 90, "text-field": "›", "text-font": [FONT], "text-size": 22, "text-keep-upright": false, "text-allow-overlap": true },
    paint: { "text-color": intervalsColour(INTERVALS_RAMP), "text-halo-color": "#ffffff", "text-halo-width": 2 },
  };
  return [withDarkPaint(line, dark), withDarkPaint(arrows, dark)];
}

// --- The switch, its status and the legend --------------------------------------------------

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readIntervalsLayer(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(INTERVALS_PREF_KEY) === "on";
  } catch {
    return false;
  }
}

export function saveIntervalsLayer(on: boolean, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(INTERVALS_PREF_KEY, on ? "on" : "off");
  } catch {
    // Not kept: the switch still works for this visit.
  }
}

export function readIntervalsMinutes(store: Store | null = defaultStore()): IntervalsMinutes {
  try {
    const kept = Number(store?.getItem(INTERVALS_MINUTES_KEY));
    return (INTERVALS_MINUTES_OPTIONS as readonly number[]).includes(kept) ? (kept as IntervalsMinutes) : INTERVALS_MINUTES_OPTIONS[0];
  } catch {
    return INTERVALS_MINUTES_OPTIONS[0];
  }
}

export function saveIntervalsMinutes(minutes: IntervalsMinutes, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(INTERVALS_MINUTES_KEY, String(minutes));
  } catch {
    // Not kept: the choice still works for this visit.
  }
}

/** What the section says while on and the file is not there to draw. */
export function intervalsStatusText(on: boolean, status: IntervalsStatus): string {
  if (!on) return "";
  return status === "unavailable" ? INTERVALS_UNAVAILABLE : status === "empty" ? INTERVALS_NONE : "";
}

export const INTERVALS_LEGEND_TEXT = t(LEGEND_TEXT);

/**
 * Inside Plan's Trails and terrain section, beside Climbs (the owner, 2026-11-17: "a layer next to climbs"): its own
 * switch, its hint, what it says while it cannot draw, and its key while on. The section switch counts it too
 * (lib/terrainSection.ts).
 */
export function IntervalsControls({
  on,
  onChange,
  status = "",
  minutes,
  onMinutesChange,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  status?: string;
  minutes?: IntervalsMinutes;
  onMinutesChange?: (minutes: IntervalsMinutes) => void;
}): ReactElement {
  return h(
    "div",
    { className: "intervals-controls" },
    h(
      "div",
      { className: "a11y-setting" },
      h(
        "button",
        {
          type: "button",
          role: "switch",
          id: "intervals-switch",
          className: "switch",
          "aria-checked": on,
          "aria-labelledby": "intervals-label",
          "aria-describedby": "intervals-hint",
          onClick: () => onChange(!on),
        },
        h("span", { id: "intervals-label", className: "switch-label" }, INTERVALS_LABEL),
        h("span", { className: "switch-state", "aria-hidden": "true" }, on ? t("On") : t("Off")),
      ),
      h("p", { className: "hint", id: "intervals-hint" }, INTERVALS_HINT),
    ),
    on &&
      minutes !== undefined &&
      onMinutesChange &&
      h(
        "div",
        { className: "climbs-from" },
        h("label", { htmlFor: "intervals-minutes" }, INTERVALS_MINUTES_LABEL),
        h(
          "select",
          { id: "intervals-minutes", value: String(minutes), onChange: (event: { target: { value: string } }) => onMinutesChange(Number(event.target.value) as IntervalsMinutes) },
          ...INTERVALS_MINUTES_OPTIONS.map((m) => h("option", { key: m, value: String(m) }, t("{n} minutes", { n: m }))),
        ),
      ),
    h("p", { className: "hint intervals-status", role: "status" }, status),
    on &&
      h(
        "ul",
        { className: "legend intervals-legend", "aria-label": t(LEGEND_NAME) },
        h(
          "li",
          { key: "glow" },
          h(
            "svg",
            { width: 24, height: 12, "aria-hidden": "true", viewBox: "0 0 24 12" },
            h("line", { x1: 2, y1: 6, x2: 22, y2: 6, className: "intervals-swatch-0", stroke: INTERVALS_COLOUR, strokeOpacity: INTERVALS_OPACITY, strokeWidth: 8, strokeLinecap: "round" }),
            h("line", { x1: 2, y1: 6, x2: 22, y2: 6, stroke: "#9aa0a6", strokeWidth: 3 }),
          ),
          h("span", { className: "stress-label" }, INTERVALS_LEGEND_TEXT),
        ),
        ...INTERVALS_BANDS.map((_, i) =>
          h(
            "li",
            { key: `band-${i}`, className: "intervals-band" },
            h(
              "svg",
              { width: 24, height: 12, "aria-hidden": "true", viewBox: "0 0 24 12" },
              h("line", { x1: 2, y1: 6, x2: 22, y2: 6, className: `intervals-swatch-${i}`, stroke: INTERVALS_RAMP[i], strokeOpacity: INTERVALS_OPACITY, strokeWidth: 8, strokeLinecap: "round" }),
            ),
            h("span", { className: "stress-label" }, intervalsBandLabel(i)),
          ),
        ),
      ),
  );
}
