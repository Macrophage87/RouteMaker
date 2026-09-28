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

/** What is under the pointer, as MapView finds it. */
export interface PointerState {
  /** A via's Remove or a rail station's card is open. */
  popupOpen: boolean;
  /** A station's symbol (or one of its elevators) is under the pointer, within the tap slop. */
  onStation: boolean;
  /** The route line is within the hit tolerance, clear of the markers. */
  onLine: boolean;
}

export type MapClickAction = "close-popup" | "ignore" | "station" | "line" | "point";

/**
 * What a click (or tap) on the map does. Nothing a click does while a popup
 * is open edits the route: a via's Remove or a station's card that is open is
 * closed, and on a station that station's card opens in its place; clicking
 * away is how a rider dismisses a popup, and it must not also add a point.
 * The click a browser still sends at the end of a drag of the line is
 * ignored. Otherwise a station under the pointer opens its card, even where
 * the route runs over it: the symbol is a small target and the line is
 * draggable on either side of it, where a station under the line's 8 px
 * (18 px by touch) reach could never be tapped at all. Then a click on the
 * line puts a via in that leg, and anywhere else it is a new point.
 */
export function mapClickAction(state: PointerState & { afterDrag: boolean }): MapClickAction {
  if (state.popupOpen) return state.onStation ? "station" : "close-popup";
  if (state.afterDrag) return "ignore";
  if (state.onStation) return "station";
  return state.onLine ? "line" : "point";
}

export type PointerTarget = "station" | "line" | "map";

/**
 * What the pointer is on, for a hover and for a press alike: the line's
 * handle shows exactly where a press would pick the line up. A station under
 * the pointer is the station's (its hover card, and a press that is left to
 * become its click), whether or not the line runs there; the line is the
 * line's only while no popup is open, since a click then only closes it.
 * Anywhere else a press pans the map.
 */
export function pointerTarget(state: PointerState): PointerTarget {
  if (state.onStation) return "station";
  return state.onLine && !state.popupOpen ? "line" : "map";
}

/**
 * Whether the hover handle has to be drawn again: it appeared, went, or
 * moved. A pointer wandering away from the line gives "none" frame after
 * frame, and drawing "none" again is a map render for nothing.
 */
export function hoverChanged(before: readonly [number, number] | null, after: readonly [number, number] | null): boolean {
  if (before === null || after === null) return before !== after;
  return before[0] !== after[0] || before[1] !== after[1];
}
