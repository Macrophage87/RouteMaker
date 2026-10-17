// v0.8.0's Scenic layer on the map (lib/scenicLayer.ts): the thin casing over the stress tiles, under every stress
// layer, and the covered bridges' and viewpoints' dots from Places to see's file. Drawn from outside MapView as the
// places and repair overlays are (app/mapOverlay.ts); App decides when it shows (its switch, not in Go, not on the
// Mass Ride map).
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, tapCard, useMap } from "./mapOverlay.ts";
import { STRESS_SOURCE_ID } from "../lib/mapStyle.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import type { SightPlace } from "../lib/places.ts";
import {
  SCENIC_BRIDGE_LAYER,
  SCENIC_CASING_LAYER,
  SCENIC_POINT_LAYERS,
  SCENIC_POINTS_SOURCE,
  SCENIC_VIEWPOINT_LAYER,
  scenicCasingLayer,
  scenicPointCard,
  scenicPointLayers,
  scenicPointsGeoJson,
} from "../lib/scenicLayer.ts";
import { stressOverlayLayers } from "../stressStyle.js";
import { useStressStyle } from "../useStressStyle.ts";

/** The lowest stress layer the map has, so the casing goes under all of them (the stress stays on top). */
function lowestStressLayer(map: MapLibreMap): string | undefined {
  return (stressOverlayLayers(STRESS_SOURCE_ID) as Array<{ id: string }>).map((layer) => layer.id).find((id) => map.getLayer(id));
}

export function ScenicOverlay({ getMap, on, places, placesOn }: { getMap: () => MapLibreMap | null; on: boolean; places: readonly SightPlace[] | null; placesOn: boolean }) {
  // The casing's gap follows the tiers' widths, which the accessibility switch changes.
  const style = useStressStyle();
  useMap(
    getMap,
    (map) => {
      // The stress tiles' source arrives with the overlay (lib/mapGlue.ts addStressOverlay), maybe after this.
      const place = () => {
        if (!map.getSource(STRESS_SOURCE_ID)) return false;
        if (map.getLayer(SCENIC_CASING_LAYER)) map.removeLayer(SCENIC_CASING_LAYER);
        map.addLayer(scenicCasingLayer(STRESS_SOURCE_ID) as never, lowestStressLayer(map));
        map.setLayoutProperty(SCENIC_CASING_LAYER, "visibility", on ? "visible" : "none");
        return true;
      };
      if (place()) return;
      const onData = () => {
        if (place()) map.off("sourcedata", onData);
      };
      map.on("sourcedata", onData);
      return () => {
        map.off("sourcedata", onData);
      };
    },
    [on, style],
  );
  useMap(
    getMap,
    (map) => {
      if (!places || places.length === 0) {
        for (const id of SCENIC_POINT_LAYERS) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
        return;
      }
      setSource(map, SCENIC_POINTS_SOURCE, scenicPointsGeoJson(places));
      const before = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
      for (const layer of scenicPointLayers()) if (!map.getLayer(layer.id as string)) map.addLayer(layer as never, before);
      // Places to see draws the same bridges and viewpoints while it is on: one dot, not two.
      const shown = on && !placesOn;
      for (const id of SCENIC_POINT_LAYERS) map.setLayoutProperty(id, "visibility", shown ? "visible" : "none");
      const byId = new Map(places.map((p) => [p.id, p]));
      const words = (id: string) => {
        const p = byId.get(id);
        return p ? scenicPointCard(p) : null;
      };
      const offBridge = tapCard(map, SCENIC_BRIDGE_LAYER, words);
      const offViewpoint = tapCard(map, SCENIC_VIEWPOINT_LAYER, words);
      return () => {
        offBridge();
        offViewpoint();
      };
    },
    [places, on, placesOn],
  );
  return null;
}
