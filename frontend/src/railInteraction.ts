/**
 * Hovering and tapping the rail stations: a hover shows the station's name
 * and lines; a tap (or click) opens the same with "Start here", "End here"
 * and "Add as stop", which put the point on the station's elevator - the bike
 * entrance - or on the tapped elevator itself (owner, 2026-09-27).
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, PointLike } from "maplibre-gl";
import type { LonLat } from "./lib/geo.ts";
import { focusBackTarget } from "./lib/mapGlue.ts";
import { RailCards } from "./lib/railCards.ts";
import { RAIL_LAYERS, STATION_MIN_ZOOM, railHitFrom, stationNear, type RailHit } from "./lib/railLayer.ts";
import {
  bikeEntrance,
  entranceNote,
  lineStyle,
  linesLabel,
  stationRoles,
  visibleLines,
  type RailVisibility,
  type Station,
  type StationRole,
} from "./lib/railStations.ts";

export interface RailInteractionOptions {
  station(id: string): Station | undefined;
  /** Every station, for the tap that the rendered-feature query misses (stationAt). */
  stations: readonly Station[];
  pennColour: string;
  visibility(): RailVisibility;
  pointCount(): number;
  onStationPoint(role: StationRole, point: LonLat): void;
}

const ROLE_TEXT: Record<StationRole, string> = {
  start: "Start here",
  end: "End here",
  via: "Add as stop",
};
/** Pixels around a tap that still count as on the station. */
const TAP_SLOP = 6;

function summary(station: Station, options: RailInteractionOptions, elevatorTapped: boolean): HTMLElement {
  const root = document.createElement("div");
  root.className = "station-popup";
  const name = document.createElement("strong");
  name.className = "station-name";
  name.textContent = station.name;
  root.append(name);
  const lines = visibleLines(station, options.visibility());
  const row = document.createElement("div");
  row.className = "station-lines";
  for (const line of lines) {
    const swatch = document.createElement("span");
    swatch.className = "station-swatch";
    swatch.style.backgroundColor = lineStyle(line, options.pennColour).color;
    swatch.setAttribute("aria-hidden", "true");
    row.append(swatch);
  }
  row.append(document.createTextNode(linesLabel(lines)));
  root.append(row);
  const entrance = document.createElement("p");
  entrance.className = "station-entrance";
  entrance.textContent = elevatorTapped ? "Elevator: a way in with a bike." : entranceNote(bikeEntrance(station).kind);
  root.append(entrance);
  return root;
}

/** A station found under the pointer: the hit (its elevator, if one was hit) and the station. */
export interface StationFound {
  hit: RailHit;
  station: Station;
}

/**
 * The stations' hover card and tap card. MapView decides, for each hover and
 * click, whether the pointer is on a station, the route line or the map
 * (mapGlue.ts pointerTarget and mapClickAction), so that the line's handle
 * and a station's card never both answer the same pointer; this module finds
 * the station and draws its cards, whose state is RailCards (railCards.ts).
 */
export function attachRailInteraction(map: MapLibreMap, options: RailInteractionOptions) {
  // The hover card has nothing to press; the pointer goes through it (.rail-hover).
  const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "rail-popup rail-hover", offset: 12 });
  const canvas = map.getCanvas();

  const layers = () => [RAIL_LAYERS.elevators, RAIL_LAYERS.stations].filter((id) => map.getLayer(id));

  /** The station (or elevator) within the tap slop of a pointer at `point`, if any. */
  function stationAt(point: { x: number; y: number }): StationFound | null {
    const ids = layers();
    if (ids.length === 0) return null;
    const { x, y } = point;
    const box: [PointLike, PointLike] = [
      [x - TAP_SLOP, y - TAP_SLOP],
      [x + TAP_SLOP, y + TAP_SLOP],
    ];
    let hit = railHitFrom(map.queryRenderedFeatures(box, { layers: ids }));
    // The query reads what the last frame placed, and with the stress overlay
    // on a cold page it missed a station right under the tap in 16 of 46
    // samples for about a second (MERGE-TILES re-check SHOULD_FIX 1), so the
    // tap added a via instead of opening the card. The stations' own points,
    // projected, do not depend on the frame.
    if (!hit && map.getLayer(RAIL_LAYERS.stations) && map.getZoom() >= STATION_MIN_ZOOM) {
      hit = stationNear(options.stations, options.visibility(), (p) => map.project(p), point, TAP_SLOP);
    }
    const station = hit && options.station(hit.id);
    return hit && station ? { hit, station } : null;
  }

  const cards = new RailCards<StationFound>({
    key: ({ hit }) => `${hit.id}|${hit.elevator?.join(",") ?? ""}`,
    showHover({ hit, station }, lineHint) {
      const content = summary(station, options, hit.elevator !== undefined);
      if (lineHint) {
        // The route runs over this station: a press that drags takes the line.
        const hint = document.createElement("p");
        hint.className = "station-line-hint";
        hint.textContent = "Click for the station; drag to reshape the route.";
        content.append(hint);
      }
      hover
        .setLngLat(hit.elevator ?? station.point)
        .setDOMContent(content)
        .addTo(map);
    },
    hideHover() {
      hover.remove();
    },
    openCard({ hit, station }) {
      // Where the focus goes back to on Escape, as for a via's Remove.
      const returnTo = document.activeElement;
      const point: LonLat = hit.elevator ?? bikeEntrance(station).point;
      const content = summary(station, options, hit.elevator !== undefined);
      const actions = document.createElement("div");
      actions.className = "station-actions";
      for (const role of stationRoles(options.pointCount())) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = ROLE_TEXT[role];
        button.addEventListener("click", () => {
          popup.remove();
          options.onStationPoint(role, point);
        });
        actions.append(button);
      }
      content.append(actions);
      content.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        popup.remove();
        const usable = (element: Element) =>
          element instanceof HTMLElement && element.isConnected && element !== document.body;
        const target = focusBackTarget<Element>(returnTo, usable, canvas);
        if (target instanceof HTMLElement) target.focus();
      });
      // Not closed by MapLibre on a map click: MapView's click closes it, so
      // that the same click does not also add a point (mapClickAction).
      const popup = new maplibregl.Popup({ className: "rail-popup", offset: 12, focusAfterOpen: true, closeOnClick: false })
        .setLngLat(hit.elevator ?? station.point)
        .setDOMContent(content)
        .addTo(map);
      return popup;
    },
  });

  return {
    stationAt,
    /** The hover card for `found` (with the line hint), or none. */
    showHover: (found: StationFound | null, lineHint = false) => cards.hover(found, lineHint),
    cardOpen: () => cards.cardOpen(),
    openCard: (found: StationFound) => cards.open(found),
    closeCard: () => cards.close(),
    close() {
      cards.hover(null);
      cards.close();
    },
  };
}
