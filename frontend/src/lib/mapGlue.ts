/**
 * What MapView does to the map, as functions of a small map interface, so a
 * test can run them against a stand-in (MapView itself needs WebGL).
 */
import {
  DEFAULT_WHEN,
  FACILITIES,
  STRESS_TILE_LAYER,
  currentTiers,
  facilityWidthAt,
  stressCasingLayers,
  stressFilters,
  stressLayers,
  stressOverlayLayers,
} from "../stressStyle.js";
import type { When } from "./dials.ts";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";
import type { RouteResponse } from "./api.ts";
import { routePaint, routeSections, sectionFeatures } from "./routeColours.ts";

/** The parts of a MapLibre map these use. */
export interface OverlayMap {
  getSource(id: string): unknown;
  addSource(id: string, source: ReturnType<typeof stressSource>): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  setLayoutProperty(id: string, name: string, value: string): void;
  setFilter(id: string, filter: unknown): void;
  setPaintProperty(id: string, name: string, value: unknown): void;
}

/**
 * Add the stress overlay, once: under the base map's labels (and the route,
 * added later), over its roads, in exactly the order stressOverlayLayers
 * gives - every casing under every tier. Returns whether it was added.
 */
export function addStressOverlay(map: OverlayMap, origin: string, visible: boolean, when?: When): boolean {
  if (map.getSource(STRESS_SOURCE_ID)) return false;
  map.addSource(STRESS_SOURCE_ID, stressSource(origin));
  const firstSymbol = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
  const layout = { visibility: visible ? "visible" : "none" };
  for (const layer of stressOverlayLayers(STRESS_SOURCE_ID, when)) {
    map.addLayer({ ...layer, layout }, firstSymbol);
  }
  return true;
}

/**
 * Draw the overlay for the ride time `when`: a road closed to cars then draws
 * as an off-road path, and one the zoomed-out tiles carry only for other ride
 * times is not drawn (stressStyle.js, stressFilters). The tiles are the same
 * whatever the ride time; only the style's filters change.
 */
export function setStressWhen(map: OverlayMap, when: When): void {
  const filters = stressFilters(when);
  for (const [id, filter] of Object.entries(filters)) {
    if (map.getLayer(id)) map.setFilter(id, filter);
  }
  for (const facility of FACILITIES) {
    const id = `facility-${facility.facility}`;
    if (map.getLayer(id)) map.setPaintProperty(id, "line-width", facilityWidthAt(facility, when));
  }
}

/**
 * Paint the overlay in the palette and strength in use: each tier's line and
 * casing, in colour and width, and the facility rails, which sit outside the
 * casing. All in place, so a rider's flip of the accessibility switch shows at
 * once, without a reload and without the tiles being fetched again. A layer
 * the map does not have (the overlay unavailable) is skipped.
 */
export function setStressPalette(
  map: OverlayMap,
  when: When = DEFAULT_WHEN,
  tiers: ReturnType<typeof currentTiers> = currentTiers(),
): void {
  const layers = [...stressCasingLayers(STRESS_SOURCE_ID, when, tiers), ...stressLayers(STRESS_SOURCE_ID, when, tiers)];
  for (const layer of layers as Array<{ id: string; paint: Record<string, unknown> }>) {
    if (!map.getLayer(layer.id)) continue;
    map.setPaintProperty(layer.id, "line-color", layer.paint["line-color"]);
    map.setPaintProperty(layer.id, "line-width", layer.paint["line-width"]);
    // A casing is a ring around a faint line (stressStyle.js, FAINT), so its gap follows the line's width.
    if ("line-gap-width" in layer.paint) map.setPaintProperty(layer.id, "line-gap-width", layer.paint["line-gap-width"]);
  }
  for (const facility of FACILITIES) {
    const id = `facility-${facility.facility}`;
    if (map.getLayer(id)) map.setPaintProperty(id, "line-width", facilityWidthAt(facility, when));
  }
}

/** The parts of a MapLibre map the route's coloured sections use. */
export interface RouteSectionsMap {
  getSource(id: string): unknown;
  setPaintProperty(id: string, name: string, value: unknown): void;
}

/** The map source the route's stress sections are drawn from (MapView adds it). */
export const ROUTE_STRESS_SOURCE_ID = "route-stress";

/**
 * Draw the route's sections in the palette in use: cut the route at its
 * stress spans, put them in the sections source, and set the route layers'
 * opacities and casing. The colours travel in the features, so a change of
 * palette has to put the sections in again, which is why this is not part of
 * placing the route.
 */
