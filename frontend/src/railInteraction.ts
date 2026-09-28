/**
 * Hovering and tapping the rail stations: a hover shows the station's name
 * and lines; a tap (or click) opens the same with "Start here", "End here"
 * and "Add as via", which put the point on the station's elevator - the bike
 * entrance - or on the tapped elevator itself (owner, 2026-09-27).
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, PointLike } from "maplibre-gl";
import type { LonLat } from "./lib/geo.ts";
import { RAIL_LAYERS, railHitFrom, type RailHit } from "./lib/railLayer.ts";
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
  pennColour: string;
  visibility(): RailVisibility;
  pointCount(): number;
  onStationPoint(role: StationRole, point: LonLat): void;
}

const ROLE_TEXT: Record<StationRole, string> = {
  start: "Start here",
  end: "End here",
  via: "Add as via",
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
 * the station and shows its cards.
 */
export function attachRailInteraction(map: MapLibreMap, options: RailInteractionOptions) {
  const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "rail-popup rail-hover", offset: 12 });
  // What the hover card shows ("" for nothing), so an unchanged hover is not built again.
  let hovered = "";
  let chosen: maplibregl.Popup | null = null;

  const layers = () => [RAIL_LAYERS.elevators, RAIL_LAYERS.stations].filter((id) => map.getLayer(id));
  const cardOpen = () => chosen?.isOpen() ?? false;

  /** The station (or elevator) within the tap slop of a pointer at `point`, if any. */
  function stationAt(point: { x: number; y: number }): StationFound | null {
    const ids = layers();
    if (ids.length === 0) return null;
    const { x, y } = point;
    const box: [PointLike, PointLike] = [
      [x - TAP_SLOP, y - TAP_SLOP],
      [x + TAP_SLOP, y + TAP_SLOP],
    ];
    const hit = railHitFrom(map.queryRenderedFeatures(box, { layers: ids }));
    const station = hit && options.station(hit.id);
    return hit && station ? { hit, station } : null;
  }

  /** The hover card for `found`, or none; not while a station's card is open. */
  function showHover(found: StationFound | null): void {
    const key = found && !cardOpen() ? `${found.hit.id}|${found.hit.elevator?.join(",") ?? ""}` : "";
    if (key === hovered) return;
    hovered = key;
    if (!found || key === "") {
      hover.remove();
      return;
    }
    hover
      .setLngLat(found.hit.elevator ?? found.station.point)
      .setDOMContent(summary(found.station, options, found.hit.elevator !== undefined))
      .addTo(map);
  }

  /** Close the station's card, if one is open; whether one was. */
  function closeCard(): boolean {
    const open = cardOpen();
    chosen?.remove();
    chosen = null;
    return open;
  }

  /** Open the card for a tapped station, with its Start here / End here / Add as via. */
  function openCard({ hit, station }: StationFound): void {
    showHover(null);
    closeCard();
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
      if (event.key === "Escape") popup.remove();
    });
    // Not closed by MapLibre on a map click: MapView's click closes it, so
    // that the same click does not also add a point (mapClickAction).
    const popup = new maplibregl.Popup({ className: "rail-popup", offset: 12, focusAfterOpen: true, closeOnClick: false })
      .setLngLat(hit.elevator ?? station.point)
      .setDOMContent(content)
      .addTo(map);
    chosen = popup;
  }

  return {
    stationAt,
    showHover,
    cardOpen,
    openCard,
    closeCard,
    close() {
      showHover(null);
      closeCard();
    },
  };
}
