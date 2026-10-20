/**
 * The rail stations' layers, as functions of a small map interface so a test
 * can run them against a stand-in (the real map needs WebGL), like mapGlue.ts.
 *
 * Order, bottom to top: the base map and its labels, the stress overlay
 * (which goes under the base map's first label layer), then these - ordinary
 * entrances, stations, elevators - then the route, then the markers (DOM, so
 * always on top). They go in directly under the route's casing, so they sit
 * over everything the base map and the overlay draw and under the ride.
 */
import {
  ALERT_BADGE_ICON,
  ELEVATOR_OUT_ICON,
  allIconLines,
  closedIconId,
  iconId,
  iconShape,
  lineStyle,
  railFeatures,
  visibleLines,
  type RailVisibility,
  type Station,
  type StationBadges,
} from "./railStations.ts";
import { ROAD_LABEL } from "../stressStyle.js";
import { alertBadgeIcon, closedStationIcon, elevatorIcon, elevatorOutIcon, stationIcon, type Raster } from "./stationIcons.ts";

export const RAIL_SOURCE_ID = "rail";
export const RAIL_LAYERS = {
  entrances: "rail-entrances",
  stations: "rail-stations",
  elevators: "rail-elevators",
  badges: "rail-badges",
} as const;
export const ELEVATOR_ICON = "rail-elevator";
/** The route's lowest layer (MapView); the stations go directly under it. */
export const ROUTE_BOTTOM_LAYER = "route-casing";
/** A face the base map's glyphs include (scripts/fetch_basemap.sh), drawn in Atkinson Hyperlegible Next SemiBold (lib/mapGlyphs.ts). */
export const LABEL_FONT = "Noto Sans Medium";

/** Street level: where an elevator is worth drawing, and a plain entrance later still. */
export const ELEVATOR_MIN_ZOOM = 15;
export const ENTRANCE_MIN_ZOOM = 16;
/** Names from the zoom the map opens at (OPENING_ZOOM), not only street level (the owner, 2026-10-20: "probably show
 *  at most zooms too"); where they crowd, a name gives way and its icon stays (text-optional). */
export const NAME_MIN_ZOOM = 11;
export const STATION_MIN_ZOOM = 8;
/** A station's name at the street names' size, 20 px in a ride (ROAD_LABEL): the stations are often the wayfinders
 *  (the owner, 2026-10-20: "The metro names are now much smaller than the roadways, but are often the key wayfinders"). */
export const STATION_NAME_SIZE = ROAD_LABEL.size;
export const RIDE_STATION_NAME_SIZE = ROAD_LABEL.rideSize;
/** WMATA's badges from where a station's name would nearly show: further out they would crowd the lines. */
export const BADGE_MIN_ZOOM = 12;

const byKind = (kind: string) => ["==", ["get", "kind"], kind];

/** The layers, bottom first. */
export function railLayers(sourceId = RAIL_SOURCE_ID) {
  return [
    {
      id: RAIL_LAYERS.entrances,
      type: "circle",
      source: sourceId,
      minzoom: ENTRANCE_MIN_ZOOM,
      filter: byKind("entrance"),
      paint: {
        "circle-radius": 3.5,
        "circle-color": "#6b7280",
        "circle-opacity": 0.7,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 1,
        "circle-stroke-opacity": 0.7,
      },
    },
    {
      id: RAIL_LAYERS.stations,
      type: "symbol",
      source: sourceId,
      minzoom: STATION_MIN_ZOOM,
      filter: byKind("station"),
      layout: {
        "icon-image": ["get", "icon"],
        "icon-size": ["interpolate", ["linear"], ["zoom"], 8, 0.5, 11, 0.7, 14, 1, 17, 1.3],
        "icon-allow-overlap": true,
        // The base map's labels still place around the stations.
        "icon-ignore-placement": true,
        // Interchanges over the single-line stations beside them.
        "symbol-sort-key": ["get", "sort"],
        "text-field": ["step", ["zoom"], "", NAME_MIN_ZOOM, ["get", "name"]],
        "text-font": [LABEL_FONT],
        "text-size": STATION_NAME_SIZE,
        "text-anchor": "top",
        "text-offset": [0, 0.9],
        "text-max-width": 8,
        "text-optional": true,
      },
      paint: {
        // A closed station's name is grey as well as "(closed)" (railClosures.ts); #4b5563 is 7.6:1 on its white halo.
        "text-color": ["case", ["==", ["get", "closed"], true], "#4b5563", "#1f2937"],
        "text-halo-color": "#ffffff",
        // The street names' white band, so a line under a name does not hide it.
        "text-halo-width": ROAD_LABEL.haloWidth,
      },
    },
    {
      id: RAIL_LAYERS.elevators,
      type: "symbol",
      source: sourceId,
      minzoom: ELEVATOR_MIN_ZOOM,
      filter: byKind("elevator"),
      layout: {
        "icon-image": ELEVATOR_ICON,
        "icon-size": ["interpolate", ["linear"], ["zoom"], ELEVATOR_MIN_ZOOM, 0.9, 18, 1.25],
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
    },
    {
      // A WMATA alert names the station (amber "!"), or an elevator there is out (crossed-out lift):
      // beside the station's icon, its card says which in words (lib/stationTimes.ts).
      id: RAIL_LAYERS.badges,
      type: "symbol",
      source: sourceId,
      minzoom: BADGE_MIN_ZOOM,
      filter: byKind("badge"),
      layout: {
        "icon-image": ["get", "icon"],
        "icon-offset": ["get", "offset"],
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
      },
    },
  ];
}

/** The parts of a MapLibre map these use. */
export interface RailMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): void;
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  hasImage(id: string): boolean;
  addImage(id: string, image: Omit<Raster, "pixelRatio">, options: { pixelRatio: number }): void;
}

