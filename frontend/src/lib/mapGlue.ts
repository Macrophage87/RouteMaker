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
 * ignored. Otherwise a click on a station opens its card, even where the
 * route runs over it - owner, 2026-09-28: "Tap = station, drag = line" (a
 * press there that becomes a drag is the line's; pointerTarget). Then a click
 * on the line puts a via in that leg, and anywhere else it is a new point.
 */
export function mapClickAction(state: PointerState & { afterDrag: boolean }): MapClickAction {
  if (state.popupOpen) return state.onStation ? "station" : "close-popup";
  if (state.afterDrag) return "ignore";
  if (state.onStation) return "station";
  return state.onLine ? "line" : "point";
}

export interface PointerAnswer {
  /** What a hover shows: a station's hover card, the line's handle, or nothing. */
  hover: "station" | "line" | "map";
  /**
   * Whether a press is (provisionally) the line's: if it becomes a drag it
   * drags the line; released as a click, it is mapClickAction's.
   */
  grab: boolean;
}

/**
 * What the pointer is on, for a hover and a press. A press near the line is
 * the line's wherever it is, a station included (owner, 2026-09-28: "A quick
 * click/tap opens the station card; pressing and dragging grabs the route
 * line. Both work everywhere."), but not while a popup is open, since a click
 * then only closes it. A hover over a station shows the station's card - with
 * a hint that the line can be dragged there too, where it can - and the
 * line's handle shows only off the stations, so the two never answer one
 * pointer together.
 */
export function pointerTarget(state: PointerState): PointerAnswer {
  const grab = state.onLine && !state.popupOpen;
  return { hover: state.onStation ? "station" : grab ? "line" : "map", grab };
}

/** What lies under a pointer, as MapView's finders report it. */
export interface Under<S, L> {
  station: S | null;
  line: L | null;
}

function stateOf(under: Under<unknown, unknown>, popupOpen: boolean): PointerState {
  return { popupOpen, onStation: under.station !== null, onLine: under.line !== null };
}

/** Whether a popup is open: a via's Remove (null when none), or a station's card. */
export function popupsOpen(viaPopup: unknown, cards: { cardOpen(): boolean } | null): boolean {
  return viaPopup !== null || (cards?.cardOpen() ?? false);
}

/** The line a press at `under` picks up (provisionally), or null: the press is the map's. */
export function pressGrab<L>(under: Under<unknown, L>, popupOpen: boolean): L | null {
  return pointerTarget(stateOf(under, popupOpen)).grab ? under.line : null;
}

export interface ClickEffects<S, L> {
  closePopups(): void;
  openCard(station: S): void;
  lineDrop(line: L): void;
  addPoint(): void;
}

/** Carry out a click at `under` (mapClickAction); returns what it was. */
export function runClick<S, L>(
  under: Under<S, L>,
  now: { popupOpen: boolean; afterDrag: boolean },
  effects: ClickEffects<S, L>,
): MapClickAction {
  const action = mapClickAction({ ...stateOf(under, now.popupOpen), afterDrag: now.afterDrag });
  if (action === "close-popup" || action === "station") effects.closePopups();
  if (action === "station" && under.station !== null) effects.openCard(under.station);
  else if (action === "line" && under.line !== null) effects.lineDrop(under.line);
  else if (action === "point") effects.addPoint();
  return action;
}

export interface HoverEffects<S> {
  /** Draw the line's handle at a spot, or take it away (a map render). */
  drawHandle(at: readonly [number, number] | null): void;
  /** A station's hover card (with the line hint), or none. */
  stationHover(station: S | null, lineHint: boolean): void;
  setCursor(cursor: string): void;
}

/**
 * Carry out a hover at `under`. The handle is drawn, and the cursor written,
 * only when they change: a pointer nowhere near the line, frame after frame,
 * is no reason to render.
 */
export function runHover<S, L extends { at: readonly [number, number] }>(
  under: Under<S, L>,
  popupOpen: boolean,
  shown: { handle: readonly [number, number] | null; cursor: string },
  effects: HoverEffects<S>,
): void {
  const target = pointerTarget(stateOf(under, popupOpen));
  const at = target.hover === "line" && under.line !== null ? under.line.at : null;
  if (hoverChanged(shown.handle, at)) effects.drawHandle(at);
  // The hover is the station's exactly when there is one under the pointer.
  effects.stationHover(under.station, target.hover === "station" && target.grab);
  const cursor = target.hover === "map" ? "" : "pointer";
  if (shown.cursor !== cursor) effects.setCursor(cursor);
}

/**
 * Where the focus goes back to when a popup that took it closes: where it was
 * before, if that can still take it, or else the fallback (the map).
 */
export function focusBackTarget<E>(back: E | null, usable: (element: E) => boolean, fallback: E | null): E | null {
  return back !== null && usable(back) ? back : fallback;
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
