/**
 * Bikeshare docks and free e-bikes on the map, and their section in Layers (v0.7.0; the rules, words and
 * drawing are lib/bikeshareDocks.ts's). The overlay draws only while its switch in Layers is on and asks
 * for the map's view after it moves and about every minute while the page is in front; nothing is asked when
 * the page is hidden, zoomed out past zoom 11, or every service is off.
 */
import { useEffect, useRef } from "react";
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { setSource, tapCard, useMap } from "./app/mapOverlay.ts";
import {
  DOCKS_POLL_MS,
  DOCKS_SOURCE,
  DOCK_CLUSTERS,
  DOCK_LAYERS,
  DOCK_POINTS,
  FREE_POINTS,
  FREE_SOURCE,
  dockCard,
  docksGeoJson,
  docksImages,
  docksLayers,
  docksPath,
  docksSource,
  freeBikeCard,
  freeGeoJson,
  loadDocks,
  type DocksAnswer,
  type OperatorInfo,
} from "./lib/bikeshareDocks.ts";
import { ROUTE_BOTTOM_LAYER } from "./lib/railLayer.ts";

export interface DocksReport {
  answer: DocksAnswer | null;
  /** A request was made for this view (so no answer means it failed). */
  asked: boolean;
  zoom: number;
}

const EMPTY = { type: "FeatureCollection", features: [] };
const MOVE_SETTLE_MS = 400;

export function BikeshareDocksOverlay({
  active,
  getMap,
  ask,
  operators,
  pixelRatio,
  onReport,
}: {
  /** Its switch in Layers is on (by default in the bikeshare ride types only). */
  active: boolean;
  getMap: () => MapLibreMap | null;
  /** The operators to ask for: switched on and licensed. */
  ask: readonly string[];
  operators: readonly OperatorInfo[];
  pixelRatio: number;
  onReport: (report: DocksReport) => void;
}) {
  const reportRef = useRef(onReport);
  reportRef.current = onReport;
  const operatorsKey = operators.map((o) => `${o.id}:${o.colour}:${o.licensed}`).join(",");
  useMap(
    getMap,
    (map) => {
      const hide = () => {
        for (const id of DOCK_LAYERS) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
      };
      if (!active) {
        hide();
        return;
      }
      for (const [id, { pixelRatio: ratio, ...image }] of docksImages(operators, pixelRatio)) {
        if (!map.hasImage(id)) map.addImage(id, image, { pixelRatio: ratio });
      }
      if (!map.getSource(DOCKS_SOURCE)) map.addSource(DOCKS_SOURCE, docksSource(EMPTY) as never);
      setSource(map, FREE_SOURCE, EMPTY);
      // Under the route: its own chosen docks keep their markers on top.
      const before = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
      for (const layer of docksLayers()) if (!map.getLayer(layer.id as string)) map.addLayer(layer as never, before);
      for (const id of DOCK_LAYERS) map.setLayoutProperty(id, "visibility", "visible");

      let latest: DocksAnswer | null = null;
      let controller: AbortController | null = null;
      let settle = 0;
      const draw = (answer: DocksAnswer | null) => {
        (map.getSource(DOCKS_SOURCE) as GeoJSONSource | undefined)?.setData((answer ? docksGeoJson(answer.docks) : EMPTY) as never);
        (map.getSource(FREE_SOURCE) as GeoJSONSource | undefined)?.setData((answer ? freeGeoJson(answer.free_bikes, operators) : EMPTY) as never);
      };
      const refresh = async () => {
        if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
        const b = map.getBounds();
        const zoom = map.getZoom();
        const path = docksPath({ west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() }, zoom, ask);
        controller?.abort();
        if (!path) {
          latest = null;
          draw(null);
          reportRef.current({ answer: null, asked: false, zoom });
          return;
        }
        const mine = new AbortController();
        controller = mine;
        const answer = await loadDocks(path, undefined, mine.signal);
        if (mine.signal.aborted) return;
        // A failed refresh keeps the last counts on the map; the section says they are unavailable.
        if (answer) {
          latest = answer;
          draw(answer);
        }
        reportRef.current({ answer, asked: true, zoom });
      };
      const onMove = () => {
        window.clearTimeout(settle);
        settle = window.setTimeout(() => void refresh(), MOVE_SETTLE_MS);
      };
      const onVisible = () => {
        if (document.visibilityState !== "hidden") void refresh();
      };
      const onCluster = (event: MapLayerMouseEvent) => {
        map.easeTo({ center: event.lngLat, zoom: Math.min(map.getZoom() + 2, 16) });
      };
      map.on("moveend", onMove);
      map.on("click", DOCK_CLUSTERS, onCluster);
      document.addEventListener("visibilitychange", onVisible);
      const poll = window.setInterval(() => void refresh(), DOCKS_POLL_MS);
      const offDock = tapCard(map, DOCK_POINTS, (id) => {
        const dock = latest?.docks.find((d) => d.id === id);
        return dock && latest ? dockCard(dock, latest) : null;
      });
      const offFree = tapCard(map, FREE_POINTS, (id) => {
        const bike = latest?.free_bikes[Number(id)];
        return bike && latest ? freeBikeCard(bike, operators, latest) : null;
      });
      void refresh();
      return () => {
        controller?.abort();
        window.clearTimeout(settle);
        window.clearInterval(poll);
        map.off("moveend", onMove);
        map.off("click", DOCK_CLUSTERS, onCluster);
        document.removeEventListener("visibilitychange", onVisible);
        offDock();
        offFree();
        draw(null);
        hide();
      };
    },
    [active, ask.join(","), operatorsKey, pixelRatio],
  );
  // Switched off: nothing to report.
  useEffect(() => {
    if (!active) reportRef.current({ answer: null, asked: false, zoom: 0 });
  }, [active]);
  return null;
}
