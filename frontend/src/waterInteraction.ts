/**
 * Tapping or clicking a water or restroom icon: a small card with what it is
 * (drinking or untreated water; a flush, basic or unmapped restroom), its
 * name, the details OSM gives (free or fee, wheelchair access, a bottle filler,
 * the season and hours) and the standing caution that it is volunteers'
 * mapping.
 *
 * As federalInteraction.ts, the card is information beside the map's own
 * click, not instead of it: the click still goes on to place a point, which
 * here is often what the rider wants (a stop at the fountain). It closes on the
 * next map click, on its own button and on Escape, does nothing while the
 * layer is off, and holds back while another card is open. The same points
 * are listed in words along the route (lib/waterLegend.ts), so nothing here is
 * the only way to them.
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import { WATER_CAUTION, WATER_LAYER, waterDetails, waterKindLabel, type WaterPoint } from "./lib/waterRestrooms.ts";

export interface WaterInteractionOptions {
  visible(): boolean;
  otherPopupOpen(): boolean;
  point(id: string): WaterPoint | undefined;
}

/** Pixels around a tap that still count as on the icon. */
const TAP_SLOP = 6;

/** The card's contents, as DOM (a test builds it too). */
export function waterCardElement(p: WaterPoint): HTMLElement {
  const root = document.createElement("div");
  root.className = "water-popup";
  const title = document.createElement("strong");
  title.className = "water-kind";
  title.textContent = waterKindLabel(p);
  root.append(title);
  if (p.name) {
    const name = document.createElement("p");
    name.className = "water-name";
    name.textContent = p.name;
    root.append(name);
  }
  for (const line of waterDetails(p)) {
    const detail = document.createElement("p");
    detail.className = "water-detail";
    detail.textContent = line;
    root.append(detail);
  }
  const caution = document.createElement("p");
  caution.className = "water-caution";
  caution.textContent = WATER_CAUTION;
  root.append(caution);
  return root;
}

export function attachWaterInteraction(map: MapLibreMap, options: WaterInteractionOptions) {
  let popup: maplibregl.Popup | null = null;
  const close = () => {
    popup?.remove();
    popup = null;
  };
  const onClick = (event: maplibregl.MapMouseEvent) => {
    close();
    if (!options.visible() || options.otherPopupOpen() || !map.getLayer(WATER_LAYER)) return;
    if (event.originalEvent.target !== map.getCanvas()) return;
    const { x, y } = event.point;
    const box: [[number, number], [number, number]] = [
      [x - TAP_SLOP, y - TAP_SLOP],
      [x + TAP_SLOP, y + TAP_SLOP],
    ];
    const feature = map.queryRenderedFeatures(box, { layers: [WATER_LAYER] })[0];
    const id = (feature?.properties as { id?: string } | undefined)?.id;
    const p = id ? options.point(id) : undefined;
    if (!p) return;
    const content = waterCardElement(p);
    content.addEventListener("keydown", (key) => {
      if (key.key === "Escape") close();
    });
    popup = new maplibregl.Popup({ className: "rail-popup water-card", offset: 10, focusAfterOpen: false, closeOnClick: true })
      .setLngLat([p.lon, p.lat])
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
