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
  allIconLines,
  iconId,
  iconShape,
  lineStyle,
  railFeatures,
  type RailVisibility,
  type Station,
} from "./railStations.ts";
import { elevatorIcon, stationIcon, type Raster } from "./stationIcons.ts";

export const RAIL_SOURCE_ID = "rail";
export const RAIL_LAYERS = {
  entrances: "rail-entrances",
  stations: "rail-stations",
  elevators: "rail-elevators",
} as const;
export const ELEVATOR_ICON = "rail-elevator";
/** The route's lowest layer (MapView); the stations go directly under it. */
export const ROUTE_BOTTOM_LAYER = "route-casing";
/** The base map's glyphs include this face (scripts/fetch_basemap.sh). */
export const LABEL_FONT = "Noto Sans Medium";

/** Street level: where an elevator is worth drawing, and a plain entrance later still. */
export const ELEVATOR_MIN_ZOOM = 15;
export const ENTRANCE_MIN_ZOOM = 16;
export const NAME_MIN_ZOOM = 13;
export const STATION_MIN_ZOOM = 8;

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
        "text-size": ["interpolate", ["linear"], ["zoom"], NAME_MIN_ZOOM, 11, 17, 13],
        "text-anchor": "top",
        "text-offset": [0, 0.9],
        "text-max-width": 8,
        "text-optional": true,
      },
      paint: {
        "text-color": "#1f2937",
        "text-halo-color": "#ffffff",
        "text-halo-width": 1.5,
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
): boolean {
  if (map.getSource(RAIL_SOURCE_ID)) return false;
  for (const { id, raster } of railImages(stations, pennColour, pixelRatio)) {
    if (map.hasImage(id)) continue;
    const { width, height, data } = raster;
    map.addImage(id, { width, height, data }, { pixelRatio: raster.pixelRatio });
  }
  map.addSource(RAIL_SOURCE_ID, { type: "geojson", data: railFeatures(stations, visibility) });
  const before = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
  for (const layer of railLayers()) map.addLayer(layer, before);
  return true;
}

/** Show the stations the toggles ask for. */
export function setRailVisibility(map: RailMap, stations: readonly Station[], visibility: RailVisibility): void {
  const source = map.getSource(RAIL_SOURCE_ID) as { setData?: (data: unknown) => void } | undefined;
  source?.setData?.(railFeatures(stations, visibility));
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
    if (props.kind === "station") return { id: props.id };
  }
  return null;
}
