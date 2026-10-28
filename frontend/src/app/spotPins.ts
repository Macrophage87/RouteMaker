// The pins of Go's tapped-spot card (GoSpotDialog.tsx; lib/spotNearby.ts; Stephen, 2026-10-28: "Let them show all on
// the map so you can select them", then "For restaurants and the like, label them"): each nearby place a real button
// on the map, its icon in a dot, and a named place's name beside it (15 px, haloed, as the map's street names); water,
// a restroom or a repair stand is its icon alone. Its accessible name is the place in full, kind and distance too.
// A press opens the place's card (lib/stopCard.ts), never a route by itself. The tapped spot itself is a small pin,
// not a control. The map frames the spot and the places in the part the card and the panel leave clear.
import { useEffect, useRef } from "react";
import { Marker, type Map as MapLibreMap } from "maplibre-gl";
import type { LonLat } from "../lib/geo.ts";
import { ICON_PATHS, type IconName } from "../lib/iconPaths.ts";
import { spotRowName, type SpotRow } from "../lib/spotNearby.ts";

type Padding = { top: number; bottom: number; left: number; right: number };

function iconSvg(name: IconName): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.innerHTML = ICON_PATHS[name];
  return svg;
}

/** The paddings shrunk together where they leave less than 120 px of map across or down. */
export function fitPadding(p: Padding, width: number, height: number): Padding {
  const fit = (a: number, b: number, size: number): [number, number] => {
    const room = Math.max(0, size - 120);
    if (a + b <= room) return [a, b];
    const k = room / (a + b);
    return [Math.floor(a * k), Math.floor(b * k)];
  };
  const [top, bottom] = fit(p.top, p.bottom, height);
  const [left, right] = fit(p.left, p.right, width);
  return { top, bottom, left, right };
}

/** A place's pin: a button, the icon in a dot, the label (if any) beside it. */
export function spotPinElement(row: SpotRow, onPress: (keyboard: boolean) => void): HTMLButtonElement {
  const element = document.createElement("button");
  element.type = "button";
  element.className = `spot-pin spot-pin-${row.kind}${row.label ? " spot-pin-named" : ""}`;
  element.setAttribute("aria-label", spotRowName(row));
  const dot = document.createElement("span");
  dot.className = "spot-pin-dot";
  dot.append(iconSvg(row.icon));
  element.append(dot);
  if (row.label) {
    const label = document.createElement("span");
    label.className = "spot-pin-label";
    label.setAttribute("aria-hidden", "true");
    label.textContent = row.label;
    element.append(label);
  }
  element.addEventListener("click", (event) => {
    // A press on a pin is not a tap on the map: it must not move the card to the pin's spot.
    event.stopPropagation();
    // From the keyboard (no pointer: detail 0), the focus goes into the card it opens.
    onPress(event.detail === 0);
  });
  element.addEventListener("dblclick", (event) => event.stopPropagation());
  return element;
}

/**
 * The pins while the card is open: `spot` and its `rows` (null while they load). `padding` is the map's part the
 * panel and the card leave clear, for the frame. Gone when the card closes (spot null).
 */
export function useSpotPins(getMap: () => MapLibreMap | null, spot: LonLat | null, rows: readonly SpotRow[] | null, onPick: (index: number, keyboard: boolean) => void, padding: () => Padding) {
  const pick = useRef(onPick);
  pick.current = onPick;
  const pad = useRef(padding);
  pad.current = padding;
  useEffect(() => {
    const map = getMap();
    if (!map || !spot) return;
    const markers: Marker[] = [];
    const here = document.createElement("span");
    here.className = "spot-here";
    here.setAttribute("aria-hidden", "true");
    markers.push(new Marker({ element: here, anchor: "bottom" }).setLngLat(spot).addTo(map));
    for (const [index, row] of (rows ?? []).entries()) {
      markers.push(new Marker({ element: spotPinElement(row, (keyboard) => pick.current(index, keyboard)), anchor: "center" }).setLngLat(row.point).addTo(map));
    }
    if (rows && rows.length > 0) {
      const points = [spot, ...rows.map((r) => r.point)];
      const lons = points.map((p) => p[0]);
      const lats = points.map((p) => p[1]);
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const { clientWidth: width, clientHeight: height } = map.getContainer();
      // Room on the right for the names, which run right of their pins; at least 120 px of map left each way.
      const p = fitPadding({ ...pad.current(), right: pad.current().right + 110 }, width, height);
      map.fitBounds(
        [
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        ],
        { padding: p, maxZoom: 17, duration: reduce ? 0 : 400 },
      );
    }
    return () => markers.forEach((marker) => marker.remove());
  }, [getMap, spot, rows]);
}
