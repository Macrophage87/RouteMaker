/**
 * See everyone (Stephen 2026-10-30: "When in a sharing mode offer a view where you can see every dot in the viewframe
 * if the default view won't", then "Always, when sharing"): in a ride or Roam with other riders' dots (Share live,
 * Group Ride, Mass Ride), a side button is there the whole time any dot is on the map, so the view can be chosen
 * before anyone drifts out of sight. Pressed, the map frames the rider and every dot (within the ride's card, its
 * bottom panel and its side buttons), and keeps doing so as the dots move and the rider rides on; pressed again,
 * Where am I?, or a move by hand goes back (the hand move to the idle recentre's 30 s). With no other dots, no button.
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

/** What ends or starts the view. */
export type EveryoneEvent =
  | { kind: "press" }
  /** The map follows the rider again (Where am I?, the idle recentre). */
  | { kind: "following" }
  | { kind: "hand-move" }
  | { kind: "dots-gone" };

/** The view on (true) or off after `event`: a press turns it over; anything else ends it. */
export function everyoneStep(on: boolean, event: EveryoneEvent): boolean {
  return event.kind === "press" ? !on : false;
}
