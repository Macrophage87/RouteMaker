import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, Marker, Popup } from "maplibre-gl";
import { Protocol } from "pmtiles";
// MapLibre 6 ships its worker as a separate module and finds it next to its own
// file by `import.meta.url`, which a bundle does not preserve; Vite builds it
// as an asset of its own here and the map is told where it is.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { COVERAGE_BBOX, type LonLat } from "./lib/geo.ts";
import {
  BASEMAP_SOURCE_ID,
  MAP_ATTRIBUTION,
  OPENING_ZOOM,
  STRESS_SOURCE_ID,
  buildStyle,
} from "./lib/mapStyle.ts";
import type { RouteResponse } from "./lib/api.ts";
import {
  ROUTE_BLUE,
  ROUTE_CASING_PLAIN,
  ROUTE_CASING_WIDTH,
  ROUTE_LINE_WIDTH,
  sectionFeatures,
} from "./lib/routeColours.ts";
import { subscribePalette } from "./stressStyle.js";
import {
  addStressOverlay,
  focusBackTarget,
  markerDeps,
  popupsOpen,
  pressGrab,
  runClick,
  ROUTE_STRESS_SOURCE_ID,
  runHover,
  setRouteSections,
  setStressPalette,
  setStressVisibility,
  setStressWhen,
} from "./lib/mapGlue.ts";
import { dragPreview, legOfSegment, nearestOnPath } from "./lib/lineEdit.ts";
import { LineGesture } from "./lib/lineGesture.ts";
import { PENN_COLOUR, RAIL_STATIONS, stationById } from "./lib/railData.ts";
import { addRailStations, setRailVisibility } from "./lib/railLayer.ts";
import type { RailVisibility, StationRole } from "./lib/railStations.ts";
import { attachRailInteraction, type StationFound } from "./railInteraction.ts";
import { stressProbe } from "./lib/stressProtocol.ts";
import type { When } from "./lib/dials.ts";
import {
  groupJunctions,
  groupLabel,
  junctionItems,
  junctionsOnMap,
  warningIconSvg,
  ICON_PX,
  type JunctionGroup,
  type JunctionItem,
} from "./lib/intersectionMarkers.ts";

export type StressAvailability = "checking" | "available" | "unavailable";

/** The route as it can be dragged: its line, where each leg ends in it, and the points it was planned through. */
export interface LineEdit {
  path: LonLat[];
  ends: number[];
  points: LonLat[];
}