/** Every image the layers can ask for: one per combination of lines, and the elevator. */
export function railImages(stations: readonly Station[], pennColour: string, pixelRatio: number) {
  const images: Array<{ id: string; raster: Raster }> = allIconLines(stations).map((lines) => ({
    id: iconId(lines),
    raster: stationIcon(
      lines.map((line) => lineStyle(line, pennColour).color),
      iconShape(lines),
      pixelRatio,
    ),
  }));
  images.push({ id: ELEVATOR_ICON, raster: elevatorIcon(pixelRatio) });
  images.push({ id: ALERT_BADGE_ICON, raster: alertBadgeIcon(pixelRatio) });
  images.push({ id: ELEVATOR_OUT_ICON, raster: elevatorOutIcon(pixelRatio) });
  for (const shape of ["circle", "square"] as const) images.push({ id: closedIconId(shape), raster: closedStationIcon(shape, pixelRatio) });
  return images;
}

/**
 * Add the stations, once: their icons, their source for the toggles as they
 * are, and their layers directly under the route. Returns whether they were
 * added.
 */
export function addRailStations(
  map: RailMap,
  stations: readonly Station[],
  visibility: RailVisibility,
  pennColour: string,
  pixelRatio: number,
  isClosed?: (station: Station) => boolean,
  badges?: (station: Station) => StationBadges | null,
): boolean {
  if (map.getSource(RAIL_SOURCE_ID)) return false;
  for (const { id, raster } of railImages(stations, pennColour, pixelRatio)) {
    if (map.hasImage(id)) continue;
    const { width, height, data } = raster;
    map.addImage(id, { width, height, data }, { pixelRatio: raster.pixelRatio });
  }
  map.addSource(RAIL_SOURCE_ID, { type: "geojson", data: railFeatures(stations, visibility, isClosed, badges) });
  const before = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
  for (const layer of railLayers()) map.addLayer(layer, before);
  return true;
}

/** Show the stations the toggles ask for, the day's closed ones struck through and WMATA's badges beside. */
export function setRailVisibility(
  map: RailMap,
  stations: readonly Station[],
  visibility: RailVisibility,
  isClosed?: (station: Station) => boolean,
  badges?: (station: Station) => StationBadges | null,
): void {
  const source = map.getSource(RAIL_SOURCE_ID) as { setData?: (data: unknown) => void } | undefined;
  source?.setData?.(railFeatures(stations, visibility, isClosed, badges));
}

/** The rail feature under a click, if any: a station, or one of its elevators. */
export interface RailHit {
  id: string;
  /** Set when an elevator was tapped: that elevator is the point to use. */
  elevator?: [number, number];
}

export function railHitFrom(
  features: ReadonlyArray<{ properties?: Record<string, unknown> | null; geometry?: { type: string; coordinates?: unknown } }>,
): RailHit | null {
  for (const feature of features) {
    const props = feature.properties ?? {};
    if (typeof props.id !== "string") continue;
    if (props.kind === "elevator" && feature.geometry?.type === "Point") {
      const [lon, lat] = feature.geometry.coordinates as number[];
      return { id: props.id, elevator: [lon, lat] };
    }
    if (props.kind === "station" || props.kind === "badge") return { id: props.id };
  }
  return null;
}

/**
 * The station a tap at `point` is on, from the stations' own points: the
 * nearest shown one within `reach` pixels of it, projected by `project`. What
 * stationAt falls back to when the rendered-feature query misses.
 */
export function stationNear(
  stations: readonly Station[],
  visibility: RailVisibility,
  project: (point: [number, number]) => { x: number; y: number },
  point: { x: number; y: number },
  reach: number,
): RailHit | null {
  let best: { id: string; d: number } | null = null;
  for (const station of stations) {
    if (visibleLines(station, visibility).length === 0) continue;
    const at = project(station.point);
    const d = Math.hypot(at.x - point.x, at.y - point.y);
    if (d <= reach && (best === null || d < best.d)) best = { id: station.id, d };
  }
  return best && { id: best.id };
}
