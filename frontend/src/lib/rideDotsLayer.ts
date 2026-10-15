/**
 * The other riders on a Mass Ride or Group Ride link, and its alert pins, on the map (lib/rideGroup.ts). Drawn
 * from the page like the GPX reference line, over the route.
 *
 * Freshness at a glance (Stephen 2026-10-14 15:48 UTC): under 30 s a solid dot, with a brief ring as a new reading
 * lands; 30-90 s the dot at about half opacity; 90 s to 2 min a hollow ring only; then gone. An alert pin fades
 * the same way by its age. The map is the light basemap in both themes, so the colours are fixed: a dark blue
 * dot with a white outline (8.6:1 on the map's light land), and alerts in dark red.
 */
import type { LonLat } from "./geo.ts";
import { freshness, type RideAlert, type ShownDot } from "./rideGroup.ts";

export const DOTS_SOURCE = "ride-dots";
export const DOTS_LAYER = "ride-dots-dot";
export const PULSE_LAYER = "ride-dots-pulse";
export const ALERTS_SOURCE = "ride-alerts";
export const ALERTS_LAYER = "ride-alerts-pin";

const DOT = "#1e3a8a";
const ALERT = "#991b1b";

export interface DotsMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  removeSource(id: string): void;
  getLayer(id: string): unknown;
  addLayer(layer: object, beforeId?: string): void;
  removeLayer(id: string): void;
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
      properties: { freshness: d.freshness, pulse: d.pulse, age: d.age_s },
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

export function dotsLayers(): object[] {
  return [
    {
      id: PULSE_LAYER,
      type: "circle",
      source: DOTS_SOURCE,
      filter: ["==", ["get", "pulse"], true],
      paint: { "circle-radius": 13, "circle-color": DOT, "circle-opacity": 0, "circle-stroke-color": DOT, "circle-stroke-width": 2, "circle-stroke-opacity": 0.5 },
    },
    {
      id: DOTS_LAYER,
      type: "circle",
      source: DOTS_SOURCE,
      paint: {
        "circle-radius": 7,
        "circle-color": DOT,
        // Solid, faded (about half), or a hollow ring only.
        "circle-opacity": byFreshness(1, 0.5, 0),
        "circle-stroke-color": byFreshness("#ffffff", "#ffffff", DOT),
        "circle-stroke-width": byFreshness(2, 2, 2.5),
        "circle-stroke-opacity": byFreshness(1, 0.5, 1),
      },
    },
    {
      id: ALERTS_LAYER,
      type: "circle",
      source: ALERTS_SOURCE,
      paint: {
        "circle-radius": 10,
        "circle-color": ALERT,
        "circle-opacity": byFreshness(1, 0.5, 0),
        "circle-stroke-color": byFreshness("#ffffff", "#ffffff", ALERT),
        "circle-stroke-width": 3,
      },
    },
  ];
}

function setData(map: DotsMap, id: string, data: object): void {
  const source = map.getSource(id) as { setData?: (d: object) => void } | undefined;
  if (source?.setData) source.setData(data);
  else map.addSource(id, { type: "geojson", data });
}

/** Draw the dots and alert pins, adding the layers the first time; null removes them (the ride link closed). */
export function showRideDots(map: DotsMap, dots: readonly ShownDot[] | null, alerts: readonly RideAlert[] = [], sinceS = 0): void {
  if (dots === null) {
    for (const id of [ALERTS_LAYER, DOTS_LAYER, PULSE_LAYER]) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of [DOTS_SOURCE, ALERTS_SOURCE]) if (map.getSource(id)) map.removeSource(id);
    return;
  }
  setData(map, DOTS_SOURCE, dotFeatures(dots));
  setData(map, ALERTS_SOURCE, alertFeatures(alerts, sinceS));
  for (const layer of dotsLayers()) {
    const id = (layer as { id: string }).id;
    if (!map.getLayer(id)) map.addLayer(layer);
  }
}
