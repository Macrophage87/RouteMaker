/**
 * The other riders on a Mass Ride or Group Ride link, and its alert pins, on the map (lib/rideGroup.ts). Drawn
 * from the page like the GPX reference line, over the route.
 *
 * Freshness at a glance (Stephen 2026-10-14 15:48 UTC): under 30 s a solid mark, with a brief ring as a new reading
 * lands; 30-90 s the mark with a white hole in it (review F12: the fill stays opaque, as half opacity left it at
 * 2.62:1 on the map; the hole is the change, not the colour); 90 s to 2 min a hollow outline only; then gone. An
 * alert pin ages the same way. The map is the light basemap in both themes, so the colours are fixed, and alerts
 * stay the large dark red circle.
 *
 * Roles (Stephen 2026-10-16: "Each will get a distinct color on the map"): each role a colour and a shape, so
 * neither carries it alone. A participant is a small blue dot; the lead line a near-black violet chevron
 * pointing the way the route goes; the sweep a magenta square; a corker a dark grey diamond. Chosen by measurement
 * (review, 2026-10-16: an orange lead vanished on LTS 3 and 4 lines, and a blue-black sweep was Avoid's own line
 * colour): every pair is CIEDE2000 15 or more apart under normal vision, protanopia, deuteranopia and tritanopia;
 * each is 7 or more from every line and casing colour of every route palette under each of those (the white
 * edge separates the rest), 3:1 or more on every map surface, and 3:1 or more from its own white edge, so two
 * marks that touch are always split by a 3:1 boundary. Four fills 3:1 apart from each other cannot all also be
 * 3:1 on the light map (only two dark colours fit), so the edge and the shapes carry that (rideGroup.test.ts).
 * The marks are images drawn here pixel by pixel (lib/stationIcons.ts `rasterise`): no files, nothing loaded. A
 * forced-colours mode leaves the map's canvas as drawn; the key beside it (RideGroup.tsx) keeps its swatches'
 * colours there too and names each role in words.
 */
import type { LonLat } from "./geo.ts";
import { freshness, type Freshness, type RideAlert, type RideRole, type ShownDot } from "./rideGroup.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export const DOTS_SOURCE = "ride-dots";
export const DOTS_LAYER = "ride-dots-dot";
/** The lead line's chevrons: their own layer, turned with the map, so they keep pointing along the route. */
export const LEAD_LAYER = "ride-dots-lead";
export const PULSE_LAYER = "ride-dots-pulse";
export const ALERTS_STALE_LAYER = "ride-alerts-stale";
export const ALERTS_SOURCE = "ride-alerts";
export const ALERTS_LAYER = "ride-alerts-pin";
/**
 * A broadcast ride's leader (Stephen 2026-10-22): a wide ring round the sharer's mark, whatever role they ride as,
 * and the path the leader has taken since the link opened, a dashed line under the marks (kept on this device only).
 */
export const LEADER_LAYER = "ride-dots-leader";
export const TRAIL_SOURCE = "ride-leader-trail";
export const TRAIL_LAYER = "ride-leader-trail-line";
/** The route the leader's phone last sent (it may have re-routed off the shared one): dashed, as the way ahead. */
export const LEADER_ROUTE_SOURCE = "ride-leader-route";
export const LEADER_ROUTE_LAYER = "ride-leader-route-line";
export const LEADER_RING = "#220044";
/** Every layer a tap on a rider's mark is heard on. */
export const RIDER_LAYERS = [DOTS_LAYER, LEAD_LAYER] as const;

export const ROLE_COLOURS: Readonly<Record<RideRole, string>> = {
  participant: "#0000ee",
  lead: "#220044",
  sweep: "#7a1f7a",
  corker: "#444444",
};
/** A participant's dot (the colour every dot was before roles). */
export const DOT = ROLE_COLOURS.participant;
export const ALERT = "#991b1b";
export const HOLE = "#ffffff";

export type RoleShape = "dot" | "chevron" | "square" | "diamond";
export const ROLE_SHAPES: Readonly<Record<RideRole, RoleShape>> = { participant: "dot", lead: "chevron", sweep: "square", corker: "diamond" };
/** The mark's box in CSS pixels: a participant's small dot, the other roles larger. */
export const ROLE_SIZES: Readonly<Record<RideRole, number>> = { participant: 16, lead: 24, sweep: 22, corker: 24 };
const OUTLINE_PX = 2;
const RING_PX = 2.5;
const HOLE_PX = 2.5;

/**
 * Each shape as a polygon in a unit box (-1 to 1, y down), the chevron pointing up (north at bearing 0); the dot
 * is a circle. The same outlines draw the key's swatches (`roleSwatchPoints`).
 */
const POLYGONS: Readonly<Record<Exclude<RoleShape, "dot">, readonly [number, number][]>> = {
  chevron: [
    [0, -1],
    [0.9, 0.8],
    [0, 0.35],
    [-0.9, 0.8],
  ],
  square: [
    [-0.72, -0.72],
    [0.72, -0.72],
    [0.72, 0.72],
    [-0.72, 0.72],
  ],
  diamond: [
    [0, -1],
    [1, 0],
    [0, 1],
    [-1, 0],
  ],
};
/** Where a faded mark's hole sits (the chevron's is a little forward of its middle, inside the arms). */
const HOLE_AT: Readonly<Record<RoleShape, [number, number]>> = { dot: [0, 0], chevron: [0, -0.1], square: [0, 0], diamond: [0, 0] };

