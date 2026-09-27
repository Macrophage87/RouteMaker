import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, Marker, Popup } from "maplibre-gl";
import { Protocol } from "pmtiles";
// MapLibre 6 ships its worker as a separate module and finds it next to its own
// file by `import.meta.url`, which a bundle does not preserve; Vite builds it
// as an asset of its own here and the map is told where it is.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { COVERAGE_BBOX, lonLatToTile, type LonLat } from "./lib/geo.ts";
import {
  BASEMAP_SOURCE_ID,
  MAP_ATTRIBUTION,
  STRESS_SOURCE_ID,
  buildStyle,
} from "./lib/mapStyle.ts";
import type { RouteResponse } from "./lib/api.ts";
import { addStressOverlay, markerDeps, setStressVisibility } from "./lib/mapGlue.ts";
import { dragPreview, legOfSegment, nearestOnPath } from "./lib/lineEdit.ts";
import { LineGesture } from "./lib/lineGesture.ts";

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
  onReady: (map: MapLibreMap) => void;
  onCanvasFocus: (focused: boolean) => void;
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
/** The handle and the dashed preview of a drag of the line. */
const EDIT_SOURCE = "route-edit";
/** How far from the line's centre a mouse, or a finger, still grabs it. */
const MOUSE_HIT_PX = 8;
const TOUCH_HIT_PX = 18;
/** Near a marker, the marker is what the pointer is on, not the line. */
const MARKER_CLEAR_PX = 14;
/** After a drag, the click the browser may still send is not a new point. */
const CLICK_AFTER_DRAG_MS = 400;
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

async function stressTilesAnswer(origin: string): Promise<boolean> {
  // One tile over central DC at a zoom the contract serves. A 404 means the
  // endpoint is not deployed; a 502 that the API is down. Either way the map
  // shows without the overlay rather than with a legend for nothing.
  const { x, y, z } = lonLatToTile(DC_CENTRE, 12);
  try {
    const response = await fetch(`${origin}/tiles/stress/${z}/${x}/${y}.pbf`);
    return response.ok;
  } catch {
    return false;
  }
}

