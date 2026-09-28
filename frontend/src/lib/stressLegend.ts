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

/** The notice for the zoom the map is at, when the overlay is shown; null when there is none. */
export function stressZoomNotice(zoom: number | null, shown: boolean): string | null {
  if (zoom === null || !shown) return null;
  if (zoom < STRESS_ZOOMS.min) return "Zoom in to see the trails and traffic stress.";
  if (zoom < STRESS_ZOOMS.roads) return "Zoom in to see traffic stress on roads. Zoomed out, only the trails are shown.";
  return null;
}

/** The standing note on what is drawn at which zoom. */
export function stressZoomHint(zoom: number | null): string {
  const { min, roads, full } = STRESS_ZOOMS;
  let text =
    `Zoomed out, only the traffic-free trails and paths are drawn. Traffic stress on roads and streets shows ` +
    `from zoom ${roads}, and footways and sidewalks from zoom ${full}. Further out than zoom ${min} nothing is ` +
    `drawn, and streets with no stress rating are not drawn.`;
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
  );
}
