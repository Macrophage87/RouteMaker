/**
 * The "Topo lines" map layer (OWNER-DECISIONS 454: "Three map layers for everyone (every mode,
 * signed out too), off until clicked on: topo lines, climbs, mountain-bike trails."; slice 4 of
 * docs/MTB-TOPO-PLAN.md). Contour lines over the current base map, from the archive
 * scripts/build_contours.py writes beside it (/basemap/contours.pmtiles, USGS 3DEP 1/3 arc-second).
 *
 * The owner, 2026-10-10: "For topo, have the lines scale with zoom." So the spacing follows the zoom:
 * every 100 ft (30 m) at zoom 12 and below, 40 ft (12 m) at zoom 13, 20 ft (6 m) from zoom 14 in;
 * every fifth line an index line, heavier and labelled in feet with metres in brackets; and every
 * line widens as the map zooms in. The archive's three layers carry the lines by the coarsest spacing
 * each belongs to (`c100`, `c40`, `c20`), each only from the zoom it is first drawn at, so this file
 * and the build script share the numbers below (tests/test_build_contours.py reads them from here).
 *
 * The look is written here for this map: brown lines under the roads and labels, as topographic maps
 * draw contours. 454 says "Build our own topo map from OpenTopoMap's style"; OpenTopoMap's style code
 * names no licence (its README, checked 2026-10-10), so nothing of it is copied and the source's
 * credit line names OpenTopoMap only as the look's inspiration (docs/MTB-TOPO-PLAN.md, slice 4).
 *
 * Off unless the rider turns it on, kept per browser (`routemaker.topoLines`), like the
 * Mountain-bike trails switch; the archive is fetched only once the layer is first shown. A button
 * with role="switch", so a keyboard (Space or Enter) and a screen reader (name, state, description)
 * reach it; written with createElement so a test renders it.
 */
import { createElement as h, useSyncExternalStore, type ReactElement } from "react";
import { METRES_PER_FOOT, formatClimb } from "./format.ts";
import { t } from "./i18n.ts";

export const TOPO_LINES_LABEL = t("Topo lines");
export const TOPO_STORAGE_KEY = "routemaker.topoLines";
export const TOPO_SOURCE_ID = "topo-contours";
export const TOPO_PATH = "/basemap/contours.pmtiles";
export const TOPO_URL = `pmtiles://${TOPO_PATH}`;
/** The archive's elevation property: whole feet. */
export const TOPO_ELEVATION = "ele_ft";
/** The first zoom drawn (the archive's own lowest zoom), and the archive's highest (overzoomed past it). */
export const TOPO_MIN_ZOOM = 10;
export const TOPO_MAX_ZOOM = 14;
/** Every so many lines is an index line. */
export const TOPO_INDEX_EVERY = 5;

/**
 * One zoom band: drawn from `minzoom` up to (not including) `maxzoom`, lines every `intervalFt`,
 * read from the archive layers that hold such lines (`sourceLayers`: at zoom 13 the 40 ft lines are
 * all of `c40` and the 200 ft multiples in `c100`; `c20` holds none).
 */
export interface TopoBand {
  minzoom: number;
  maxzoom: number;
  intervalFt: number;
  sourceLayers: readonly string[];
}

/** The owner's spacing by zoom (2026-10-10). Zoom 12 and below, 13, then 14 and in. */
export const TOPO_BANDS: readonly TopoBand[] = [
  { minzoom: TOPO_MIN_ZOOM, maxzoom: 13, intervalFt: 100, sourceLayers: ["c100"] },
  { minzoom: 13, maxzoom: 14, intervalFt: 40, sourceLayers: ["c100", "c40"] },
  { minzoom: 14, maxzoom: 24, intervalFt: 20, sourceLayers: ["c100", "c40", "c20"] },
];

/** The archive's layers, coarsest spacing first, and the zoom each is tiled from (scripts/build_contours.py BANDS). */
export const TOPO_SOURCE_LAYERS: readonly { layer: string; intervalFt: number; minzoom: number }[] = [
  { layer: "c100", intervalFt: 100, minzoom: 10 },
  { layer: "c40", intervalFt: 40, minzoom: 13 },
  { layer: "c20", intervalFt: 20, minzoom: 14 },
];

/**
 * The colours: a mid brown for the lines, a darker one for index lines, and the labels' brown on a
 * white halo (5.9:1 against white, over 4.5:1; topoLines.test.ts measures each). Not colour alone:
 * an index line is also heavier and carries its elevation in words.
 */