function segmentDistance(px: number, py: number, a: readonly [number, number], b: readonly [number, number]): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(a[0] + t * dx - px, a[1] + t * dy - py);
}

/** How far inside the shape a point is, in unit-box units (negative outside). */
export function insideBy(shape: RoleShape, u: number, v: number): number {
  if (shape === "dot") return 1 - Math.hypot(u, v);
  const poly = POLYGONS[shape];
  let inside = false;
  let nearest = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > v !== yj > v && u < ((xj - xi) * (v - yi)) / (yj - yi) + xi) inside = !inside;
    nearest = Math.min(nearest, segmentDistance(u, v, poly[i], poly[j]));
  }
  return inside ? nearest : -nearest;
}

export const dotImageId = (role: RideRole, f: Exclude<Freshness, "gone">) => `ride-dot-${role}-${f}`;

/** A rider's mark: fresh is the shape filled with a white edge, faded the same with a white hole, ring the outline only. */
export function dotImage(role: RideRole, f: Exclude<Freshness, "gone">, pixelRatio = 2): Raster {
  const shape = ROLE_SHAPES[role];
  const css = ROLE_SIZES[role];
  const size = Math.round(css * pixelRatio);
  const half = size / 2;
  const unit = (px: number) => px / (css / 2);
  const colour = hexToRgb(ROLE_COLOURS[role]);
  const white: Rgb = hexToRgb(HOLE);
  const [hx, hy] = HOLE_AT[shape];
  return rasterise(size, pixelRatio, (x, y) => {
    const u = (x - half) / half;
    const v = (y - half) / half;
    const depth = insideBy(shape, u, v);
    if (depth < 0) return null;
    if (f === "ring") return depth <= unit(RING_PX) ? colour : null;
    if (depth <= unit(OUTLINE_PX)) return white;
    if (f === "faded" && Math.hypot(u - hx, v - hy) <= unit(HOLE_PX)) return white;
    return colour;
  });
}

/** Every rider image the layers can ask for. */
export function dotImages(pixelRatio = 2): { id: string; raster: Raster }[] {
  const out: { id: string; raster: Raster }[] = [];
  for (const role of Object.keys(ROLE_COLOURS) as RideRole[]) {
    for (const f of ["fresh", "faded", "ring"] as const) out.push({ id: dotImageId(role, f), raster: dotImage(role, f, pixelRatio) });
  }
  return out;
}

/** A swatch's outline for the key, as SVG points in a 0-24 box ("" for the dot, drawn as a circle). */
export function roleSwatchPoints(role: RideRole): string {
  const shape = ROLE_SHAPES[role];
  if (shape === "dot") return "";
  return POLYGONS[shape].map(([u, v]) => `${(12 + u * 10).toFixed(1)},${(12 + v * 10).toFixed(1)}`).join(" ");
}

export interface DotsMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  removeSource(id: string): void;
  getLayer(id: string): unknown;
  addLayer(layer: object, beforeId?: string): void;
  removeLayer(id: string): void;
  hasImage(id: string): boolean;
  addImage(id: string, image: Omit<Raster, "pixelRatio">, options: { pixelRatio: number }): void;
}

interface Point {
  type: "Feature";
  properties: Record<string, string | number | boolean>;
  geometry: { type: "Point"; coordinates: LonLat };
}

export function dotFeatures(dots: readonly ShownDot[]): { type: "FeatureCollection"; features: Point[] } {
  return {
    type: "FeatureCollection",
    features: dots.map((d) => ({
      type: "Feature",
      properties: { freshness: d.freshness, pulse: d.pulse, age: d.age_s, role: d.role, bearing: d.bearing, along: Math.round(d.alongM), leader: d.leader === true },
      geometry: { type: "Point", coordinates: [d.lon, d.lat] },
    })),
  };
}

export function alertFeatures(alerts: readonly RideAlert[], sinceS = 0): { type: "FeatureCollection"; features: Point[] } {
  return {
    type: "FeatureCollection",
    features: alerts.map((a) => {
      const f = freshness(Math.min(a.age_s + sinceS, 120));
      return {
        type: "Feature",
        properties: { id: a.id, freshness: f === "gone" ? "ring" : f, label: a.label },
        geometry: { type: "Point", coordinates: [a.lon, a.lat] },
      };
    }),
  };
}

const byFreshness = <T,>(fresh: T, faded: T, ring: T) => ["match", ["get", "freshness"], "fresh", fresh, "faded", faded, ring];
const byRole = <T,>(values: Readonly<Record<RideRole, T>>) => [
  "match",
  ["get", "role"],
  "lead",
  values.lead,
  "sweep",
  values.sweep,
  "corker",
  values.corker,
  values.participant,
];
const markLayout = {
  "icon-image": ["concat", "ride-dot-", ["get", "role"], "-", ["get", "freshness"]],
  "icon-allow-overlap": true,
  "icon-ignore-placement": true,
};

