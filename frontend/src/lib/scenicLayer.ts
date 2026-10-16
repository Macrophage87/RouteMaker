/**
 * The Scenic map layer (v0.8.0). The owner, 2026-10-16: "Name in the road panel and have as a layer. Possibly the
 * scenic roads and trails layer. We could also add the east coast greenway and usbr paths to that." Then:
 * "Basically looking for a scenic layer in general. Off by default. How about including covered bridges".
 *
 * One switch in Plan's Map layers, after Trails and terrain, off by default and kept on this device; not in Go
 * (its Layers sheet leaves the section out and the map draws nothing of it there). It draws:
 *
 * - a thin casing, two teal lines just outside the stress line and its rails (`line-gap-width`), on every way the
 *   stress tiles mark `scenic` (core/stress_tiles.py, from `segment.scenic`): Montgomery County's Rustic and
 *   Exceptional Rustic Roads, Maryland's Scenic Byways, the East Coast Greenway and the US Bicycle Routes, and
 *   covered bridges. Under the stress layers, which stay on top and keep their colours; never on the Mass Ride map.
 * - covered bridges as named teal dots and viewpoints as small ones, from Places to see's file
 *   (amenity-data/places.json; scripts/build_places.py marks a covered bridge `cv`). While Places to see is on it
 *   draws them already, so this layer leaves its dots off.
 *
 * The casing is never the only cue: the road panel says the designations in words ("Rustic Road (Montgomery
 * County)", "East Coast Greenway · USBR 50"; core/segment_info.py), and a dot's tap card names it. Nothing here
 * changes a route or a stress rating. Written with createElement so a test renders it.
 */
import { createElement as h, type ReactElement } from "react";
import { FACILITIES, STRESS_TILE_LAYER, accessibilityOn, casingWidth, currentTiers, railWidth } from "../stressStyle.js";
import { LayerSection } from "./layerSection.ts";
import type { SightPlace } from "./places.ts";

export const SCENIC_LABEL = "Scenic";
/** Read on every focus, so one short line. */
export const SCENIC_HINT = "Rustic roads, scenic byways, the East Coast Greenway, US Bicycle Routes, covered bridges and viewpoints. Tap a road for its name.";
export const SCENIC_NO_STRESS = "Scenic roads need the stress map, unavailable for now.";
export const SCENIC_NO_PLACES = "Covered bridges and viewpoints are unavailable for now.";
export const SCENIC_PREF_KEY = "routemaker.scenicLayer";

/**
 * The casing's teal: not a stress colour in any palette, not a facility rail's violet, not the route's blue nor a
 * mountain-bike level's colour (scenicLayer.test.ts). 5.47:1 on the base map's white roads and the bridges' label
 * halo, and 3:1 or more on every surface of the light base map (the lowest, scrub's green, 3.20:1; park 3.23:1).
 */
export const SCENIC_COLOUR = "#0f766e";
export const SCENIC_LINE_PX = 1.5;
export const SCENIC_STRONG_LINE_PX = 2;
export const SCENIC_CASING_LAYER = "scenic-casing";

/** A way the tiles mark scenic, and not a mountain-bike trail (drawn on its own layer). */
export const SCENIC_FILTER = ["all", ["==", ["get", "scenic"], true], ["!=", ["get", "mtb"], true]];

/**
 * The gap the two lines sit either side of: the tier's casing, a pixel each side for a ring, and the facility's rails,
 * so the casing is outside everything the stress layers draw on the way.
 */
export function scenicGap(tiers = currentTiers(), strong = accessibilityOn()): unknown[] {
  const casing = ["match", ["get", "tier"], ...tiers.flatMap((t: { tier: number }) => [t.tier, casingWidth(t) + 2]), Math.max(...tiers.map((t: { tier: number }) => casingWidth(t) + 2))];
  const rails = ["match", ["coalesce", ["get", "facility"], "none"], ...FACILITIES.flatMap((f: { facility: string }) => [f.facility, 2 * railWidth(f, strong)]), 0];
  return ["+", casing, rails];
}

/** The casing layer over the stress tiles' source. */
export function scenicCasingLayer(sourceId = "stress", tiers = currentTiers(), strong = accessibilityOn()): Record<string, unknown> {
  return {
    id: SCENIC_CASING_LAYER,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: SCENIC_FILTER,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": SCENIC_COLOUR, "line-width": strong ? SCENIC_STRONG_LINE_PX : SCENIC_LINE_PX, "line-gap-width": scenicGap(tiers, strong) },
  };
}

/** Whether the layer draws: its switch, outside Go and off the Mass Ride map. */
export function scenicShown(on: boolean, mode: "go" | "plan" | string, massMap: boolean): boolean {
  return on && mode !== "go" && !massMap;
}

// --- Covered bridges and viewpoints ---------------------------------------------------------

export const SCENIC_POINTS_SOURCE = "scenic-points";
export const SCENIC_VIEWPOINT_LAYER = "scenic-viewpoints";
export const SCENIC_BRIDGE_LAYER = "scenic-bridges";
export const SCENIC_BRIDGE_LABEL_LAYER = "scenic-bridge-labels";
export const SCENIC_POINT_LAYERS = [SCENIC_VIEWPOINT_LAYER, SCENIC_BRIDGE_LAYER, SCENIC_BRIDGE_LABEL_LAYER] as const;
export const SCENIC_POINTS_MIN_ZOOM = 11;
export const SCENIC_LABEL_MIN_ZOOM = 13;
/** The base map's glyphs include this face (scripts/fetch_basemap.sh), as the climbs' and mountain-bike labels use. */
export const SCENIC_FONT = "Noto Sans Medium";

