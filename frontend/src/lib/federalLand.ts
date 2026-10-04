/**
 * The federal-land overlay for the Mass Ride map (PLAN.md FOLLOWUP-FEDERAL-LAYER,
 * owner items 236-239): the areas under federal control, lightly shaded, so a
 * mass ride can see where federal permit rules may apply. Information, not
 * legal advice, and not a police-jurisdiction map (ownership is not
 * jurisdiction). The routing and description warnings of item 239 are a later
 * step; this is the shaded layer, its legend and its popup.
 *
 * Every kind is told apart by more than colour: a fill pattern, an outline
 * dash, and a name in the legend and the popup. The data is
 * federal-data/federal-land.json, built by scripts/build_federal_land.py,
 * loaded only when the overlay is first shown.
 *
 * These are functions of a small map interface so a test can run them against
 * a stand-in (the real map needs WebGL), like railLayer.ts.
 */
import type { PresetId } from "./presets.ts";
import type { Raster } from "./stationIcons.ts";

export type FederalKind = "capitol" | "military" | "nps" | "reservation" | "federal";

/** The legend's order, and the data's: the most specific first. */
export const FEDERAL_KINDS: readonly FederalKind[] = ["capitol", "military", "nps", "reservation", "federal"];

export const FEDERAL_SOURCE_ID = "federal-land";
export const FEDERAL_TINT_LAYER = "federal-land-tint";
export const FEDERAL_PATTERN_LAYER = "federal-land-pattern";
export const federalOutlineLayer = (kind: FederalKind) => `federal-land-outline-${kind}`;
export const federalImageId = (kind: FederalKind) => `federal-pattern-${kind}`;

/** The one line the owner asked the map to say (items 238, 239). */
export const FEDERAL_NOTE = "Federal land - permit rules may differ (information, not legal advice)";

export interface FederalKindStyle {
  label: string;
  /** What the legend says the kind is. */
  describe: string;
  colour: string;
  /** The pattern in words, for the legend (a cue that is not colour). */
  cue: string;
  /** Outline dashes, in line widths (empty is solid). */
  dash: readonly number[];
  /** Whether a pixel of the 8x8 pattern tile is inked. */
  ink: (x: number, y: number) => boolean;
}

const mod = (n: number, m: number) => ((n % m) + m) % m;

export const FEDERAL_STYLE: Record<FederalKind, FederalKindStyle> = {
  capitol: {
    label: "Capitol grounds",
    describe: "the Architect of the Capitol's grounds",
    colour: "#b45309",
    cue: "dots",
    dash: [1, 2],
    ink: (x, y) => mod(x, 4) < 2 && mod(y, 4) < 2,
  },
  military: {
    label: "Military installation",
    describe: "a military or defense installation",
    colour: "#374151",
    cue: "cross-hatch",
    dash: [3, 2],
    ink: (x, y) => mod(x + y, 4) === 0 || mod(x - y, 4) === 0,
  },
  nps: {
    label: "National Park Service land",
    describe: "National Park Service parks, parkways and other Map A land",
    colour: "#8b6f47",
    cue: "rising diagonal stripes",
    dash: [],
    ink: (x, y) => mod(x + y, 4) === 0,
  },
  reservation: {
    label: "U.S. Reservation",
    describe: "other U.S. Reservations, federal land mostly kept by the National Park Service",
    colour: "#4b6a88",
    cue: "falling diagonal stripes",
    dash: [5, 2],
    ink: (x, y) => mod(x - y, 4) === 0,
  },
  federal: {
    label: "Other federal land",
    describe: "other federally owned land (GSA office buildings are left out)",
    colour: "#6d5b8a",
    cue: "horizontal stripes",
    dash: [6, 2, 1, 2],
    ink: (_x, y) => mod(y, 4) === 0,
  },
};

export const PATTERN_SIZE = 8;

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** The pattern tile for `kind`: its colour on inked pixels, clear elsewhere. */
export function federalPattern(kind: FederalKind): Omit<Raster, "pixelRatio"> {
  const { colour, ink } = FEDERAL_STYLE[kind];
  const [r, g, b] = hexToRgb(colour);
  const data = new Uint8Array(PATTERN_SIZE * PATTERN_SIZE * 4);
  for (let y = 0; y < PATTERN_SIZE; y++) {
    for (let x = 0; x < PATTERN_SIZE; x++) {
      if (!ink(x, y)) continue;
      data.set([r, g, b, 255], (y * PATTERN_SIZE + x) * 4);
    }
  }
  return { width: PATTERN_SIZE, height: PATTERN_SIZE, data };
}

/** The tile's inked pixels as an SVG path, so the legend draws the map's own pattern. */
export function federalPatternPath(kind: FederalKind): string {
  const { ink } = FEDERAL_STYLE[kind];
  let d = "";
  for (let y = 0; y < PATTERN_SIZE; y++) {
    for (let x = 0; x < PATTERN_SIZE; x++) if (ink(x, y)) d += `M${x} ${y}h1v1h-1z`;
  }
  return d;
}

/** Whether the overlay is on the map: Mass Ride only, and the rider's own switch. */
export function federalShown(preset: PresetId, on: boolean): boolean {
  return preset === "mass-ride" && on;
}

