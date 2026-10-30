/**
 * See everyone (Stephen 2026-10-30: "When in a sharing mode offer a view where you can see every dot in the viewframe
 * if the default view won't"): in a ride or Roam with other riders' dots (Share live, Group Ride, Mass Ride), a side
 * button shows when the follow camera leaves one or more of them out of the open map (between the ride's card, its
 * bottom panel and its side buttons). Pressed, the map frames the rider and every dot, and keeps doing so as the dots
 * move; pressed again, Where am I?, or a move by hand goes back (the hand move to the idle recentre's 30 s). Hidden
 * whenever every dot is in view, so the ride's buttons stay as they were (Go stays clean: one control, only when needed).
 */
import type { LonLat } from "./geo.ts";
import type { ScreenBox } from "./detourSearch.ts";

/** A point on the screen, in the map's own pixels (MapLibre's `project`). */
export interface ScreenPoint {
  x: number;
  y: number;
}

/** The open map within a map `width` by `height`, given the paddings the ride's panels leave (lib/detourSearch.ts rideOpenPadding). */
export function openBox(width: number, height: number, padding: ScreenBox): ScreenBox {
  return { left: padding.left, top: padding.top, right: width - padding.right, bottom: height - padding.bottom };
}

/** Some of `dots` fall outside `open`, the part of the map the ride leaves clear. None: nothing is out of view. */
export function dotsOffScreen(dots: readonly LonLat[], toScreen: (at: LonLat) => ScreenPoint, open: ScreenBox): boolean {
  return dots.some((at) => {
    const p = toScreen(at);
    return !(p.x >= open.left && p.x <= open.right && p.y >= open.top && p.y <= open.bottom);
  });
}

/** The dots' places as one string, so a new array of the same dots changes nothing. */
export function dotsKey(dots: readonly LonLat[]): string {
  return dots.map((d) => `${d[0]},${d[1]}`).join(";");
}

/** The points the map frames: every dot, and the rider where known. */
export function everyoneFrame(dots: readonly LonLat[], rider: LonLat | null): LonLat[] {
  return rider ? [...dots, rider] : [...dots];
}

/** The view on or off, and whether the last check found a dot out of view. */
export interface EveryoneState {
  on: boolean;
  offScreen: boolean;
}

export type EveryoneEvent =
  | { kind: "press" }
  /** The map follows the rider again (Where am I?, the idle recentre). */
  | { kind: "following" }
  | { kind: "hand-move" }
  | { kind: "checked"; offScreen: boolean }
  | { kind: "dots-gone" };

/**
 * The view's changes. Off by a press or by following again, the last check (made while every dot was framed) is set
 * aside: the button stays until the follow camera's next move checks again, so it never vanishes under the press.
 */
export function everyoneStep(state: EveryoneState, event: EveryoneEvent): EveryoneState {
  switch (event.kind) {
    case "press":
      return state.on ? { on: false, offScreen: true } : { ...state, on: true };
    case "following":
      return state.on ? { on: false, offScreen: true } : state;
    case "hand-move":
      return state.on ? { ...state, on: false } : state;
    case "checked":
      return state.offScreen === event.offScreen ? state : { ...state, offScreen: event.offScreen };
    case "dots-gone":
      return { on: false, offScreen: false };
  }
}

/** The button shows: dots on the map, and the view on, or one out of view while the map follows the rider. */
export function everyoneShown(state: EveryoneState, anyDots: boolean, follow: boolean): boolean {
  return anyDots && (state.on || (follow && state.offScreen));
}
