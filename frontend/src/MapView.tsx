import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import { Protocol } from "pmtiles";
// MapLibre 6 ships its worker as a separate module and finds it next to its own
// file by `import.meta.url`, which a bundle does not preserve; Vite builds it
// as an asset of its own here and the map is told where it is.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { stressLayers } from "./stressStyle.js";
import { COVERAGE_BBOX, lonLatToTile, type LonLat } from "./lib/geo.ts";
import {
  BASEMAP_SOURCE_ID,
  STRESS_SOURCE_ID,
  MAP_CREDITS,
  buildStyle,
  stressSource,
} from "./lib/mapStyle.ts";
import type { RouteResponse } from "./lib/api.ts";

export type StressAvailability = "checking" | "available" | "unavailable";

interface Props {
  points: LonLat[];
  route: RouteResponse | null;
  stale: boolean;
  stressVisible: boolean;
  onStressAvailability: (availability: StressAvailability) => void;
  onMapClick: (point: LonLat) => void;
  onMovePoint: (index: number, point: LonLat) => void;
  onReady: (map: MapLibreMap) => void;
}

// One protocol for the page. MapLibre 4+ runs a custom protocol's handler on
// the page's own thread, so the archive's range requests carry this page as
// their Referer - which is what the edge's /basemap/* guard checks.
let protocolRegistered = false;
function registerPmtiles(): void {
  if (protocolRegistered) return;
  maplibregl.setWorkerUrl(maplibreWorkerUrl);
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  protocolRegistered = true;
}

const DC_CENTRE: LonLat = [-77.03, 38.9];
const ROUTE_SOURCE = "route";
const MAX_BOUNDS_PAD = 0.4;

function pointLabel(index: number, count: number): { text: string; name: string; kind: string } {
  if (index === 0) return { text: "A", name: "Start", kind: "start" };
  if (index === count - 1 && count > 1) return { text: "B", name: "End", kind: "end" };
  return { text: String(index), name: `Via point ${index}`, kind: "via" };
}

/** Is the route's extent already on screen? If not, the map moves to it. */
function routeInView(map: MapLibreMap, coordinates: LonLat[]): boolean {
  const view = map.getBounds();
  return coordinates.every(([lon, lat]) => view.contains([lon, lat]));
}

async function stressTilesAnswer(origin: string): Promise<boolean> {
  // One tile over central DC at a zoom the contract serves. A 404 means the
  // endpoint is not deployed; a 502 that the API is down. Either way the map
  // shows without the overlay rather than with a legend for nothing.
  const { x, y, z } = lonLatToTile(DC_CENTRE, 12);
  try {
    const response = await fetch(`${origin}/tiles/stress/${z}/${x}/${y}.pbf`);
    return response.ok;
  } catch {
    return false;
  }
}