export function setRouteSections(
  map: RouteSectionsMap,
  route: Pick<RouteResponse, "geometry" | "stress_spans"> | null,
  stale: boolean,
): void {
  const sections = route ? routeSections(route.geometry.coordinates as [number, number][], route.stress_spans) : null;
  (map.getSource(ROUTE_STRESS_SOURCE_ID) as { setData(data: object): void } | undefined)?.setData(sectionFeatures(sections));
  const paint = routePaint(sections !== null, stale);
  map.setPaintProperty("route-line", "line-opacity", paint.lineOpacity);
  map.setPaintProperty("route-stress", "line-opacity", paint.sectionOpacity);
  map.setPaintProperty("route-halo", "line-opacity", paint.haloOpacity);
  map.setPaintProperty("route-casing", "line-color", paint.casingColor);
}

/** Show or hide every overlay layer that is on the map. */
export function setStressVisibility(map: OverlayMap, visible: boolean): void {
  for (const { id } of stressOverlayLayers(STRESS_SOURCE_ID)) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

/**
 * The markers effect's dependencies: the points, and the counter App bumps to
 * put a dragged marker back without changing the points (a drag outside the
 * area). Without the counter a put-back marker stays where it was dropped.
 */
export function markerDeps<P>(points: readonly P[], markerReset: number): readonly unknown[] {
  return [points, markerReset];
}

/** What is under the pointer, as MapView finds it. */
export interface PointerState {
  /** A via's Remove or a rail station's card is open. */
  popupOpen: boolean;
  /** A station's symbol (or one of its elevators) is under the pointer, within the tap slop. */
  onStation: boolean;
  /** The route line is within the hit tolerance, clear of the markers. */
  onLine: boolean;
}

export type MapClickAction = "close-popup" | "ignore" | "station" | "line" | "point";

/**
 * What a click (or tap) on the map does. Nothing a click does while a popup
 * is open edits the route: a via's Remove or a station's card that is open is
 * closed, and on a station that station's card opens in its place; clicking
 * away is how a rider dismisses a popup, and it must not also add a point.
 * The click a browser still sends at the end of a drag of the line is
 * ignored. Otherwise a click on a station opens its card, even where the
 * route runs over it - owner, 2026-09-28: "Tap = station, drag = line" (a
 * press there that becomes a drag is the line's; pointerTarget). Then a click
 * on the line puts a via in that leg, and anywhere else it is a new point.
 */
export function mapClickAction(state: PointerState & { afterDrag: boolean }): MapClickAction {
  if (state.popupOpen) return state.onStation ? "station" : "close-popup";
  if (state.afterDrag) return "ignore";
  if (state.onStation) return "station";
  return state.onLine ? "line" : "point";
}

export interface PointerAnswer {
  /** What a hover shows: a station's hover card, the line's handle, or nothing. */
  hover: "station" | "line" | "map";
  /**
   * Whether a press is (provisionally) the line's: if it becomes a drag it
   * drags the line; released as a click, it is mapClickAction's.
   */
  grab: boolean;
}

/**
 * What the pointer is on, for a hover and a press. A press near the line is
 * the line's wherever it is, a station included (owner, 2026-09-28: "A quick
 * click/tap opens the station card; pressing and dragging grabs the route
 * line. Both work everywhere."), but not while a popup is open, since a click
 * then only closes it. A hover over a station shows the station's card - with
 * a hint that the line can be dragged there too, where it can - and the
 * line's handle shows only off the stations, so the two never answer one
 * pointer together.
 */
export function pointerTarget(state: PointerState): PointerAnswer {
  const grab = state.onLine && !state.popupOpen;
  return { hover: state.onStation ? "station" : grab ? "line" : "map", grab };
}

/** What lies under a pointer, as MapView's finders report it. */
export interface Under<S, L> {
  station: S | null;
  line: L | null;
}

function stateOf(under: Under<unknown, unknown>, popupOpen: boolean): PointerState {
  return { popupOpen, onStation: under.station !== null, onLine: under.line !== null };
}

/** Whether a popup is open: a via's Remove (null when none), or a station's card. */
export function popupsOpen(viaPopup: unknown, cards: { cardOpen(): boolean } | null): boolean {
  return viaPopup !== null || (cards?.cardOpen() ?? false);
}

/** The line a press at `under` picks up (provisionally), or null: the press is the map's. */
export function pressGrab<L>(under: Under<unknown, L>, popupOpen: boolean): L | null {
  return pointerTarget(stateOf(under, popupOpen)).grab ? under.line : null;
}

export interface ClickEffects<S, L> {
  closePopups(): void;
  openCard(station: S): void;
  lineDrop(line: L): void;
  addPoint(): void;
}

/** Carry out a click at `under` (mapClickAction); returns what it was. */
export function runClick<S, L>(
  under: Under<S, L>,
  now: { popupOpen: boolean; afterDrag: boolean },
  effects: ClickEffects<S, L>,
): MapClickAction {
  const action = mapClickAction({ ...stateOf(under, now.popupOpen), afterDrag: now.afterDrag });
  if (action === "close-popup" || action === "station") effects.closePopups();
  if (action === "station" && under.station !== null) effects.openCard(under.station);
  else if (action === "line" && under.line !== null) effects.lineDrop(under.line);
  else if (action === "point") effects.addPoint();
  return action;
}

export interface HoverEffects<S> {
  /** Draw the line's handle at a spot, or take it away (a map render). */
  drawHandle(at: readonly [number, number] | null): void;
  /** A station's hover card (with the line hint), or none. */
  stationHover(station: S | null, lineHint: boolean): void;
  setCursor(cursor: string): void;
}

/**
 * Carry out a hover at `under`. The handle is drawn, and the cursor written,
 * only when they change: a pointer nowhere near the line, frame after frame,
 * is no reason to render.
 */
export function runHover<S, L extends { at: readonly [number, number] }>(
  under: Under<S, L>,
  popupOpen: boolean,
  shown: { handle: readonly [number, number] | null; cursor: string },
  effects: HoverEffects<S>,
): void {
  const target = pointerTarget(stateOf(under, popupOpen));
  const at = target.hover === "line" && under.line !== null ? under.line.at : null;
  if (hoverChanged(shown.handle, at)) effects.drawHandle(at);
  // The hover is the station's exactly when there is one under the pointer.
  effects.stationHover(under.station, target.hover === "station" && target.grab);
  const cursor = target.hover === "map" ? "" : "pointer";
  if (shown.cursor !== cursor) effects.setCursor(cursor);
}

/**
 * Where the focus goes back to when a popup that took it closes: where it was
 * before, if that can still take it, or else the fallback (the map).
 */
export function focusBackTarget<E>(back: E | null, usable: (element: E) => boolean, fallback: E | null): E | null {
  return back !== null && usable(back) ? back : fallback;
}

/**
 * Whether the hover handle has to be drawn again: it appeared, went, or
 * moved. A pointer wandering away from the line gives "none" frame after
 * frame, and drawing "none" again is a map render for nothing.
 */
export function hoverChanged(before: readonly [number, number] | null, after: readonly [number, number] | null): boolean {
  if (before === null || after === null) return before !== after;
  return before[0] !== after[0] || before[1] !== after[1];
}

/** GET /api/coverage: the area the API routes in, as a GeoJSON polygon feature. */
export interface Coverage {
  type: "Feature";
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: Record<string, unknown>;
}

export const COVERAGE_SOURCE_ID = "coverage";

// The world as Web Mercator draws it: the mask's outer ring.
const WORLD: number[][] = [
  [-180, -85.0511],
  [180, -85.0511],
  [180, 85.0511],
  [-180, 85.0511],
  [-180, -85.0511],
];

/**
 * What greys out the map beyond the covered area (owner request of
 * 2026-09-27): the world with the coverage ring as its hole, and the ring
 * again as a line for the edge. The ring is the API's own
 * (`core.api.coverage_ring`, the box its route validator enforces), so what
 * the map shows as covered is what the planner accepts.
 */
export function coverageMask(coverage: Coverage) {
  const ring = coverage.geometry.coordinates[0];
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { part: "mask" },
        // A hole winds the other way from its outer ring (RFC 7946 3.1.6).
        geometry: { type: "Polygon" as const, coordinates: [WORLD, [...ring].reverse()] },
      },
      {
        type: "Feature" as const,
        properties: { part: "edge" },
        geometry: { type: "LineString" as const, coordinates: ring },
      },
    ],
  };
}

