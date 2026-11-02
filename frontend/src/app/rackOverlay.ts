// Bike racks on the map (lib/bikeParking.ts; Stephen, 2026-11-01: "They should also be seen on the map"): every rack,
// drawn with the Water and restrooms layer's switch (no switch of their own) from RACK_MIN_ZOOM in; a press opens the
// rack's card (lib/stopCard.ts), never a route by itself. And Go's pins for the racks near a route's end
// (useRackPins), at any zoom, as the tapped-spot card's pins are drawn (app/spotPins.ts).
import { useEffect, useRef } from "react";
import { Marker, type Map as MapLibreMap } from "maplibre-gl";
import { RACK_ICON_ID, RACK_LAYER, RACK_SOURCE_ID, rackGeoJson, rackIcon, rackLayer, rackPoint, rackWords, type BikeRack } from "../lib/bikeParking.ts";
import type { StopActionFor } from "../lib/stopCard.ts";
import { spotPinsKey, type SpotRow } from "../lib/spotNearby.ts";
import { ROUTE_BOTTOM_LAYER } from "../lib/railLayer.ts";
import { setSource, stopCard, useMap } from "./mapOverlay.ts";
import { spotPinElement } from "./spotPins.ts";

export function RacksOverlay({ getMap, racks, on, pixelRatio, actionFor }: { getMap: () => MapLibreMap | null; racks: readonly BikeRack[] | null; on: boolean; pixelRatio: number; actionFor: StopActionFor }) {
  useMap(
    getMap,
    (map) => {
      if (!racks || racks.length === 0) return;
      if (!map.hasImage(RACK_ICON_ID)) {
        const { pixelRatio: ratio, ...image } = rackIcon(pixelRatio);
        map.addImage(RACK_ICON_ID, image, { pixelRatio: ratio });
      }
      setSource(map, RACK_SOURCE_ID, rackGeoJson(racks));
      if (!map.getLayer(RACK_LAYER)) map.addLayer(rackLayer() as never, map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined);
      map.setLayoutProperty(RACK_LAYER, "visibility", on ? "visible" : "none");
      const byId = new Map(racks.map((r) => [r.id, r]));
      return stopCard(map, RACK_LAYER, (id) => {
        const r = byId.get(id);
        return r ? { point: rackPoint(r), words: rackWords(r) } : null;
      }, actionFor);
    },
    [racks, on, pixelRatio, actionFor],
  );
  return null;
}

/** Pins for `rows` (the racks near a Go route's end) while given; made again only when what they show changes. */
export function useRackPins(getMap: () => MapLibreMap | null, rows: readonly SpotRow[] | null, onPick: (index: number, keyboard: boolean) => void) {
  const pick = useRef(onPick);
  pick.current = onPick;
  const latest = useRef(rows);
  latest.current = rows;
  const key = spotPinsKey(rows);
  useEffect(() => {
    const map = getMap();
    const rows = latest.current;
    if (!map || !rows || rows.length === 0) return;
    const markers = rows.map((row, index) => new Marker({ element: spotPinElement(row, (keyboard) => pick.current(index, keyboard)), anchor: "center" }).setLngLat(row.point).addTo(map));
    return () => markers.forEach((marker) => marker.remove());
  }, [getMap, key]);
}
