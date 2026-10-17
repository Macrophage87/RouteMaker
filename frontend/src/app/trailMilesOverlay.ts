// The trail mile markers on the map (lib/trailMiles.ts; OWNER-DECISIONS 465), drawn from outside MapView as the
// v0.7.0 overlays are: from the trail zooms in, always (no switch), with a tap card in words. The road panel names
// the nearest for a trail way, which is the keyboard's and screen reader's way to them.
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, tapCard, useMap } from "./mapOverlay.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { MILES_LABEL_LAYER, MILES_LAYER, MILES_SOURCE_ID, milesCard, milesGeoJson, milesLabelLayer, milesLayer, type TrailMiles } from "../lib/trailMiles.ts";

export function TrailMilesOverlay({ getMap, data }: { getMap: () => MapLibreMap | null; data: TrailMiles | null }) {
  useMap(
    getMap,
    (map) => {
      if (!data || data.markers.length === 0) return;
      setSource(map, MILES_SOURCE_ID, milesGeoJson(data.markers));
      const below = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
      if (!map.getLayer(MILES_LAYER)) map.addLayer(milesLayer() as never, below);
      if (!map.getLayer(MILES_LABEL_LAYER)) map.addLayer(milesLabelLayer() as never, below);
      const byId = new Map(data.markers.map((m) => [m.id, m]));
      return tapCard(map, MILES_LAYER, (id) => {
        const marker = byId.get(id);
        return marker ? milesCard(marker) : null;
      });
    },
    [data],
  );
  return null;
}