/** Pixels on each side of the map that the panel covers. */
export interface Frame {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface Props {
  points: LonLat[];
  route: RouteResponse | null;
  stale: boolean;
  stressVisible: boolean;
  /** The ride time the overlay follows, for the roads closed to cars at set times (lib/rideTime.ts). */
  when: When;
  /** Screen space the panel covers, so a route is framed in what is left. */
  framePadding: () => Frame;
  onStressAvailability: (availability: StressAvailability) => void;
  onMapClick: (point: LonLat) => void;
  onMovePoint: (index: number, point: LonLat) => void;
  /** The route line, when it is the current points' route and can be dragged; null otherwise. */
  lineEdit: LineEdit | null;
  /** The line was dragged (or clicked) to `point` from leg `leg` of the route through `points`. */
  onLineDrop: (leg: number, point: LonLat, points: LonLat[]) => void;
  /** Remove the point at `index` (a via's Remove on the map). */
  onRemovePoint: (index: number) => void;
  /** Changes when the markers must be put back on the points as they are. */
  markerReset: number;
  /** The junction the route summary's list asked the map to show (nonce: again), or null. */
  junctionFocus: { index: number; nonce: number } | null;
  onReady: (map: MapLibreMap) => void;
  onCanvasFocus: (focused: boolean) => void;
  /** Which rail stations show (the panel's toggles). */
  rail: RailVisibility;
  /** A station's Start here / End here / Add as via, with its bike entrance. */
  onStationPoint: (role: StationRole, point: LonLat) => void;
}

// One protocol for the page. MapLibre 4+ runs a custom protocol's handler on
// the page's own thread, so the archive's range requests carry this page as
// their Referer - which is what the edge's /basemap/* guard checks.
let protocolRegistered = false;
function registerPmtiles(): void {
  if (protocolRegistered) return;
  maplibregl.setWorkerUrl(maplibreWorkerUrl);
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  protocolRegistered = true;
}

const DC_CENTRE: LonLat = [-77.03, 38.9];
const ROUTE_SOURCE = "route";
/** The route's sections by traffic stress (lib/routeColours.ts). */
const ROUTE_STRESS_SOURCE = ROUTE_STRESS_SOURCE_ID;
/** The handle and the dashed preview of a drag of the line. */
const EDIT_SOURCE = "route-edit";
/** How far from the line's centre a mouse, or a finger, still grabs it. */
const MOUSE_HIT_PX = 8;
const TOUCH_HIT_PX = 18;
/** Near a marker, the marker is what the pointer is on, not the line. */
const MARKER_CLEAR_PX = 14;
/** After a drag, the click the browser may still send is not a new point. */
const CLICK_AFTER_DRAG_MS = 400;
/** The buzz when a held finger picks the line up. */
const PICK_UP_BUZZ_MS = 15;
const MAX_BOUNDS_PAD = 0.4;
/** How long an unanswered stress endpoint is left before it is asked again. */
const STRESS_RECHECK_MS = 60_000;

function pointLabel(index: number, count: number): { text: string; name: string; kind: string } {
  if (index === 0) return { text: "A", name: "Start", kind: "start" };
  if (index === count - 1 && count > 1) return { text: "B", name: "End", kind: "end" };
  return { text: String(index), name: `Via point ${index}`, kind: "via" };
}

type EditFeature =
  | { type: "Feature"; properties: object; geometry: { type: "LineString"; coordinates: LonLat[] } }
  | { type: "Feature"; properties: object; geometry: { type: "Point"; coordinates: LonLat } };

/** The drag's handle (a point) and its preview (dashed lines), as map data. */
function editData(handle: LonLat | null, preview: LonLat[][]): { type: "FeatureCollection"; features: EditFeature[] } {
  const features: EditFeature[] = preview.map((coordinates) => ({
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates },
  }));
  if (handle) features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: handle } });
  return { type: "FeatureCollection", features };
}

/** Is the route's extent already on screen, outside the panel? If not, the map moves to it. */
function routeInView(map: MapLibreMap, coordinates: LonLat[], padding: Frame): boolean {
  const canvas = map.getCanvas();
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  return coordinates.every((c) => {
    const p = map.project(c);
    return (
      p.x >= padding.left && p.x <= width - padding.right && p.y >= padding.top && p.y <= height - padding.bottom
    );
  });
}


