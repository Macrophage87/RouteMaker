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

export const INTERVALS_LABEL = "Interval stretches";
/** Read on every focus, so one short line. */
export const INTERVALS_HINT = "A mile or more with no stops, busy crossings or sharp turns, flat or uphill.";
export const INTERVALS_UNAVAILABLE = "Interval stretches are unavailable for now.";
/** The file ships empty until the build host fills it (interval-data/README.md). */
export const INTERVALS_NONE = "No interval stretches yet: they arrive with the next map data update.";
export const INTERVALS_PREF_KEY = "routemaker.intervalsLayer";

/** Deep pink: not a stress colour, not the Scenic teal, the rails' violet nor the route's blue. 6:1 on white. */
/** Drawn at this opacity: at least 3:1 on white, the land colour and the dark map as drawn (WCAG 1.4.11; v0.27.2 review). */
export const INTERVALS_OPACITY = 0.7;
export const INTERVALS_COLOUR = "#be185d";
export const INTERVALS_DARK_COLOUR = "#f472b6";
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
    out.push({
      id: row.id,
      lengthM,
      riseM: Number(row.r) || 0,
      gradePct: Number(row.g) || 0,
      line,
      bothWays: row.w === 1,
      name: typeof row.n === "string" && row.n ? row.n : null,
      surface: row.s === "p" ? "path" : row.s === "g" ? "gravel" : "road",
      busy: row.b === 1,
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

/** The map's source: each stretch as a line in its riding direction, `one` where it holds one way only. */
export function intervalsGeoJson(stretches: readonly IntervalStretch[]): object {
  return {
    type: "FeatureCollection",
    features: stretches.map((s) => ({ type: "Feature", properties: { id: s.id, one: !s.bothWays }, geometry: { type: "LineString", coordinates: s.line } })),
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
    paint: { "line-color": INTERVALS_COLOUR, "line-opacity": INTERVALS_OPACITY, "line-width": ["interpolate", ["linear"], ["zoom"], INTERVALS_MIN_ZOOM, 5, 14, 12, 17, 18] },
  };
  const arrows = {
    id: INTERVALS_ARROW_LAYER,
    type: "symbol",
    source: INTERVALS_SOURCE,
    minzoom: 12,
    filter: ["==", ["get", "one"], true],
    layout: { "symbol-placement": "line", "symbol-spacing": 90, "text-field": "›", "text-font": [FONT], "text-size": 22, "text-keep-upright": false, "text-allow-overlap": true },
    paint: { "text-color": INTERVALS_COLOUR, "text-halo-color": "#ffffff", "text-halo-width": 2 },
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

/** What the section says while on and the file is not there to draw. */
export function intervalsStatusText(on: boolean, status: IntervalsStatus): string {
  if (!on) return "";
  return status === "unavailable" ? INTERVALS_UNAVAILABLE : status === "empty" ? INTERVALS_NONE : "";
}

export const INTERVALS_LEGEND_TEXT = "Pink glow: an interval stretch. Arrows: ride it that way only (the other way goes downhill).";

/**
 * Inside Plan's Trails and terrain section, beside Climbs (the owner, 2026-11-17: "a layer next to climbs"): its own
 * switch, its hint, what it says while it cannot draw, and its key while on. The section switch counts it too
 * (lib/terrainSection.ts).
 */
export function IntervalsControls({ on, onChange, status = "" }: { on: boolean; onChange: (on: boolean) => void; status?: string }): ReactElement {
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
    status && h("p", { className: "hint intervals-status", role: "status" }, status),
    on &&
      h(
        "ul",
        { className: "legend intervals-legend", "aria-label": "Interval stretches legend" },
        h(
          "li",
          { key: "glow" },
          h(
            "svg",
            { width: 24, height: 12, "aria-hidden": "true", viewBox: "0 0 24 12" },
            h("line", { x1: 2, y1: 6, x2: 22, y2: 6, stroke: INTERVALS_COLOUR, strokeOpacity: INTERVALS_OPACITY, strokeWidth: 8, strokeLinecap: "round" }),
            h("line", { x1: 2, y1: 6, x2: 22, y2: 6, stroke: "#9aa0a6", strokeWidth: 3 }),
          ),
          h("span", { className: "stress-label" }, INTERVALS_LEGEND_TEXT),
        ),
      ),
  );
}
