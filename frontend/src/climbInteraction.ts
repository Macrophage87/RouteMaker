/**
 * Tapping or clicking a climb's summit marker: a small card with the climb in words ("Category 3
 * climb, 2.1 miles (3.4 km) at 4.6%"), what it gains, its surface and trail, and the caution that
 * the grade is an average over coarse elevation data.
 *
 * As waterInteraction.ts, the card is information beside the map's own click, not instead of it: the
 * click still goes on to place a point. It closes on the next map click and on Escape, does nothing
 * while the layer is off, and holds back while another card is open. The climbs the route rides are
 * listed in words (lib/climbsLegend.ts), so nothing here is the only way to them.
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import { CLIMBS_MARKER_LAYER, climbCard, type Climb } from "./lib/climbs.ts";

export interface ClimbInteractionOptions {
  visible(): boolean;
  otherPopupOpen(): boolean;
  climb(id: string): Climb | undefined;
}

/** Pixels around a tap that still count as on the marker. */
const TAP_SLOP = 6;

/** The card's contents, as DOM; what it says is climbCard's (tested there). */
export function climbCardElement(c: Climb): HTMLElement {
  const card = climbCard(c);
  const root = document.createElement("div");
  root.className = "climb-popup";
  const title = document.createElement("strong");
  title.className = "climb-title";
  title.textContent = card.title;
  root.append(title);
  for (const line of card.details) {
    const detail = document.createElement("p");
    detail.className = "climb-detail";
    detail.textContent = line;
    root.append(detail);
  }
  const caution = document.createElement("p");
  caution.className = "climb-caution";
  caution.textContent = card.caution;
  root.append(caution);
  return root;
}

export function attachClimbInteraction(map: MapLibreMap, options: ClimbInteractionOptions) {
  let popup: maplibregl.Popup | null = null;
  const close = () => {
    popup?.remove();
    popup = null;
  };
  const onClick = (event: maplibregl.MapMouseEvent) => {
    close();
    if (!options.visible() || options.otherPopupOpen() || !map.getLayer(CLIMBS_MARKER_LAYER)) return;
    if (event.originalEvent.target !== map.getCanvas()) return;
    const { x, y } = event.point;
    const box: [[number, number], [number, number]] = [
      [x - TAP_SLOP, y - TAP_SLOP],
      [x + TAP_SLOP, y + TAP_SLOP],
    ];
    const feature = map.queryRenderedFeatures(box, { layers: [CLIMBS_MARKER_LAYER] })[0];
    const id = (feature?.properties as { id?: string } | undefined)?.id;
    const c = id ? options.climb(id) : undefined;
    if (!c) return;
    const content = climbCardElement(c);
    content.addEventListener("keydown", (key) => {
      if (key.key === "Escape") close();
    });
    popup = new maplibregl.Popup({ className: "rail-popup climb-card", offset: 12, focusAfterOpen: false, closeOnClick: true })
      .setLngLat([c.lon, c.lat])
      .setDOMContent(content)
      .addTo(map);
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") close();
  };
  map.on("click", onClick);
  window.addEventListener("keydown", onKey);
  return {
    close,
    open: () => popup !== null,
    detach() {
      close();
      map.off("click", onClick);
      window.removeEventListener("keydown", onKey);
    },
  };
}