export function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const popup = useRef<Popup | null>(null);
  // The route's junction markers (OWNER-DECISIONS 172) and the card one of them has open.
  const junctionMarkers = useRef<{ group: JunctionGroup; marker: Marker }[]>([]);
  // The route's junctions, which the markers are drawn from at each zoom.
  const junctionList = useRef<JunctionItem[]>([]);
  const junctionCard = useRef<Popup | null>(null);
  // The hover handle as last drawn (null: none), so an unchanged answer is
  // not drawn again; anything else that redraws the edit layer resets it.
  const hoverShown = useRef<LonLat | null>(null);
  // Where the focus was before a via's Remove took it, to go back to on Escape.
  const popupReturn = useRef<Element | null>(null);
  /** Close a via's Remove popup, if one is open; whether one was. */
  const closePopup = (returnFocus: boolean): boolean => {
    const open = popup.current;
    if (!open) return false;
    popup.current = null;
    open.remove();
    const back = popupReturn.current;
    popupReturn.current = null;
    if (returnFocus) {
      const usable = (element: Element) =>
        element instanceof HTMLElement && element.isConnected && element !== document.body;
      const target = focusBackTarget<Element>(back, usable, mapRef.current?.getCanvas() ?? null);
      if (target instanceof HTMLElement) target.focus();
    }
    return true;
  };
  const loaded = useRef(false);
  // The first route shown (a shared link, usually) is framed; after that the
  // map moves only when a route leaves the visible part of the map.
  const fitted = useRef(false);
  const callbacks = useRef(props);
  callbacks.current = props;

  // The map itself, once.
  useEffect(() => {
    if (!container.current) return;
    registerPmtiles();
    const origin = window.location.origin;
    const basemapLayers = protomapsLayers(BASEMAP_SOURCE_ID, namedFlavor("light"), { lang: "en" });
    const [west, south, east, north] = COVERAGE_BBOX;
    const map = new maplibregl.Map({
      container: container.current,
      style: buildStyle(origin, basemapLayers) as maplibregl.StyleSpecification,
      center: DC_CENTRE,
      zoom: OPENING_ZOOM,
      minZoom: 7,
      maxZoom: 18,
      maxBounds: [
        [west - MAX_BOUNDS_PAD, south - MAX_BOUNDS_PAD],
        [east + MAX_BOUNDS_PAD, north + MAX_BOUNDS_PAD],
      ],
      // One entry, OpenStreetMap first (mapStyle.ts says why).
      attributionControl: { compact: true, customAttribution: MAP_ATTRIBUTION },
      cooperativeGestures: false,
    });
    mapRef.current = map;
    let disposed = false;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    // Both scales, miles and feet over kilometres and metres (OWNER-DECISIONS 85):
    // a bottom corner stacks its controls upwards, so the one added last is on top.
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
    const canvas = map.getCanvas();
    canvas.setAttribute("aria-label", "Map. Use arrow keys to pan and plus or minus to zoom.");
    canvas.addEventListener("focus", () => callbacks.current.onCanvasFocus(true));
    canvas.addEventListener("blur", () => callbacks.current.onCanvasFocus(false));

    // The style package can name an icon the pinned sprite sheet predates
    // (basemaps-assets is pinned by commit in scripts/fetch_basemap.sh). A
    // blank stand-in keeps the label and quiets the console.
    map.setMissingStyleImageResolver((id) => {
      if (!map.hasImage(id)) map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
    });

    // Dragging the route line (lineEdit.ts, lineGesture.ts). The handle and
    // the preview are map layers; the gesture follows the pointer on the
    // window, so a drag that leaves the map still ends.
    const showEdit = (handle: LonLat | null, preview: LonLat[][] = []) => {
      hoverShown.current = preview.length === 0 ? handle : null;
      (map.getSource(EDIT_SOURCE) as GeoJSONSource | undefined)?.setData(editData(handle, preview));
    };
    // The rail stations' hover card and tap card (railInteraction.ts), once
    // their layers are on the map.
    let rail: ReturnType<typeof attachRailInteraction> | null = null;
    const anyPopupOpen = () => popupsOpen(popup.current, rail);
    /** The station under a pointer at `point` on the canvas, if any. */
    const stationAt = (point: { x: number; y: number }): StationFound | null => rail?.stationAt(point) ?? null;
    /** The leg and the spot on the line under a pointer at `point`, if it is on the line. */
    const lineAt = (point: { x: number; y: number }, tolerance: number) => {
      const edit = callbacks.current.lineEdit;
      if (!edit) return null;
      const { lng, lat } = map.unproject([point.x, point.y]);
      const near = nearestOnPath(edit.path, [lng, lat]);
      if (!near) return null;
      const at = map.project(near.point);
      if (Math.hypot(at.x - point.x, at.y - point.y) > tolerance) return null;
      for (const p of edit.points) {
        const marker = map.project(p);
        if (Math.hypot(marker.x - at.x, marker.y - at.y) < MARKER_CLEAR_PX) return null;
      }
      return { leg: legOfSegment(edit.ends, near.segment), at: near.point, points: edit.points };
    };
    let grabbed: { leg: number; at: LonLat; points: LonLat[] } | null = null;
    let panStopped = false;
    let clickSuppressedUntil = 0;
    const gesture = new LineGesture({
      onPickUp: () => {
        // A held finger: the map stops panning under it, and the handle and
        // the preview show where the line was picked up, with a short buzz
        // where the phone has one (Android; iOS Safari has no vibrate).
        try {
          navigator.vibrate?.(PICK_UP_BUZZ_MS);
        } catch {
          // A browser that refuses is no reason to stop the drag.
        }
        panStopped = true;
        map.dragPan.disable();
        map.touchZoomRotate.disable();
        if (grabbed) showEdit(grabbed.at, dragPreview(grabbed.points, grabbed.leg, grabbed.at));
      },
    });
    const endDrag = () => {
      showEdit(null);
      canvas.style.cursor = "";
      if (panStopped) {
        panStopped = false;
        map.dragPan.enable();
        map.touchZoomRotate.enable();
      }
    };
    const local = (clientX: number, clientY: number) => {
      const box = canvas.getBoundingClientRect();
      return { x: clientX - box.left, y: clientY - box.top };
    };
    const lonLatAt = (point: { x: number; y: number }): LonLat => {
      const { lng, lat } = map.unproject([point.x, point.y]);
      return [lng, lat];
    };
    const follow = (point: { x: number; y: number }): boolean => {
      if (!grabbed || gesture.move(point.x, point.y) !== "drag") return false;
      const cursor = lonLatAt(point);
      showEdit(cursor, dragPreview(grabbed.points, grabbed.leg, cursor));
      canvas.style.cursor = "grabbing";
      return true;
    };
    /** The press ended at `point`, or was called off (null). */
    const finish = (point: { x: number; y: number } | null) => {
      const wasDragging = gesture.dragging;
      const result = point ? gesture.release() : "none";
      gesture.cancel();
      const drop = grabbed;
      grabbed = null;
      endDrag();
      if (wasDragging) clickSuppressedUntil = performance.now() + CLICK_AFTER_DRAG_MS;
      if (result === "drop" && drop && point) callbacks.current.onLineDrop(drop.leg, lonLatAt(point), drop.points);
    };

    // Hovering: a handle on the line where a press would grab it, or a
    // station's hover card where a click would open its card - one or the
    // other, as pointerTarget (mapGlue.ts) decides for the press and click.
    let hoverFrame = 0;
    let hoverPoint: { x: number; y: number } | null = null;
    map.on("mousemove", (event) => {
      if (gesture.active) return;
      hoverPoint = event.originalEvent.target === canvas ? event.point : null;
      if (hoverFrame) return;
      hoverFrame = requestAnimationFrame(() => {
        hoverFrame = 0;
        if (gesture.active) return;
        const under = hoverPoint
          ? { station: stationAt(hoverPoint), line: lineAt(hoverPoint, MOUSE_HIT_PX) }
          : { station: null, line: null };
        runHover(under, anyPopupOpen(), { handle: hoverShown.current, cursor: canvas.style.cursor }, {
          drawHandle: (at) => showEdit(at as LonLat | null),
          stationHover: (station, lineHint) => rail?.showHover(station, lineHint),
          setCursor: (cursor) => {
            canvas.style.cursor = cursor;
          },
        });
      });
    });
    const onCanvasLeave = () => {
      hoverPoint = null;
      rail?.showHover(null);
      if (!gesture.active) endDrag();
    };
    canvas.addEventListener("mouseleave", onCanvasLeave);
    map.on("mousedown", (event) => {
      if (event.originalEvent.button !== 0 || event.originalEvent.target !== canvas) return;
      const hit = grabAt(event.point, MOUSE_HIT_PX);
      if (!hit) return;
      // The map does not pan: this press is the line's.
      event.preventDefault();
      grabbed = hit;
      gesture.press("mouse", event.point.x, event.point.y);
    });
    /**
     * The line under a press at `point`, if the press is the line's: near the
     * line, a station included (it becomes the station's click if it does not
     * become a drag), and not while a popup is open (the click only closes it).
     */
    const grabAt = (point: { x: number; y: number }, tolerance: number) =>
      pressGrab({ station: stationAt(point), line: lineAt(point, tolerance) }, anyPopupOpen());
    const onMouseMove = (event: MouseEvent) => {
      if (gesture.active) follow(local(event.clientX, event.clientY));
    };
    const onMouseUp = (event: MouseEvent) => {
      if (gesture.active) finish(local(event.clientX, event.clientY));
    };
    map.on("touchstart", (event) => {
      if (event.points.length !== 1) {
        // A second finger is a pinch, never a drag of the line.
        if (gesture.active) finish(null);
        return;
      }
      if (event.originalEvent.target !== canvas) return;
      const hit = grabAt(event.point, TOUCH_HIT_PX);
      if (!hit) return;
      grabbed = hit;
      gesture.press("touch", event.point.x, event.point.y);
    });
    const onTouchMove = (event: TouchEvent) => {
      if (!gesture.active) return;
      if (event.touches.length !== 1) {
        finish(null);
        return;
      }
      const touch = event.touches[0];
      if (follow(local(touch.clientX, touch.clientY))) event.preventDefault();
    };
    const onTouchEnd = (event: TouchEvent) => {
      if (!gesture.active) return;
      const touch = event.changedTouches[0];
      finish(event.type === "touchend" && touch ? local(touch.clientX, touch.clientY) : null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Escape calls off a drag; otherwise it closes a via's Remove, and the
      // focus goes back where it was.
      if (gesture.active) finish(null);
      else if (closePopup(true)) event.preventDefault();
    };
    // A long press on a phone also asks for the browser's context menu.
    const onContextMenu = (event: Event) => {
      if (gesture.active) event.preventDefault();
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd);
    window.addEventListener("touchcancel", onTouchEnd);
    window.addEventListener("keydown", onKey);
    canvas.addEventListener("contextmenu", onContextMenu);

    map.on("click", (event) => {
      // A click on a station opens its card, and a click on the line puts
      // the via in the leg clicked, as a drag does; anywhere else it is
      // addPoint's (the leg it lengthens least). A click while a via's Remove
      // or a station's card is open only closes it, or opens the station
      // clicked (mapGlue.ts mapClickAction).
      const touch = (event.originalEvent as PointerEvent).pointerType === "touch";
      const onCanvas = event.originalEvent.target === canvas;
      const under = onCanvas
        ? { station: stationAt(event.point), line: lineAt(event.point, touch ? TOUCH_HIT_PX : MOUSE_HIT_PX) }
        : { station: null, line: null };
      const point: LonLat = [event.lngLat.lng, event.lngLat.lat];
      runClick(under, { popupOpen: anyPopupOpen(), afterDrag: performance.now() < clickSuppressedUntil }, {
        closePopups: () => {
          closePopup(false);
          rail?.closeCard();
        },
        openCard: (station) => rail?.openCard(station),
        lineDrop: (hit) => callbacks.current.onLineDrop(hit.leg, point, hit.points),
        addPoint: () => callbacks.current.onMapClick(point),
      });
    });

    // Under the base map's labels and the route, over its roads, in the
    // order stressOverlayLayers gives: every casing under every tier.
    const addStress = () => addStressOverlay(map, origin, callbacks.current.stressVisible, callbacks.current.when);

    // Ask the endpoint; if it does not answer, say so and ask again later, so
    // one bad minute does not take the overlay away for the whole visit
    // (stressProtocol.ts, stressProbe).
    const stressCheck = stressProbe(origin, STRESS_RECHECK_MS, {
      add: addStress,
      report: (availability) => callbacks.current.onStressAvailability(availability),
      disposed: () => disposed,
    });

    map.on("load", () => {
      loaded.current = true;
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ROUTE_CASING_PLAIN, "line-width": ROUTE_CASING_WIDTH, "line-opacity": 0.9 },
      });
      // The route in its traffic stress, between the casing and the line: one
      // feature per section, each in its class's colour. The line itself
      // stays, drawn in the route's blue only when there are no sections (an
      // older API); it is also what the stale dimming and the rail and
      // reference layers are placed against, and the pointer's hit test is
      // made against the route's geometry, not against any layer, so a
      // second line layer changes nothing about grabbing or dragging it.
      map.addSource(ROUTE_STRESS_SOURCE, { type: "geojson", data: sectionFeatures(null) });
      map.addLayer({
        id: "route-stress",
        type: "line",
        source: ROUTE_STRESS_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ["get", "color"], "line-width": ROUTE_LINE_WIDTH },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ROUTE_BLUE, "line-width": ROUTE_LINE_WIDTH },
      });
      map.addSource(EDIT_SOURCE, { type: "geojson", data: editData(null, []) });
      map.addLayer({
        id: "route-edit-preview",
        type: "line",
        source: EDIT_SOURCE,
        filter: ["==", ["geometry-type"], "LineString"],
        layout: { "line-cap": "round" },
        paint: { "line-color": "#1d4ed8", "line-width": 3, "line-opacity": 0.75, "line-dasharray": [2, 1.5] },
      });
      map.addLayer({
        id: "route-edit-handle",
        type: "circle",
        source: EDIT_SOURCE,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 7,
          "circle-color": "#ffffff",
          "circle-stroke-color": "#1d4ed8",
          "circle-stroke-width": 3,
        },
      });
      // Over the base map and the stress overlay, under the route and the
      // drag's handle and preview (railLayer.ts).
      // Left off, with a console warning, if a fixture no longer fits (railFixtures.ts).
      if (RAIL_STATIONS.length > 0) addRailStations(map, RAIL_STATIONS, callbacks.current.rail, PENN_COLOUR, iconPixelRatio());
      rail = attachRailInteraction(map, {
        station: stationById,
        stations: RAIL_STATIONS,
        pennColour: PENN_COLOUR,
        visibility: () => callbacks.current.rail,
        pointCount: () => callbacks.current.points.length,
        onStationPoint: (role, point) => callbacks.current.onStationPoint(role, point),
      });
      syncRoute(map, callbacks.current, fitted);
      callbacks.current.onReady(map);
      callbacks.current.onStressAvailability("checking");
      void stressCheck.probe();
    });

    map.on("error", (event) => {
      // A stress tile that failed after the endpoint had answered: check the
      // endpoint again rather than trusting one tile's failure either way.
      const source = (event as { sourceId?: string }).sourceId;
      if (source === STRESS_SOURCE_ID) stressCheck.later(5_000);
    });

    return () => {
      disposed = true;
      rail?.close();
      stressCheck.cancel();
      if (hoverFrame) cancelAnimationFrame(hoverFrame);
      gesture.cancel();
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
      window.removeEventListener("keydown", onKey);
      canvas.removeEventListener("mouseleave", onCanvasLeave);
      canvas.removeEventListener("contextmenu", onContextMenu);
      closePopup(false);
      loaded.current = false;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // Markers follow the point list (and go back to it on markerReset).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markers.current.forEach((m) => m.remove());
    // An undo (Ctrl+Z) while a via's Remove has the focus rebuilds the
    // markers under it: the focus goes back as Escape would send it, not to
    // the page's body.
    const focusInPopup = popup.current?.getElement().contains(document.activeElement) ?? false;
    closePopup(focusInPopup);
    markers.current = props.points.map((point, index) => {
      const { text, name, kind } = pointLabel(index, props.points.length);
      const via = kind === "via";
      const element = document.createElement("div");
      element.className = `pin pin-${kind}`;
      element.textContent = text;
      element.setAttribute("role", "img");
      element.setAttribute("aria-label", via ? `${name}. Drag to move; click for Remove.` : `${name}. Drag to move.`);
      element.title = via ? `${name} - drag to move, click for Remove, double-click to remove` : `${name} - drag to move`;
      const marker = new maplibregl.Marker({ element, draggable: true, anchor: "center" })
        .setLngLat(point)
        .addTo(map);
      // The browser's click at the end of a drag of the marker is not a click on it.
      let dragged = false;
      marker.on("dragstart", () => {
        dragged = true;
        closePopup(false);
      });
      marker.on("dragend", () => {
        setTimeout(() => {
          dragged = false;
        }, 0);
        const { lng, lat } = marker.getLngLat();
        callbacks.current.onMovePoint(index, [lng, lat]);
      });
      element.addEventListener("click", (event) => {
        // A click on a marker is not a click on the map: without this it
        // would also add a via point under the marker.
        event.stopPropagation();
        if (!via || dragged) return;
        // A via's click offers Remove beside it: a real button, so a finger
        // can use it as well as a mouse.
        // Where the focus goes back to on Escape: from a second via's click,
        // still wherever it was before the first.
        const returnTo = popup.current ? popupReturn.current : document.activeElement;
        closePopup(false);
        popupReturn.current = returnTo;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "via-remove";
        button.textContent = "Remove";
        button.setAttribute("aria-label", `Remove ${name.toLowerCase()}`);
        button.addEventListener("click", (clicked) => {
          clicked.stopPropagation();
          closePopup(true);
          callbacks.current.onRemovePoint(index);
        });
        // Not closed by MapLibre on a map click: the map's click handler
        // closes it, so that the same click does not also add a point.
        popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "via-popup" })
          .setLngLat(marker.getLngLat())
          .setDOMContent(button)
          .addTo(map);
        button.focus();
      });
      if (via) {
        // A double-click removes it at once, and is not the map's zoom.
        element.addEventListener("dblclick", (event) => {
          event.stopPropagation();
          event.preventDefault();
          closePopup(true);
          callbacks.current.onRemovePoint(index);
        });
      }
      return marker;
    });
  }, markerDeps(props.points, props.markerReset));

  // The route line.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    syncRoute(map, callbacks.current, fitted);
  }, [props.route, props.stale]);

  // The accessibility switch (or the system's request for more contrast):
  // the overlay's layers and the route's sections are painted again in place.
  // The legend and the stress bar are React and follow by useStressStyle.
  useEffect(
    () =>
      subscribePalette(() => {
        const map = mapRef.current;
        if (!map || !loaded.current) return;
        setStressPalette(map, callbacks.current.when);
        setRouteSections(map, callbacks.current.route, callbacks.current.stale);
      }),
    [],
  );

  // The route's stressful junctions: orange and red warning markers on the line,
  // a click on one showing why (OWNER-DECISIONS 172). They go while the route
  // is being planned again, as the line's own colours dim.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    junctionCard.current?.remove();
    junctionCard.current = null;
    junctionMarkers.current.forEach(({ marker }) => marker.remove());
    junctionMarkers.current = [];
    junctionList.current = [];
    if (!props.route || props.stale) return;
    junctionList.current = junctionsOnMap(junctionItems(props.route));
    const draw = () => {
      junctionMarkers.current.forEach(({ marker }) => marker.remove());
      const groups = groupJunctions(junctionList.current, map.getZoom(), (item) => map.project([item.lon, item.lat]));
      junctionMarkers.current = groups.map((group) => {
        const [first] = group.members;
        const single = group.members.length === 1;
        const element = document.createElement("button");
        element.type = "button";
        element.className = `junction-marker junction-${group.severity}${single ? "" : " junction-group"}`;
        element.innerHTML =
          warningIconSvg(group.severity, ICON_PX) +
          (single ? "" : `<span class="junction-count" aria-hidden="true">${group.members.length}</span>`);
        element.setAttribute("aria-label", single ? first.label : groupLabel(group));
        element.title = single ? first.reason : groupLabel(group);
        const marker = new maplibregl.Marker({ element, anchor: "center" }).setLngLat([first.lon, first.lat]).addTo(map);
        element.addEventListener("click", (event) => {
          // A click on a marker is not a click on the map: it must not add a via point.
          event.stopPropagation();
          if (single) {
            showJunctionCard(map, first, junctionCard);
            return;
          }
          const bounds = new maplibregl.LngLatBounds();
          group.members.forEach((m) => bounds.extend([m.lon, m.lat]));
          map.fitBounds(bounds, { padding: 120, maxZoom: 17, duration: 500 });
        });
        element.addEventListener("dblclick", (event) => event.stopPropagation());
        return { group, marker };
      });
    };
    draw();
    map.on("zoomend", draw);
    return () => {
      map.off("zoomend", draw);
    };
  }, [props.route, props.stale]);

  // A click on the summary's list: take the map there and say why.
  useEffect(() => {
    const map = mapRef.current;
    const focus = props.junctionFocus;
    if (!map || !focus) return;
    const found = junctionList.current.find((item) => item.index === focus.index);
    if (!found) return;
    map.easeTo({ center: [found.lon, found.lat], zoom: Math.max(map.getZoom(), 15), duration: 500 });
    showJunctionCard(map, found, junctionCard);
  }, [props.junctionFocus]);

  // A route that can no longer be dragged (it is being planned again) takes
  // its hover handle with it.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || props.lineEdit) return;
    (map.getSource(EDIT_SOURCE) as GeoJSONSource | undefined)?.setData(editData(null, []));
    hoverShown.current = null;
    // The hover's pointer cursor goes with its handle (an undo made while
    // hovering the line would otherwise leave it).
    map.getCanvas().style.cursor = "";
  }, [props.lineEdit]);

  // The overlay toggle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || !map.getSource(STRESS_SOURCE_ID)) return;
    setStressVisibility(map, props.stressVisible);
  }, [props.stressVisible]);

  // The ride time: a road closed to cars at set times is a path in them.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || !map.getSource(STRESS_SOURCE_ID)) return;
    setStressWhen(map, props.when);
  }, [props.when]);

  // The rail stations' toggles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    setRailVisibility(map, RAIL_STATIONS, props.rail);
  }, [props.rail.metro, props.rail.marc]);

  return <div ref={container} className="map" role="region" aria-label="Map" />;
}