export const TOPO_COLOURS = {
  line: "#b07d4f",
  index: "#8a5a2c",
  label: "#7a4e24",
  halo: "#ffffff",
} as const;

/** Line widths (px) by zoom: thin zoomed out, wider zoomed in; an index line about twice a plain one. */
export const TOPO_WIDTHS = {
  line: [10, 0.35, 13, 0.55, 15, 0.8, 18, 1.3] as const,
  index: [10, 0.8, 13, 1.1, 15, 1.5, 18, 2.4] as const,
};

/** Short, read on every focus; the spacings through lib/format.ts, feet first. */
export const TOPO_LINES_HINT = t("Contours every {coarse}, {middle} at zoom 13, {fine} from 14.", { coarse: formatClimb(100 * METRES_PER_FOOT), middle: formatClimb(40 * METRES_PER_FOOT), fine: formatClimb(20 * METRES_PER_FOOT) });
export const TOPO_LINES_UNAVAILABLE_HINT = t("Not available on this server yet.");

type Expr = unknown[];
const ele: Expr = ["get", TOPO_ELEVATION];
const multipleOf = (n: number): Expr => ["==", ["%", ele, n], 0];
const interpolate = (stops: readonly number[]): Expr => ["interpolate", ["linear"], ["zoom"], ...stops];

/** Every layer id this file adds, for the visibility switch and the tests. */
export function topoLayerIds(): string[] {
  return topoLayers().map((layer) => layer.id as string);
}

/**
 * The style layers: for each band and each archive layer it reads, a line layer for the plain lines,
 * one for the index lines, and a label layer along the index lines. A 100 ft line drawn at zoom 13 is
 * shown only where it is a multiple of 40 ft too (200, 400, ...): the band's own spacing, never a mix.
 */
export function topoLayers(visible = true): Record<string, unknown>[] {
  const layers: Record<string, unknown>[] = [];
  const visibility = visible ? "visible" : "none";
  for (const band of TOPO_BANDS) {
    const index = band.intervalFt * TOPO_INDEX_EVERY;
    for (const sourceLayer of band.sourceLayers) {
      const base = {
        source: TOPO_SOURCE_ID,
        "source-layer": sourceLayer,
        minzoom: band.minzoom,
        maxzoom: band.maxzoom,
      };
      const inBand = multipleOf(band.intervalFt);
      const key = `topo-${band.intervalFt}-${sourceLayer}`;
      layers.push({
        ...base,
        id: `${key}-line`,
        type: "line",
        filter: ["all", inBand, ["!", multipleOf(index)]],
        layout: { "line-join": "round", visibility },
        paint: { "line-color": TOPO_COLOURS.line, "line-width": interpolate(TOPO_WIDTHS.line) },
      });
      layers.push({
        ...base,
        id: `${key}-index`,
        type: "line",
        filter: multipleOf(index),
        layout: { "line-join": "round", visibility },
        paint: { "line-color": TOPO_COLOURS.index, "line-width": interpolate(TOPO_WIDTHS.index) },
      });
      layers.push({
        ...base,
        id: `${key}-label`,
        type: "symbol",
        filter: multipleOf(index),
        layout: {
          visibility,
          "symbol-placement": "line",
          "symbol-spacing": 400,
          "text-field": topoLabelExpression(),
          // The street names' face (the owner, 2026-10-21: "All into stret name style"), smaller: a height, not a name.
          "text-font": ["Noto Sans Medium"],
          "text-size": interpolate([10, 12, 15, 13, 18, 13]),
          "text-max-angle": 30,
          "text-padding": 4,
        },
        paint: {
          "text-color": TOPO_COLOURS.label,
          "text-halo-color": TOPO_COLOURS.halo,
          "text-halo-width": 3,
        },
      });
    }
  }
  return layers;
}

/**
 * "500 ft (152 m)", "1,200 ft (366 m)": feet first, metres in brackets (the owner's rule), thousands separated
 * as `formatClimb` writes them, as MapLibre computes it per line.
 */
export function topoLabelExpression(): Expr {
  const grouped = (value: Expr) => ["number-format", value, { locale: "en-US", "max-fraction-digits": 0 }];
  return ["concat", grouped(ele), " ft (", grouped(["round", ["*", ele, METRES_PER_FOOT]]), " m)"];
}

/** The same label, worked out here, for the tests and any text alternative. */
export function topoLabel(feet: number): string {
  return formatClimb(feet * METRES_PER_FOOT);
}

