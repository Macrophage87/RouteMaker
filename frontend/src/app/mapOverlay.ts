// Map overlays drawn from outside MapView (v0.7.0: repair stands, places to see, bikeshare docks), as RideGroup
// does: wait for the map, draw, and undo on the way out; a tap gives a small card in words, or a stop's card.
import { useEffect, useRef, useState } from "react";
import { Popup, type Map as MapLibreMap, type MapMouseEvent } from "maplibre-gl";
import type { LonLat } from "../lib/geo.ts";
import type { FeatureCards } from "../lib/mapGlue.ts";
import { fitPopup } from "../lib/popupFit.ts";
import { stopCardElement, type StopAction, type StopActionFor, type StopCardWords } from "../lib/stopCard.ts";

/** Run `draw` once the map is there (App sets it when MapView is ready), and again when its inputs change. */
export function useMap(getMap: () => MapLibreMap | null, draw: (map: MapLibreMap) => void | (() => void), deps: unknown[]) {
  const [map, setMap] = useState<MapLibreMap | null>(() => getMap());
  useEffect(() => {
    if (map) return;
    const id = window.setInterval(() => {
      const found = getMap();
      if (found) {
        setMap(found);
        window.clearInterval(id);
      }
    }, 500);
    return () => window.clearInterval(id);
  }, [map, getMap]);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  useEffect(() => {
    if (!map) return;
    return drawRef.current(map) ?? undefined;
    // The caller's inputs decide when it redraws.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, ...deps]);
}

/** A small card on a tap, in words; the same facts are in the lists. A stop's card is stopCard's, below. */
export function tapCard(map: MapLibreMap, layer: string | string[], words: (id: string) => string[] | null): () => void {
  let popup: Popup | null = null;
  const onClick = (event: MapMouseEvent & { features?: Array<{ properties?: Record<string, unknown> }> }) => {
    const id = event.features?.[0]?.properties?.id;
    const lines = typeof id === "string" ? words(id) : null;
    if (!lines) return;
    popup?.remove();
    const body = document.createElement("div");
    body.className = "place-card";
    for (const [i, line] of lines.entries()) {
      const p = document.createElement(i === 0 ? "strong" : "p");
      p.textContent = line;
      body.appendChild(p);
    }
    popup = new Popup({ closeButton: true, maxWidth: "260px", className: "rail-popup place-popup" }).setLngLat(event.lngLat).setDOMContent(body).addTo(map);
  };
  const layers = typeof layer === "string" ? [layer] : layer;
  map.on("click", layers, onClick);
  return () => {
    map.off("click", layers, onClick);
    popup?.remove();
  };
}

// --- Stops' cards (lib/stopCard.ts): food, places to see, repair, and the lettered pins ----------------------

/** The stop card open now, if any: one at a time, whichever opened it, and the layer whose dot opened it. */
let stopPopup: Popup | null = null;
let stopFrom: string | null = null;
/** The layers whose points open a stop card, for MapView's main click (stopCards). */
const stopLayers = new Set<string>();

/** The map's part the panel does not cover, and whether motion is reduced (App sets them; lib/popupFit.ts). */
let stopFrame: { padding: () => { top: number; left: number; bottom: number; right: number }; instant: () => boolean } | null = null;
export function setStopCardFrame(frame: typeof stopFrame) {
  stopFrame = frame;
}

/** Close the stop card, if one is open (only if `layer`'s dot opened it, when given). */
export function closeStopCard(layer?: string) {
  if (layer !== undefined && stopFrom !== layer) return;
  stopPopup?.remove();
  stopPopup = null;
}

/** Open a stop's card at `point`, kept clear of the panel; `focus` moves the focus into it (a keyboard pick). */
export function openStopCard(map: MapLibreMap, point: LonLat, words: StopCardWords, action: StopAction | null, focus = false, from: string | null = null) {
  closeStopCard();
  // A keyboard pick: the focus goes back where it was (the list's row, the sheet) when the card closes.
  const returnTo = focus && document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
  const body = stopCardElement(words, action, () => closeStopCard());
  const popup = new Popup({ closeButton: true, maxWidth: "260px", className: "rail-popup place-popup", offset: 12, focusAfterOpen: focus })
    .setLngLat(point)
    .setDOMContent(body)
    .addTo(map);
  const element = popup.getElement();
  // On the whole card, so Escape works from its close button too.
  element?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeStopCard();
  });
  popup.on("close", () => {
    if (stopPopup === popup) stopPopup = null;
    const lost = document.activeElement === document.body || !document.activeElement?.isConnected;
    if (lost && returnTo?.isConnected) returnTo.focus();
  });
  stopPopup = popup;
  stopFrom = from;
  if (element && stopFrame) fitPopup(map, element, stopFrame.padding(), stopFrame.instant());
}

/**
 * A layer's points as stops: a press opens the point's card (what's there, the website, Route here or Add as stop),
 * never a route by itself (Stephen 2026-10-19: "don't auto route"). `at` gives a point's place and words.
 */
export function stopCard(
  map: MapLibreMap,
  layer: string,
  at: (id: string) => { point: LonLat; words: StopCardWords } | null,
  actionFor: StopActionFor,
): () => void {
  const onClick = (event: MapMouseEvent & { features?: Array<{ properties?: Record<string, unknown> }> }) => {
    const id = event.features?.[0]?.properties?.id;
    const found = typeof id === "string" ? at(id) : null;
    if (!found) return;
    openStopCard(map, found.point, found.words, actionFor(found.point, found.words.title), false, layer);
  };
  map.on("click", layer, onClick);
  stopLayers.add(layer);
  return () => {
    map.off("click", layer, onClick);
    stopLayers.delete(layer);
    closeStopCard(layer);
  };
}

/** The stop cards as MapView's main click sees them (lib/mapGlue.ts FeatureCards): a press on one is the card's. */
export function stopCards(map: MapLibreMap): FeatureCards {
  return {
    open: () => stopPopup !== null && stopPopup.isOpen(),
    hits: ({ x, y }) => {
      const layers = [...stopLayers].filter((layer) => map.getLayer(layer) && map.getLayoutProperty(layer, "visibility") !== "none");
      if (layers.length === 0) return false;
      const slop = 6;
      return map.queryRenderedFeatures([[x - slop, y - slop], [x + slop, y + slop]], { layers }).length > 0;
    },
  };
}

export function setSource(map: MapLibreMap, id: string, data: object): void {
  const source = map.getSource(id) as { setData?: (d: object) => void } | undefined;
  if (source?.setData) source.setData(data);
  else map.addSource(id, { type: "geojson", data: data as never });
}
