// The Intervals layer on the map (lib/intervals.ts): a pink highlight under the stress lines, so their colour stays on
// top, and arrows over them where a stretch holds one way only. No tap of its own: a press on a highlighted road
// is the road's, as ever (a point in Plan, the road panel). Drawn from outside MapView as the Scenic overlay is
// (app/mapOverlay.ts); App decides when it shows (its switch, Plan only). The file is fetched the first time it is on.
import { useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { setSource, useMap } from "./mapOverlay.ts";
import { STRESS_SOURCE_ID } from "../lib/mapStyle.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { INTERVALS_LAYERS, INTERVALS_SOURCE, intervalsGeoJson, intervalsLayers, loadIntervals, type IntervalStretch, type IntervalsStatus } from "../lib/intervals.ts";
import { stressOverlayLayers } from "../stressStyle.js";
import { useStressStyle } from "../useStressStyle.ts";
// A committed snapshot, as climbs.json: `manage.py build_intervals` on the build host writes it. `no-inline`, so it is
// its own hashed file the service worker leaves out of its precache (sw/swCore.mjs LAZY_ASSET).
import intervalsUrl from "../interval-data/intervals.json?url&no-inline";

/** Loads the file the first time `on` is true; the status for the Layers sheet. */
export function useIntervals(on: boolean): { data: IntervalStretch[] | null; status: IntervalsStatus } {
  const [data, setData] = useState<IntervalStretch[] | null>(null);
  const [status, setStatus] = useState<IntervalsStatus>("loading");
  const asked = useRef(false);
  useEffect(() => {
    if (!on || asked.current) return;
    asked.current = true;
    void loadIntervals(intervalsUrl).then((found) => {
      if (!found) asked.current = false;
      setData(found);
      setStatus(found === null ? "unavailable" : found.length === 0 ? "empty" : "ready");
    });
  }, [on]);
  return { data, status };
}

function lowestStressLayer(map: MapLibreMap): string | undefined {
  return (stressOverlayLayers(STRESS_SOURCE_ID) as Array<{ id: string }>).map((layer) => layer.id).find((id) => map.getLayer(id));
}

export function IntervalsOverlay({ getMap, on, data }: { getMap: () => MapLibreMap | null; on: boolean; data: readonly IntervalStretch[] | null }) {
  // The dark map's paint follows the style key, as the Scenic overlay's does.
  const style = useStressStyle();
  useMap(
    getMap,
    (map) => {
      if (!on || !data) {
        for (const id of INTERVALS_LAYERS) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
        return;
      }
      setSource(map, INTERVALS_SOURCE, intervalsGeoJson(data));
      const [line, arrows] = intervalsLayers();
      for (const id of INTERVALS_LAYERS) if (map.getLayer(id)) map.removeLayer(id);
      map.addLayer(line as never, lowestStressLayer(map) ?? (map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined));
      map.addLayer(arrows as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
    },
    [on, data, style],
  );
  return null;
}