/** The archive's source: credited for its look (USGS 3DEP is already in the map's credits). */
export function topoSource(): Record<string, unknown> {
  return {
    type: "vector",
    url: TOPO_URL,
    minzoom: TOPO_MIN_ZOOM,
    maxzoom: TOPO_MAX_ZOOM,
    attribution: 'Topo look after <a href="https://opentopomap.org/about">OpenTopoMap</a>',
  };
}

/** The base map layer the contours go under: its first road layer, so roads, labels and every overlay draw over them. */
export function topoBeforeId(layerIds: readonly string[]): string | undefined {
  return layerIds.find((id) => id.startsWith("roads_")) ?? layerIds.find((id) => id.startsWith("places_"));
}

export interface TopoMap {
  getSource(id: string): unknown;
  getLayer(id: string): unknown;
  addSource(id: string, source: unknown): unknown;
  addLayer(layer: unknown, beforeId?: string): unknown;
  setLayoutProperty(id: string, name: string, value: unknown): unknown;
  getStyle(): { layers?: { id: string }[] } | undefined;
}

/**
 * Show or hide the layer. The source and its layers are added the first time it is shown, so a
 * rider who never turns it on never fetches the archive; after that only visibility changes.
 */
export function syncTopoLines(map: TopoMap, on: boolean): void {
  if (!map.getSource(TOPO_SOURCE_ID)) {
    if (!on) return;
    map.addSource(TOPO_SOURCE_ID, topoSource());
    const before = topoBeforeId((map.getStyle()?.layers ?? []).map((l) => l.id));
    for (const layer of topoLayers(true)) map.addLayer(layer, before && map.getLayer(before) ? before : undefined);
    return;
  }
  for (const id of topoLayerIds()) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }
}

/**
 * Whether the server has the archive: a HEAD of it (the edge's same-site guard is met by the page's own Referer).
 * "offline" when the request itself failed (no signal), so a ride can say so rather than "not on this server".
 */
export async function topoArchive(fetcher: typeof fetch = fetch): Promise<"yes" | "no" | "offline"> {
  try {
    const response = await fetcher(TOPO_PATH, { method: "HEAD" });
    return response.ok ? "yes" : "no";
  } catch {
    return "offline";
  }
}

export async function topoAvailable(fetcher: typeof fetch = fetch): Promise<boolean> {
  return (await topoArchive(fetcher)) === "yes";
}

// ---- the switch's state: per browser, shared by the sheet and the map ------------------

interface KeyStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): KeyStore | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** What this browser remembers: true, false, or null for nothing (or a value this page did not write). */
export function storedTopoLines(storage: KeyStore | null = browserStorage()): boolean | null {
  try {
    const value = storage?.getItem(TOPO_STORAGE_KEY);
    return value === "on" ? true : value === "off" ? false : null;
  } catch {
    return null;
  }
}

export function rememberTopoLines(on: boolean, storage: KeyStore | null = browserStorage()): void {
  try {
    storage?.setItem(TOPO_STORAGE_KEY, on ? "on" : "off");
  } catch {
    // Blocked site data: the layer still works for this visit.
  }
}

let topoOn = storedTopoLines() === true;
const listeners = new Set<(on: boolean) => void>();

export function topoLinesOn(): boolean {
  return topoOn;
}

/** Turn the layer on or off and tell the subscribers; kept for this browser unless `remember` is false. */
export function setTopoLines(on: boolean, { remember = true, storage }: { remember?: boolean; storage?: KeyStore | null } = {}): void {
  if (remember) rememberTopoLines(on, storage === undefined ? browserStorage() : storage);
  if (on === topoOn) return;
  topoOn = on;
  for (const listener of [...listeners]) listener(on);
}

export function subscribeTopoLines(listener: (on: boolean) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Re-render when the layer is turned on or off; returns whether it is on. */
export function useTopoLines(): boolean {
  return useSyncExternalStore(subscribeTopoLines, topoLinesOn, topoLinesOn);
}

export function TopoLinesSwitch({
  on,
  onChange,
  available = true,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  /** False once a check found no archive on the server. */
  available?: boolean;
}): ReactElement {
  return h(
    "div",
    { className: "a11y-setting" },
    h(
      "button",
      {
        type: "button",
        role: "switch",
        id: "topo-lines-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "topo-lines-label",
        "aria-describedby": "topo-lines-hint",
        onClick: () => onChange(!on),
      },
      h("span", { id: "topo-lines-label", className: "switch-label" }, TOPO_LINES_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h(
      "p",
      // Polite, so the hint's change to "not available" is read out once the check answers.
      { className: "hint", id: "topo-lines-hint", "aria-live": "polite" },
      available ? TOPO_LINES_HINT : TOPO_LINES_UNAVAILABLE_HINT,
    ),
  );
}