export function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const popup = useRef<Popup | null>(null);
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
      zoom: 11.2,
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
    let recheck: ReturnType<typeof setTimeout> | null = null;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
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
      (map.getSource(EDIT_SOURCE) as GeoJSONSource | undefined)?.setData(editData(handle, preview));
    };
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
        // the preview show where the line was picked up.
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

    // Hovering: a handle on the line where a press would grab it.
    let hoverFrame = 0;
    let hoverPoint: { x: number; y: number } | null = null;
    map.on("mousemove", (event) => {
      if (gesture.active) return;
      hoverPoint = event.originalEvent.target === canvas ? event.point : null;
      if (hoverFrame) return;
      hoverFrame = requestAnimationFrame(() => {
        hoverFrame = 0;
        if (gesture.active) return;
        const hit = hoverPoint ? lineAt(hoverPoint, MOUSE_HIT_PX) : null;
        showEdit(hit ? hit.at : null);
        canvas.style.cursor = hit ? "pointer" : "";
      });
    });
    const onCanvasLeave = () => {
      hoverPoint = null;
      if (!gesture.active) endDrag();
    };
    canvas.addEventListener("mouseleave", onCanvasLeave);
    map.on("mousedown", (event) => {
      if (event.originalEvent.button !== 0 || event.originalEvent.target !== canvas) return;
      const hit = lineAt(event.point, MOUSE_HIT_PX);
      if (!hit) return;
      // The map does not pan: this press is the line's.
      event.preventDefault();
      grabbed = hit;
      gesture.press("mouse", event.point.x, event.point.y);
    });
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
      const hit = lineAt(event.point, TOUCH_HIT_PX);
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
      if (event.key === "Escape" && gesture.active) finish(null);
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
      if (performance.now() < clickSuppressedUntil) return;
      // A click on the line puts the via in the leg clicked, as a drag does;
      // anywhere else it is addPoint's (the leg it lengthens least).
      const touch = (event.originalEvent as PointerEvent).pointerType === "touch";
      const hit =
        event.originalEvent.target === canvas ? lineAt(event.point, touch ? TOUCH_HIT_PX : MOUSE_HIT_PX) : null;
      const point: LonLat = [event.lngLat.lng, event.lngLat.lat];
      if (hit) callbacks.current.onLineDrop(hit.leg, point, hit.points);
      else callbacks.current.onMapClick(point);
    });

    // Under the base map's labels and the route, over its roads, in the
    // order stressOverlayLayers gives: every casing under every tier.
    const addStress = () => addStressOverlay(map, origin, callbacks.current.stressVisible);

    // Ask the endpoint; if it does not answer, say so and ask again later, so
    // one bad minute does not take the overlay away for the whole visit.
    const probeStress = async () => {
      const available = await stressTilesAnswer(origin);
      if (disposed) return;
      if (available) {
        addStress();
        callbacks.current.onStressAvailability("available");
      } else {
        callbacks.current.onStressAvailability("unavailable");
        if (recheck === null) {
          recheck = setTimeout(() => {
            recheck = null;
            void probeStress();
          }, STRESS_RECHECK_MS);
        }
      }
    };

    map.on("load", () => {
      loaded.current = true;
      map.addSource(ROUTE_SOURCE, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#ffffff", "line-width": 9, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#1d4ed8", "line-width": 5 },
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
      syncRoute(map, callbacks.current, fitted);
      callbacks.current.onReady(map);
      callbacks.current.onStressAvailability("checking");
      void probeStress();
    });

    map.on("error", (event) => {
      // A stress tile that failed after the endpoint had answered: check the
      // endpoint again rather than trusting one tile's failure either way.
      const source = (event as { sourceId?: string }).sourceId;
      if (source === STRESS_SOURCE_ID && recheck === null) {
        recheck = setTimeout(() => {
          recheck = null;
          void probeStress();
        }, 5_000);
      }
    });

    return () => {
      disposed = true;
      if (recheck !== null) clearTimeout(recheck);
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
      popup.current?.remove();
      popup.current = null;
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
    popup.current?.remove();
    popup.current = null;
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
        popup.current?.remove();
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
        popup.current?.remove();
        const button = document.createElement("button");
        button.type = "button";
        button.className = "via-remove";
        button.textContent = "Remove";
        button.setAttribute("aria-label", `Remove ${name.toLowerCase()}`);
        button.addEventListener("click", (clicked) => {
          clicked.stopPropagation();
          popup.current?.remove();
          callbacks.current.onRemovePoint(index);
        });
        popup.current = new maplibregl.Popup({ closeButton: false, offset: 14, className: "via-popup" })
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
          popup.current?.remove();
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

  // A route that can no longer be dragged (it is being planned again) takes
  // its hover handle with it.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || props.lineEdit) return;
    (map.getSource(EDIT_SOURCE) as GeoJSONSource | undefined)?.setData(editData(null, []));
  }, [props.lineEdit]);

  // The overlay toggle.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current || !map.getSource(STRESS_SOURCE_ID)) return;
    setStressVisibility(map, props.stressVisible);
  }, [props.stressVisible]);

  return <div ref={container} className="map" role="region" aria-label="Map" />;
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
  map.setPaintProperty("route-line", "line-opacity", stale ? 0.45 : 1);
  if (!route || stale || route.geometry.coordinates.length < 2) return;
  const padding = props.framePadding();
  if (fitted.current && routeInView(map, route.geometry.coordinates, padding)) return;
  fitted.current = true;
  const bounds = new maplibregl.LngLatBounds();
  route.geometry.coordinates.forEach((c) => bounds.extend(c));
  map.fitBounds(bounds, { padding, maxZoom: 15, duration: 600 });
}