/** The card a junction marker opens: its reason, and the way to avoid it. */
function showJunctionCard(map: MapLibreMap, item: JunctionItem, card: { current: Popup | null }): void {
  card.current?.remove();
  const body = document.createElement("div");
  body.className = "junction-card";
  const title = document.createElement("strong");
  title.textContent = item.label.split(":")[0];
  const reason = document.createElement("p");
  reason.textContent = item.reason;
  const where = document.createElement("p");
  where.className = "hint";
  where.textContent = `${item.where}. Drag the route away to plan around it.`;
  body.append(title, reason, where);
  card.current = new maplibregl.Popup({ closeButton: true, closeOnClick: true, offset: 16, className: `junction-popup junction-popup-${item.severity}` })
    .setLngLat([item.lon, item.lat])
    .setDOMContent(body)
    .addTo(map);
}

/** Station icons are drawn for the screen's pixel density, whole numbers only. */
function iconPixelRatio(): number {
  return Math.min(3, Math.max(1, Math.ceil(window.devicePixelRatio || 1)));
}

function syncRoute(map: MapLibreMap, props: Props, fitted: { current: boolean }): void {
  const { route, stale } = props;
  const source = map.getSource(ROUTE_SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  source.setData(
    route
      ? { type: "Feature", properties: {}, geometry: route.geometry }
      : { type: "FeatureCollection", features: [] },
  );
  setRouteSections(map, route, stale);
  if (!route || stale || route.geometry.coordinates.length < 2) return;
  const padding = props.framePadding();
  if (fitted.current && routeInView(map, route.geometry.coordinates, padding)) return;
  fitted.current = true;
  const bounds = new maplibregl.LngLatBounds();
  route.geometry.coordinates.forEach((c) => bounds.extend(c));
  map.fitBounds(bounds, { padding, maxZoom: 15, duration: 600 });
}