export function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const loaded = useRef(false);
  // The first route shown (a shared link, usually) is framed; after that the
  // map moves only when a route leaves the screen.
  const fitted = useRef(false);
  const callbacks = useRef(props);
  callbacks.current = props;

  // The map itself, once.
  useEffect(() => {
    if (!container.current) return;
    registerPmtiles();
    const origin = window.location.origin;
    const basemapLayers = protomapsLayers(BASEMAP_SOURCE_ID, namedFlavor("light"), { lang: "en" });
    const [west, south, east, north] = COVERAGE_BBOX;
    const map = new maplibregl.Map({
      container: container.current,
      style: buildStyle(origin, basemapLayers) as maplibregl.StyleSpecification,
      center: DC_CENTRE,
      zoom: 11.2,
      minZoom: 7,
      maxZoom: 18,
      maxBounds: [
        [west - MAX_BOUNDS_PAD, south - MAX_BOUNDS_PAD],
        [east + MAX_BOUNDS_PAD, north + MAX_BOUNDS_PAD],
      ],
      // Every credit, in order, stated here: the base map source repeats its
      // own, which MapLibre folds into the same entry.
      attributionControl: { compact: true, customAttribution: [...MAP_CREDITS] },
      cooperativeGestures: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.getCanvas().setAttribute("aria-label", "Map. Use arrow keys to pan and plus or minus to zoom.");

    // The style package can name an icon the pinned sprite sheet predates
    // (basemaps-assets is pinned by commit in scripts/fetch_basemap.sh). A
    // blank stand-in keeps the label and quiets the console.
    map.setMissingStyleImageResolver((id) => {
      if (!map.hasImage(id)) map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
    });

    map.on("click", (event) => {
      callbacks.current.onMapClick([event.lngLat.lng, event.lngLat.lat]);
    });

    map.on("load", async () => {
      loaded.current = true;
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#ffffff", "line-width": 9, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#1d4ed8", "line-width": 5 },
      });
      syncRoute(map, callbacks.current.route, callbacks.current.stale, fitted);
      callbacks.current.onReady(map);

      callbacks.current.onStressAvailability("checking");
      const available = await stressTilesAnswer(origin);
      if (!mapRef.current) return;
      if (!available) {
        callbacks.current.onStressAvailability("unavailable");
        return;
      }
      map.addSource(STRESS_SOURCE_ID, stressSource(origin));
      // Under the base map's labels and the route, over its roads.
      const firstSymbol = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
      for (const layer of stressLayers(STRESS_SOURCE_ID)) {
        map.addLayer(
          {
            ...(layer as maplibregl.LineLayerSpecification),
            layout: { visibility: callbacks.current.stressVisible ? "visible" : "none" },
          },
          firstSymbol,
        );
      }
      callbacks.current.onStressAvailability("available");
    });

    map.on("error", (event) => {
      // A stress tile that fails after the probe passed: say so rather than
      // leave a legend over an empty overlay.
      const source = (event as { sourceId?: string }).sourceId;
      if (source === STRESS_SOURCE_ID) callbacks.current.onStressAvailability("unavailable");
    });

    return () => {
      loaded.current = false;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Markers follow the point list.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markers.current.forEach((m) => m.remove());
    markers.current = props.points.map((point, index) => {
      const { text, name, kind } = pointLabel(index, props.points.length);
      const element = document.createElement("div");
      element.className = `pin pin-${kind}`;
      element.textContent = text;
      element.setAttribute("role", "img");
      element.setAttribute("aria-label", `${name}. Drag to move.`);
      element.title = `${name} - drag to move`;
      // A click on a marker is not a click on the map: without this it would
      // also add a via point under the marker.
      element.addEventListener("click", (event) => event.stopPropagation());
      const marker = new maplibregl.Marker({ element, draggable: true, anchor: "center" })
        .setLngLat(point)
        .addTo(map);
      marker.on("dragend", () => {
        const { lng, lat } = marker.getLngLat();
        callbacks.current.onMovePoint(index, [lng, lat]);
      });
      return marker;
    });
  }, [props.points]);

  // The route line.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    syncRoute(map, props.route, props.stale, fitted);
  }, [props.route, props.stale]);

  // The overlay toggle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || !map.getSource(STRESS_SOURCE_ID)) return;
    for (const layer of stressLayers(STRESS_SOURCE_ID)) {
      if (map.getLayer(layer.id)) {
        map.setLayoutProperty(layer.id, "visibility", props.stressVisible ? "visible" : "none");
      }
    }
  }, [props.stressVisible]);

  return <div ref={container} className="map" role="region" aria-label="Map" />;
}

function syncRoute(
  map: MapLibreMap,
  route: RouteResponse | null,
  stale: boolean,
  fitted: { current: boolean },
): void {
  const source = map.getSource(ROUTE_SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  source.setData(
    route
      ? { type: "Feature", properties: {}, geometry: route.geometry }
      : { type: "FeatureCollection", features: [] },
  );
  map.setPaintProperty("route-line", "line-opacity", stale ? 0.45 : 1);
  if (
    route &&
    !stale &&
    route.geometry.coordinates.length > 1 &&
    (!fitted.current || !routeInView(map, route.geometry.coordinates))
  ) {
    fitted.current = true;
    const bounds = new maplibregl.LngLatBounds();
    route.geometry.coordinates.forEach((c) => bounds.extend(c));
    const narrow = window.matchMedia("(max-width: 720px)").matches;
    map.fitBounds(bounds, {
      padding: narrow ? { top: 40, bottom: 40, left: 30, right: 30 } : { top: 60, bottom: 60, left: 420, right: 60 },
      maxZoom: 15,
      duration: 600,
    });
  }
}
