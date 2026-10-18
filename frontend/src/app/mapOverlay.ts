// Map overlays drawn from outside MapView (v0.7.0: repair stands, places to see, bikeshare docks), as RideGroup
// does: wait for the map, draw, and undo on the way out; a tap gives a small card in words.
import { useEffect, useRef, useState } from "react";
import { Popup, type Map as MapLibreMap, type MapMouseEvent } from "maplibre-gl";

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

/** A small card on a tap, in words; the same facts are in the lists. `link`, where given, adds a web link under them. */
export function tapCard(
  map: MapLibreMap,
  layer: string,
  words: (id: string) => string[] | null,
  link?: (id: string) => { href: string; text: string; label: string } | null,
): () => void {
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
    const web = typeof id === "string" ? link?.(id) : null;
    if (web) {
      const a = document.createElement("a");
      a.href = web.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = web.text;
      a.setAttribute("aria-label", web.label);
      body.appendChild(a);
    }
    popup = new Popup({ closeButton: true, maxWidth: "260px", className: "rail-popup place-popup" }).setLngLat(event.lngLat).setDOMContent(body).addTo(map);
  };
  map.on("click", layer, onClick);
  return () => {
    map.off("click", layer, onClick);
    popup?.remove();
  };
}

export function setSource(map: MapLibreMap, id: string, data: object): void {
  const source = map.getSource(id) as { setData?: (d: object) => void } | undefined;
  if (source?.setData) source.setData(data);
  else map.addSource(id, { type: "geojson", data: data as never });
}
