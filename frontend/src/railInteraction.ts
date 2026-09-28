/**
 * Hovering and tapping the rail stations: a hover shows the station's name
 * and lines; a tap (or click) opens the same with "Start here", "End here"
 * and "Add as via", which put the point on the station's elevator - the bike
 * entrance - or on the tapped elevator itself (owner, 2026-09-27).
 */
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, MapMouseEvent, PointLike } from "maplibre-gl";
import type { LonLat } from "./lib/geo.ts";
import { RAIL_LAYERS, railHitFrom } from "./lib/railLayer.ts";
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

export function attachRailInteraction(map: MapLibreMap, options: RailInteractionOptions) {
  const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "rail-popup", offset: 12 });
  let chosen: maplibregl.Popup | null = null;
  const canvas = map.getCanvas();

  const layers = () => [RAIL_LAYERS.elevators, RAIL_LAYERS.stations].filter((id) => map.getLayer(id));

  map.on("mousemove", RAIL_LAYERS.stations, (event) => {
    canvas.style.cursor = "pointer";
    if (chosen?.isOpen()) return;
    const hit = railHitFrom(event.features ?? []);
    const station = hit && options.station(hit.id);
    if (!station) return;
    hover.setLngLat(station.point).setDOMContent(summary(station, options, false)).addTo(map);
  });
  map.on("mouseleave", RAIL_LAYERS.stations, () => {
    canvas.style.cursor = "";
    hover.remove();
  });
  map.on("mouseenter", RAIL_LAYERS.elevators, () => {
    canvas.style.cursor = "pointer";
  });
  map.on("mouseleave", RAIL_LAYERS.elevators, () => {
    canvas.style.cursor = "";
  });

  /** A click on a station opens its choices; says whether it was one, so the map does not also add a point. */
  function handleClick(event: MapMouseEvent): boolean {
    const ids = layers();
    if (ids.length === 0) return false;
    const { x, y } = event.point;
    const box: [PointLike, PointLike] = [
      [x - TAP_SLOP, y - TAP_SLOP],
      [x + TAP_SLOP, y + TAP_SLOP],
    ];
    const hit = railHitFrom(map.queryRenderedFeatures(box, { layers: ids }));
    const station = hit && options.station(hit.id);
    if (!hit || !station) {
      // A tap beside an open station card closes it, and only that: it is
      // how a card is dismissed on a phone, not a request for a point.
      // MapView's click listener was registered before any card's own
      // close-on-click, so the card is still open when this runs.
      if (chosen?.isOpen()) {
        chosen.remove();
        return true;
      }
      return false;
    }
    hover.remove();
    chosen?.remove();
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
    const popup = new maplibregl.Popup({ className: "rail-popup", offset: 12, focusAfterOpen: true })
      .setLngLat(hit.elevator ?? station.point)
      .setDOMContent(content)
      .addTo(map);
    chosen = popup;
    return true;
  }

  return {
    handleClick,
    close() {
      hover.remove();
      chosen?.remove();
    },
  };
}