/**
 * The mask's two layers, bottom first. The base map is the same light flavour
 * in both themes (mapStyle.ts, SPRITE_FLAVOR), so one grey serves both: dark
 * enough to read as "not here", open enough that the roads beyond stay legible
 * for someone riding in from outside; the edge is a solid dark line.
 */
export const COVERAGE_MASK_LAYERS = [
  {
    id: "coverage-mask",
    type: "fill",
    source: COVERAGE_SOURCE_ID,
    filter: ["==", ["get", "part"], "mask"],
    paint: { "fill-color": "#5b616b", "fill-opacity": 0.42 },
  },
  {
    id: "coverage-edge",
    type: "line",
    source: COVERAGE_SOURCE_ID,
    filter: ["==", ["get", "part"], "edge"],
    paint: { "line-color": "#2f343b", "line-width": 1.5 },
  },
] as const;

/** The parts of a MapLibre map the mask uses. */
export interface MaskMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
}

/**
 * Add the mask, once, over the base map and under its labels - so a place
 * name beyond the edge is still read - and under the stress overlay, whichever
 * of the two reaches the map first. A layer added this way takes no clicks:
 * the map's own click handler still decides what a click outside does.
 */
export function addCoverageMask(map: MaskMap, coverage: Coverage): boolean {
  if (map.getSource(COVERAGE_SOURCE_ID)) return false;
  map.addSource(COVERAGE_SOURCE_ID, { type: "geojson", data: coverageMask(coverage) });
  const overlay = new Set(stressOverlayLayers(STRESS_SOURCE_ID).map((layer: { id: string }) => layer.id));
  const before = map.getStyle().layers.find((layer) => layer.type === "symbol" || overlay.has(layer.id))?.id;
  for (const layer of COVERAGE_MASK_LAYERS) map.addLayer({ ...layer }, before);
  return true;
}