export type ScenicPointKind = "bridge" | "viewpoint";

export function scenicKind(place: SightPlace): ScenicPointKind | null {
  if (place.category === "bridge" && place.covered) return "bridge";
  return place.category === "viewpoint" ? "viewpoint" : null;
}

/** The covered bridges and viewpoints, as the points' source. */
export function scenicPointsGeoJson(places: readonly SightPlace[]): object {
  const features = [];
  for (const p of places) {
    const kind = scenicKind(p);
    if (kind) features.push({ type: "Feature", properties: { id: p.id, kind, name: p.name }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } });
  }
  return { type: "FeatureCollection", features };
}

/** A viewpoint's small dot, a covered bridge's larger one, and the bridge's name under it from zoom 13. */
export function scenicPointLayers(): Record<string, unknown>[] {
  const base = { source: SCENIC_POINTS_SOURCE, minzoom: SCENIC_POINTS_MIN_ZOOM };
  return [
    {
      id: SCENIC_VIEWPOINT_LAYER,
      type: "circle",
      ...base,
      filter: ["==", ["get", "kind"], "viewpoint"],
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], SCENIC_POINTS_MIN_ZOOM, 2.5, 16, 4], "circle-color": SCENIC_COLOUR, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 },
    },
    {
      id: SCENIC_BRIDGE_LAYER,
      type: "circle",
      ...base,
      filter: ["==", ["get", "kind"], "bridge"],
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], SCENIC_POINTS_MIN_ZOOM, 4, 16, 6.5], "circle-color": SCENIC_COLOUR, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 },
    },
    {
      id: SCENIC_BRIDGE_LABEL_LAYER,
      type: "symbol",
      ...base,
      minzoom: SCENIC_LABEL_MIN_ZOOM,
      filter: ["==", ["get", "kind"], "bridge"],
      layout: { "text-field": ["get", "name"], "text-font": [SCENIC_FONT], "text-size": 12, "text-anchor": "top", "text-offset": [0, 0.8], "text-optional": true },
      paint: { "text-color": SCENIC_COLOUR, "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
    },
  ];
}

/** A dot's tap card, in words. */
export function scenicPointCard(place: SightPlace): string[] {
  return [place.name, scenicKind(place) === "bridge" ? "Covered bridge." : "Viewpoint.", "From OpenStreetMap."];
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

/** The switch as kept on this device; off when nothing is kept or storage is blocked (off by default). */
export function readScenicLayer(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(SCENIC_PREF_KEY) === "on";
  } catch {
    return false;
  }
}

export function saveScenicLayer(on: boolean, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(SCENIC_PREF_KEY, on ? "on" : "off");
  } catch {
    // Not kept: the switch still works for this visit.
  }
}

/** The section's status line: what of the layer cannot show while it is on. */
export function scenicStatus(on: boolean, stressAvailable: boolean, placesUnavailable: boolean): string {
  if (!on) return "";
  return [stressAvailable ? "" : SCENIC_NO_STRESS, placesUnavailable ? SCENIC_NO_PLACES : ""].filter(Boolean).join(" ");
}

/** The Map layers section: one switch, its hint inside. */
export function ScenicSection({ on, onChange, status = "" }: { on: boolean; onChange: (on: boolean) => void; status?: string }): ReactElement {
  return h(
    LayerSection,
    { id: "scenic", title: SCENIC_LABEL, headingId: "scenic-heading", layers: [{ key: "scenic", label: SCENIC_LABEL, on }], onLayers: (next) => onChange(next.scenic), status },
    h("p", { className: "hint", id: "scenic-hint" }, SCENIC_HINT),
  );
}

export const SCENIC_LEGEND_TEXT =
  "Scenic: thin teal lines either side of a rustic road, a scenic byway, the East Coast Greenway or a US Bicycle Route " +
  "(the stress colour stays inside); teal dots for covered bridges, named, and viewpoints. The road panel names each.";

/** The legend's one entry: the casing round a road's line, and the words. */
export function ScenicLegend(): ReactElement {
  return h(
    "ul",
    { className: "legend scenic-legend", "aria-label": "Scenic legend" },
    h(
      "li",
      { key: "scenic" },
      h(
        "svg",
        { width: 24, height: 12, "aria-hidden": "true", className: "scenic-swatch", viewBox: "0 0 24 12" },
        h("line", { x1: 1, y1: 2, x2: 23, y2: 2, stroke: SCENIC_COLOUR, strokeWidth: SCENIC_LINE_PX }),
        h("line", { x1: 1, y1: 6, x2: 23, y2: 6, stroke: "#9aa0a6", strokeWidth: 4 }),
        h("line", { x1: 1, y1: 10, x2: 23, y2: 10, stroke: SCENIC_COLOUR, strokeWidth: SCENIC_LINE_PX }),
      ),
      h("span", { className: "stress-label" }, SCENIC_LEGEND_TEXT),
    ),
  );
}
