/**
 * What the stress legend says about zoom: what the overlay draws at the zoom
 * the map is at. The owner, 2026-09-28: "It looks way too busy zoomed out
 * though." and "Zoomed out just show the trails." - so below
 * `STRESS_ZOOMS.roads` the tiles carry only the traffic-free paths, and the
 * legend says why the roads have no stress lines there (core/stress_tiles.py).
 * Written with createElement so a test renders it (as pointsList.ts).
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { STRESS_ZOOMS } from "./mapStyle.ts";

/**
 * The one phrase for what the map shows zoomed out, wherever the legend says
 * it (review of round 1: it had three names for one thing). Roadside trails
 * are in it: the owner, 2026-09-29, "Show roadside trails (Recommended)".
 */
export const ZOOMED_OUT = "Zoomed out, only traffic-free paths and trails are shown.";

/** The bike-facility legend's note on the protected lanes the zoomed-out map leaves out. */
export const ROADWAY_LANES = `Protected lanes in the roadway show from zoom ${STRESS_ZOOMS.roads}.`;

/**
 * Roads closed to cars (the owner, 2026-09-29: "One note: Car-free roads
 * should be regarded the same as an off-road path on a map."), and those
 * closed at set times, which follow the ride time chosen ("Path on weekends
 * only").
 */
export const CAR_FREE_NOTE =
  "Roads closed to cars are shown as traffic-free paths, and roads closed only at set times, such as Sligo Creek " +
  "Parkway on weekends, are too when that ride time is chosen.";

/** The notice for the zoom the map is at, when the overlay is shown; null when there is none. */
export function stressZoomNotice(zoom: number | null, shown: boolean): string | null {
  if (zoom === null || !shown) return null;
  if (zoom < STRESS_ZOOMS.min) return "Zoom in to see traffic-free paths, trails and traffic stress.";
  if (zoom < STRESS_ZOOMS.roads) return `Zoom in to see traffic stress on roads. ${ZOOMED_OUT}`;
  return null;
}

/** The standing note on what is drawn at which zoom. */
export function stressZoomHint(zoom: number | null): string {
  const { min, roads, full } = STRESS_ZOOMS;
  let text =
    `${ZOOMED_OUT} Trails beside a road are among them. From zoom ${roads} traffic stress on roads and streets ` +
    `shows, protected lanes in the roadway with it, and from zoom ${full} footways and sidewalks. Further out than ` +
    `zoom ${min} nothing is drawn, and streets with no stress rating are not drawn.`;
  if (zoom !== null) text += ` The map is at zoom ${Math.floor(zoom)}.`;
  return text;
}

export function StressZoomNotes({ zoom, shown }: { zoom: number | null; shown: boolean }): ReactElement {
  const notice = stressZoomNotice(zoom, shown);
  return h(
    Fragment,
    null,
    notice && h("p", { className: "notice", role: "status" }, notice),
    h("p", { className: "hint" }, stressZoomHint(zoom)),
    h("p", { className: "hint" }, CAR_FREE_NOTE),
  );
}