/** The coverage the API serves, or null if it does not answer with one. */
export async function fetchCoverage(origin: string, get: typeof fetch = fetch): Promise<Coverage | null> {
  try {
    const response = await get(`${origin}/api/coverage`);
    if (!response.ok) return null;
    const body = (await response.json()) as Coverage;
    const ring = body?.geometry?.coordinates?.[0];
    if (body?.geometry?.type !== "Polygon" || !Array.isArray(ring) || ring.length < 4) return null;
    return body;
  } catch {
    return null;
  }
}

/** The parts of a MapLibre map the facility check uses. */
export interface FacilityMap {
  getSource(id: string): unknown;
  querySourceFeatures(
    id: string,
    options: { sourceLayer: string; filter: ["has", string] },
  ): Array<{ properties?: Record<string, unknown> | null }>;
  on(event: "idle", listener: () => void): unknown;
  off(event: "idle", listener: () => void): unknown;
}

/**
 * The bike-facility kinds the stress tiles on screen carry, among the ones the
 * legend knows. Until the routing lane's column exists the tiles carry only
 * "path", derived from the trail network (core/stress_tiles.py), so the legend
 * lists only the kinds the map has actually drawn.
 */
export function facilitiesOnMap(map: FacilityMap): Set<string> {
  const kinds = new Set<string>();
  if (!map.getSource(STRESS_SOURCE_ID)) return kinds;
  const known = new Set(FACILITIES.map((f: { facility: string }) => f.facility));
  for (const feature of map.querySourceFeatures(STRESS_SOURCE_ID, {
    sourceLayer: STRESS_TILE_LAYER,
    filter: ["has", "facility"],
  })) {
    const kind = feature.properties?.facility;
    if (typeof kind === "string" && known.has(kind)) kinds.add(kind);
  }
  return kinds;
}

/**
 * Report each time the map settles having drawn a facility kind it had not
 * drawn before, with every kind seen so far; stop once it has seen them all.
 */
export function watchForFacilities(map: FacilityMap, seen: (kinds: ReadonlySet<string>) => void): void {
  const all = new Set<string>();
  const check = () => {
    const before = all.size;
    for (const kind of facilitiesOnMap(map)) all.add(kind);
    if (all.size === before) return;
    seen(new Set(all));
    if (all.size === FACILITIES.length) map.off("idle", check);
  };
  map.on("idle", check);
}

/** The parts of a MapLibre map the zoom watch uses. */
export interface ZoomMap {
  getZoom(): number;
  on(event: "zoomend", listener: () => void): unknown;
}

/** Report the zoom now and after every change, for the legend's zoom notes. */
export function watchZoom(map: ZoomMap, zoom: (z: number) => void): void {
  zoom(map.getZoom());
  map.on("zoomend", () => zoom(map.getZoom()));
}