export interface FederalFeature {
  type: "Feature";
  properties: { kind: FederalKind; name: string; agency?: string };
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
}
export interface FederalData {
  type: "FeatureCollection";
  features: FederalFeature[];
}

const isKind = (value: unknown): value is FederalKind =>
  typeof value === "string" && (FEDERAL_KINDS as readonly string[]).includes(value);

/** The file's polygons with a known kind and a name; null if it is not a feature collection. */
export function parseFederalLand(value: unknown): FederalData | null {
  const body = value as { type?: unknown; features?: unknown } | null;
  if (!body || body.type !== "FeatureCollection" || !Array.isArray(body.features)) return null;
  const features: FederalFeature[] = [];
  for (const raw of body.features as Array<Record<string, any>>) {
    const props = raw?.properties;
    const geometry = raw?.geometry;
    if (!props || !isKind(props.kind) || typeof props.name !== "string" || !props.name) continue;
    if (!geometry || (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon")) continue;
    const agency = typeof props.agency === "string" && props.agency ? props.agency : undefined;
    features.push({
      type: "Feature",
      properties: agency ? { kind: props.kind, name: props.name, agency } : { kind: props.kind, name: props.name },
      geometry,
    });
  }
  return { type: "FeatureCollection", features };
}

/** Fetch and parse the overlay's file; null if it cannot be had (the overlay then stays off). */
export async function loadFederalLand(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<FederalData | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    const data = parseFederalLand(await response.json());
    return data && data.features.length > 0 ? data : null;
  } catch {
    return null;
  }
}

const byKind = (kind: FederalKind) => ["==", ["get", "kind"], kind];
const matchKind = (pick: (kind: FederalKind) => string) => [
  "match",
  ["get", "kind"],
  ...FEDERAL_KINDS.flatMap((kind) => [kind, pick(kind)]),
  "#000000",
];

/** The layers, bottom first: a light tint, the pattern, then one outline per kind. */
export function federalLayers(sourceId = FEDERAL_SOURCE_ID): Array<Record<string, any>> {
  return [
    {
      id: FEDERAL_TINT_LAYER,
      type: "fill",
      source: sourceId,
      paint: { "fill-color": matchKind((k) => FEDERAL_STYLE[k].colour), "fill-opacity": 0.1 },
    },
    {
      id: FEDERAL_PATTERN_LAYER,
      type: "fill",
      source: sourceId,
      paint: { "fill-pattern": matchKind(federalImageId), "fill-opacity": 0.45 },
    },
    ...FEDERAL_KINDS.map((kind) => ({
      id: federalOutlineLayer(kind),
      type: "line",
      source: sourceId,
      filter: byKind(kind),
      layout: { "line-join": "round" },
      paint: {
        "line-color": FEDERAL_STYLE[kind].colour,
        "line-width": 1.25,
        "line-opacity": 0.8,
        ...(FEDERAL_STYLE[kind].dash.length > 0 ? { "line-dasharray": [...FEDERAL_STYLE[kind].dash] } : {}),
      },
    })),
  ];
}

export const federalLayerIds = (): string[] => federalLayers().map((l) => l.id as string);

/** The parts of a MapLibre map these use. */
export interface FederalMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string; source?: string }> };
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  hasImage(id: string): boolean;
  addImage(id: string, image: Omit<Raster, "pixelRatio">, options: { pixelRatio: number }): void;
  setLayoutProperty(id: string, name: string, value: string): void;
}

/**
 * Where the overlay goes: directly under the stress overlay's first layer when
 * that is on the map, else under the base map's first label, so it sits over
 * the base map's land and roads and under the stress lines, the stations and
 * the route whichever of them is added first.
 */
export function federalBefore(map: FederalMap, stressSourceId: string): string | undefined {
  const layers = map.getStyle().layers;
  return (layers.find((l) => l.source === stressSourceId) ?? layers.find((l) => l.type === "symbol"))?.id;
}

/** Add the source, images and layers, once, hidden or shown; whether they were added. */
export function addFederalLand(map: FederalMap, data: FederalData, visible: boolean, stressSourceId: string): boolean {
  if (map.getSource(FEDERAL_SOURCE_ID)) return false;
  for (const kind of FEDERAL_KINDS) {
    if (!map.hasImage(federalImageId(kind))) map.addImage(federalImageId(kind), federalPattern(kind), { pixelRatio: 1 });
  }
  map.addSource(FEDERAL_SOURCE_ID, { type: "geojson", data });
  const before = federalBefore(map, stressSourceId);
  const visibility = visible ? "visible" : "none";
  for (const layer of federalLayers()) map.addLayer({ ...layer, layout: { ...layer.layout, visibility } }, before);
  return true;
}

/** Show or hide every layer that is on the map. */
export function setFederalVisibility(map: FederalMap, visible: boolean): void {
  for (const id of federalLayerIds()) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

export interface FederalCard {
  title: string;
  kind: string;
  agency: string | null;
  note: string;
}

/** What the popup says about a tapped area. */
export function federalCard(props: { kind: FederalKind; name: string; agency?: string }): FederalCard {
  return { title: props.name, kind: FEDERAL_STYLE[props.kind].label, agency: props.agency ?? null, note: FEDERAL_NOTE };
}