export function trailFeature(trail: readonly LonLat[]): object {
  return {
    type: "FeatureCollection",
    features: trail.length >= 2 ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: trail } }] : [],
  };
}

export function dotsLayers(): object[] {
  return [
    {
      id: LEADER_ROUTE_LAYER,
      type: "line",
      source: LEADER_ROUTE_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": LEADER_RING, "line-width": 3, "line-dasharray": [1.5, 1.5], "line-opacity": 0.85 },
    },
    {
      // Where the leader has been: solid and wide, under the marks.
      id: TRAIL_LAYER,
      type: "line",
      source: TRAIL_SOURCE,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": LEADER_RING, "line-width": 5, "line-opacity": 0.55 },
    },
    {
      id: LEADER_LAYER,
      type: "circle",
      source: DOTS_SOURCE,
      filter: ["==", ["get", "leader"], true],
      paint: {
        "circle-radius": 19,
        "circle-color": HOLE,
        "circle-opacity": 0.6,
        "circle-stroke-color": LEADER_RING,
        "circle-stroke-width": 3,
      },
    },
    {
      id: PULSE_LAYER,
      type: "circle",
      source: DOTS_SOURCE,
      filter: ["==", ["get", "pulse"], true],
      paint: {
        "circle-radius": byRole({ participant: 12, lead: 16, sweep: 16, corker: 16 }),
        "circle-opacity": 0,
        "circle-stroke-color": byRole(ROLE_COLOURS),
        "circle-stroke-width": 2,
        "circle-stroke-opacity": 0.5,
      },
    },
    {
      id: DOTS_LAYER,
      type: "symbol",
      source: DOTS_SOURCE,
      filter: ["!=", ["get", "role"], "lead"],
      // The roles over the crowd of participants.
      layout: { ...markLayout, "icon-rotation-alignment": "viewport", "symbol-sort-key": ["match", ["get", "role"], "participant", 0, 1] },
    },
    {
      id: LEAD_LAYER,
      type: "symbol",
      source: DOTS_SOURCE,
      filter: ["==", ["get", "role"], "lead"],
      layout: { ...markLayout, "icon-rotate": ["get", "bearing"], "icon-rotation-alignment": "map", "icon-pitch-alignment": "map" },
    },
    {
      id: ALERTS_LAYER,
      type: "circle",
      source: ALERTS_SOURCE,
      paint: {
        "circle-radius": 10,
        "circle-color": ALERT,
        "circle-opacity": byFreshness(1, 1, 0),
        "circle-stroke-color": byFreshness("#ffffff", "#ffffff", ALERT),
        "circle-stroke-width": 3,
      },
    },
    {
      id: ALERTS_STALE_LAYER,
      type: "circle",
      source: ALERTS_SOURCE,
      filter: ["==", ["get", "freshness"], "faded"],
      paint: { "circle-radius": 4, "circle-color": HOLE, "circle-opacity": 1 },
    },
  ];
}

function setData(map: DotsMap, id: string, data: object): void {
  const source = map.getSource(id) as { setData?: (d: object) => void } | undefined;
  if (source?.setData) source.setData(data);
  else map.addSource(id, { type: "geojson", data });
}

/**
 * Draw the dots, alert pins and the leader's path, adding the images and layers the first time; null removes them
 * (the ride link closed).
 */
export function showRideDots(
  map: DotsMap,
  dots: readonly ShownDot[] | null,
  alerts: readonly RideAlert[] = [],
  sinceS = 0,
  pixelRatio = 2,
  trail: readonly LonLat[] = [],
  leaderRoute: readonly LonLat[] = [],
): void {
  if (dots === null) {
    for (const id of [ALERTS_STALE_LAYER, ALERTS_LAYER, LEAD_LAYER, DOTS_LAYER, PULSE_LAYER, LEADER_LAYER, TRAIL_LAYER, LEADER_ROUTE_LAYER]) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of [DOTS_SOURCE, ALERTS_SOURCE, TRAIL_SOURCE, LEADER_ROUTE_SOURCE]) if (map.getSource(id)) map.removeSource(id);
    return;
  }
  if (!map.hasImage(dotImageId("participant", "fresh"))) {
    for (const { id, raster } of dotImages(pixelRatio)) {
      if (map.hasImage(id)) continue;
      const { width, height, data } = raster;
      map.addImage(id, { width, height, data }, { pixelRatio: raster.pixelRatio });
    }
  }
  setData(map, DOTS_SOURCE, dotFeatures(dots));
  setData(map, ALERTS_SOURCE, alertFeatures(alerts, sinceS));
  setData(map, TRAIL_SOURCE, trailFeature(trail));
  setData(map, LEADER_ROUTE_SOURCE, trailFeature(leaderRoute));
  for (const layer of dotsLayers()) {
    const id = (layer as { id: string }).id;
    if (!map.getLayer(id)) map.addLayer(layer);
  }
}
