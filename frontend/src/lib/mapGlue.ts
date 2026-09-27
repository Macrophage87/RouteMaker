/**
 * What MapView does to the map, as functions of a small map interface, so a
 * test can run them against a stand-in (MapView itself needs WebGL).
 */
import { stressOverlayLayers } from "../stressStyle.js";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";

/** The parts of a MapLibre map these use. */
export interface OverlayMap {
  getSource(id: string): unknown;
  addSource(id: string, source: ReturnType<typeof stressSource>): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  setLayoutProperty(id: string, name: string, value: string): void;
}

/**
 * Add the stress overlay, once: under the base map's labels (and the route,
 * added later), over its roads, in exactly the order stressOverlayLayers
 * gives - every casing under every tier. Returns whether it was added.
 */
export function addStressOverlay(map: OverlayMap, origin: string, visible: boolean): boolean {
  if (map.getSource(STRESS_SOURCE_ID)) return false;
  map.addSource(STRESS_SOURCE_ID, stressSource(origin));
  const firstSymbol = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
  const layout = { visibility: visible ? "visible" : "none" };
  for (const layer of stressOverlayLayers(STRESS_SOURCE_ID)) {
    map.addLayer({ ...layer, layout }, firstSymbol);
  }
  return true;
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
