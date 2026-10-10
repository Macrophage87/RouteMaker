import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, Marker, Popup } from "maplibre-gl";
import { Protocol } from "pmtiles";
// MapLibre 6 ships its worker as a separate module and finds it next to its own
// file by `import.meta.url`, which a bundle does not preserve; Vite builds it
// as an asset of its own here and the map is told where it is.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { COVERAGE_BBOX, type LonLat } from "./lib/geo.ts";
import { accuracyRing } from "./lib/geolocation.ts";
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
  ROUTE_HALO_WIDTH,
  ROUTE_CASING_PLAIN,
  ROUTE_CASING_WIDTH,
  ROUTE_LINE_WIDTH,
  sectionFeatures,
} from "./lib/routeColours.ts";
import { stressOverlayLayers, subscribeHighStressLanes, subscribeMtbTrails, subscribePalette } from "./stressStyle.js";
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
  onLaneSwitch,
  routeUnpavedLayer,
  routeAvoidLayer,
  routeDashLayers,
  solidRouteFilter,
  setMassMode,
} from "./lib/mapGlue.ts";
import { dragPreview, legOfSegment, nearestOnPath } from "./lib/lineEdit.ts";
import { LineGesture } from "./lib/lineGesture.ts";
import { PENN_COLOUR, RAIL_STATIONS, stationById } from "./lib/railData.ts";
import { addRailStations, ROUTE_BOTTOM_LAYER, setRailVisibility } from "./lib/railLayer.ts";
import type { RailVisibility, StationRole } from "./lib/railStations.ts";
import { attachRailInteraction, type StationFound } from "./railInteraction.ts";
import { stressProbe } from "./lib/stressProtocol.ts";
import federalLandUrl from "./federal-data/federal-land.json?url";
import { addDcMask } from "./lib/dcBoundary.ts";
import { addFederalLand, loadFederalLand, setFederalVisibility, type FederalData, type FederalMap } from "./lib/federalLand.ts";
import type { FederalStatus } from "./lib/federalLegend.ts";
import { attachFederalInteraction } from "./federalInteraction.ts";
import { addWaterRestrooms, setWaterPrefs, WATER_SOURCE_ID, type WaterMap, type WaterPoint, type WaterPrefs } from "./lib/waterRestrooms.ts";
import { attachWaterInteraction } from "./waterInteraction.ts";
import type { When } from "./lib/dials.ts";
import { pointLabel } from "./lib/pointText.ts";
import { LongPress, isInfoKey, repeatsInfoAsk, type InfoRequest } from "./lib/roadInfo.ts";
import {
  BIKESHARE_CREDIT,
  WALK_CASING,
  WALK_CASING_WIDTH,
  WALK_COLOUR,
  WALK_DASH,
  WALK_LINE_WIDTH,
  bikeshareOf,
  dockMarkers,
  walkFeatures,
} from "./lib/bikeshare.ts";
import {
  CARD_CLOSE_LABEL,
  cardName,
  cardTakesFocus,
  collapseCredits,
  escapeClosesCard,
  focusAfterClose,
  groupHolding,
  type CardOpener,
} from "./lib/junctionCard.ts";
import {
  MAP_MAX_ZOOM,
  groupJunctions,
  groupLabel,
  junctionItems,
  junctionsOnMap,
  warningIconSvg,
  ICON_PX,
  type JunctionGroup,
  type JunctionItem,
} from "./lib/intersectionMarkers.ts";
import { avoidItems, avoidMarkerName } from "./lib/avoidJunctions.ts";
import { avoidMarkerSvg } from "./lib/avoidIcon.ts";

export type StressAvailability = "checking" | "available" | "unavailable";

/** The route as it can be dragged: its line, where each leg ends in it, and the points it was planned through. */
export interface LineEdit {
  path: LonLat[];
  ends: number[];
  points: LonLat[];
  /** The points the legs run between: `points`, and in a loop the start again (lineEdit.ts, legPoints). */
  legPoints: LonLat[];
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
  /** "Make it a loop" is on: the first point is the start and finish, the rest are stops (OWNER-DECISIONS 374). */
  loopVias?: boolean;
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
  /** The accuracy circle of the rider's location while its point is in the plan (OWNER-DECISIONS 395), or null. */
  accuracy: { centre: LonLat; radiusM: number } | null;
  /** The junction the route summary's list asked the map to show (nonce: again), or null. */
  junctionFocus: { index: number; nonce: number } | null;
  /** The point on the route the elevation chart is reading (OWNER-DECISIONS 322), or null: a ringed marker, not in the tab order. */
  scrubPoint?: LonLat | null;
  /**
   * Ride mode (WEB-NAV-plan.md section 1): the rider's position, a "you" arrow distinct from the scrub ring
   * (drawn over the accuracy circle, which `accuracy` carries), or null outside a ride. With `follow` the map
   * centres on it at each fix (one easeTo, no continuous animation); a pan by hand calls `onFollowBroken`.
   * `headingUp` turns the map to the rider's heading; north-up otherwise. While riding the route is not
   * re-framed when it changes (a re-plan).
   */
  rider?: { point: LonLat; headingDeg: number | null } | null;
  follow?: boolean;
  headingUp?: boolean;
  onFollowBroken?: () => void;
  onReady: (map: MapLibreMap) => void;
  onCanvasFocus: (focused: boolean) => void;
  /** Which rail stations show (the panel's toggles). */
  rail: RailVisibility;
  /**
   * The map is coloured by carrying capacity, riders per minute, not by traffic stress
   * (OWNER-DECISIONS 325-327; massStyle.js): a Mass Ride on tiles that carry a capacity (App's
   * `massMap`). On an older table a Mass Ride keeps the stress layers, as its legend says.
   */
  massCapacity?: boolean;
  /** The ride type is Mass Ride: the grey outside the District shows (OWNER-DECISIONS 418), whatever the tiles. */
  massArea?: boolean;
  /** Whether the federal-land shading is on (a Mass Ride's, lib/federalLand.ts federalShown). */
  federalVisible: boolean;
  /** Whether to load the federal-land data even with the shading off: a Mass Ride's planner lists the points on it. */
  federalWanted?: boolean;
  onFederalStatus: (status: FederalStatus) => void;
  /** The federal-land data once it has come: App lists the plan's points on it (lib/federalLand.ts federalPoints). */
  onFederalData?: (data: FederalData) => void;
  /** The public water and restrooms (lib/waterRestrooms.ts), once App has loaded them; null before. */
  water?: readonly WaterPoint[] | null;
  /** The rider's switches for their layer (lib/waterRestrooms.ts WaterPrefs): on, basic toilets, untreated water. */
  waterPrefs?: WaterPrefs;
  /** A station's Start here / End here / Add as stop, with its bike entrance. */
  onStationPoint: (role: StationRole, point: LonLat) => void;
  /**
   * The road panel for a spot (OWNER-DECISIONS 441a; lib/roadInfo.ts): a right-click, a
   * long press on a phone, or I with the map focused (the map's centre).
   */
  onRoadInfo?: (request: InfoRequest) => void;
  /**
   * Drawn in a map control of its own under the zoom buttons (top right): App's "Map tools"
   * (OWNER-DECISIONS 450; MapTools.tsx), so it sits with the map's other controls, in their
   * Tab order, inside the map's region.
   */
  tools?: ReactNode;
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
const ACCURACY_SOURCE = "location-accuracy";
// Bikeshare's walk legs (lib/bikeshare.ts): dotted, with the operator's source citation as the
// source's attribution, so the attribution control shows it exactly while a bikeshare plan's
// layer is visible and never otherwise (OWNER-DECISIONS 301).
const WALK_SOURCE = "bikeshare-walk";
/** How far from the line's centre a mouse, or a finger, still grabs it. */
const MOUSE_HIT_PX = 8;
const TOUCH_HIT_PX = 18;
/** Near a marker, the marker is what the pointer is on, not the line. */
const MARKER_CLEAR_PX = 14;
/** After a drag, the click the browser may still send is not a new point. */
const CLICK_AFTER_DRAG_MS = 400;
/** The buzz when a held finger picks the line up. */
const PICK_UP_BUZZ_MS = 15;
/** One gesture can ask for the road panel twice (a phone's long press is also its contextmenu). */
const INFO_REPEAT_MS = 800;
/** A right-button press that moved this far rotated the map: its contextmenu is not a request. */
const RIGHT_DRAG_PX = 5;
const MAX_BOUNDS_PAD = 0.4;
/** How long an unanswered stress endpoint is left before it is asked again. */
const STRESS_RECHECK_MS = 60_000;

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


function accuracyData(accuracy: { centre: LonLat; radiusM: number } | null) {
  return {
    type: "FeatureCollection" as const,
    features:
      accuracy && accuracy.radiusM > 0
        ? [
            {
              type: "Feature" as const,
              properties: {},
              geometry: { type: "Polygon" as const, coordinates: [accuracyRing(accuracy.centre, accuracy.radiusM)] },
            },
          ]
        : [],
  };
}

export function MapView(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  // The map control App's Map tools is drawn into, once the map has made it.
  const [toolsHost, setToolsHost] = useState<HTMLElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const popup = useRef<Popup | null>(null);
  // The route's junction markers (OWNER-DECISIONS 172) and the card one of them has open.
  const junctionMarkers = useRef<{ group: JunctionGroup; marker: Marker }[]>([]);
  // The route's junctions, which the markers are drawn from at each zoom.
  const junctionList = useRef<JunctionItem[]>([]);
  const junctionCard = useRef<Popup | null>(null);
  // After a group's zoom, the junction whose new marker takes the focus.
  const focusAfterZoom = useRef<number | null>(null);
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
  /**
   * Open a junction's card (lib/junctionCard.ts): from a marker it takes the
   * focus and gives it back to the marker on close; from the list the focus
   * stays on the row. Escape closes it (onKey).
   */
  const openCard = (item: JunctionItem, opener: CardOpener) => {
    const map = mapRef.current;
    if (!map) return;
    const previous = junctionCard.current;
    junctionCard.current = null;
    previous?.remove();
    const card = showJunctionCard(map, item, cardTakesFocus(opener));
    junctionCard.current = card;
    // Whether the focus was in the card as it went: MapLibre takes the card
    // out of the page before it says "close".
    const element = card.getElement();
    let focusWasInCard = element.contains(document.activeElement);
    element.addEventListener("focusin", () => {
      focusWasInCard = true;
    });
    element.addEventListener("focusout", (event) => {
      const next = (event as FocusEvent).relatedTarget;
      focusWasInCard = next instanceof Node && element.contains(next);
    });
    card.on("close", () => {
      if (junctionCard.current === card) junctionCard.current = null;
      const active = document.activeElement;
      const back = focusAfterClose(opener, focusWasInCard, active === null || active === document.body);
      if (back === null) return;
      (back === "marker" ? markerFor(item.index) : rowFor(item.index))?.focus();
    });
  };
  /** The marker now drawn for the junction at `index` (its group's, if it is in one). */
  const markerFor = (index: number): HTMLElement | null => {
    const drawn = junctionMarkers.current;
    const at = groupHolding(
      drawn.map((m) => m.group),
      index,
    );
    return at >= 0 ? drawn[at].marker.getElement() : null;
  };
  const loaded = useRef(false);
  /** Set once the map has loaded: puts the federal-land layers in line with the prop. */
  const federalSync = useRef<(() => void) | null>(null);
  /** Set once the map has loaded: puts the water and restrooms layer in line with the props. */
  const waterSync = useRef<(() => void) | null>(null);
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
      maxZoom: MAP_MAX_ZOOM,
      maxBounds: [
        [west - MAX_BOUNDS_PAD, south - MAX_BOUNDS_PAD],
        [east + MAX_BOUNDS_PAD, north + MAX_BOUNDS_PAD],
      ],
      // Added below, so it can start collapsed on a phone.
      attributionControl: false,
      cooperativeGestures: false,
    });
    mapRef.current = map;
    let disposed = false;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    // Map tools, under the zoom buttons (OWNER-DECISIONS 450): an empty control React fills.
    const toolsControl = document.createElement("div");
    toolsControl.className = "maplibregl-ctrl map-tools-ctrl";
    map.addControl({ onAdd: () => toolsControl, onRemove: () => toolsControl.remove() }, "top-right");
    setToolsHost(toolsControl);
    // One entry, OpenStreetMap first (mapStyle.ts says why). Added before the
    // scales, so it is the bottom of the corner's stack. On a narrow map it
    // starts as the "i" button with the OpenStreetMap credit beside it, as
    // MapLibre's own first drag leaves it (lib/junctionCard.ts collapseCredits).
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: MAP_ATTRIBUTION }), "bottom-right");
    collapseCredits(container.current.querySelector(".maplibregl-ctrl-attrib"), map.getCanvasContainer().offsetWidth);
    // Both scales, miles and feet over kilometres and metres (OWNER-DECISIONS 85):
    // a bottom corner stacks its controls upwards, so the one added last is on top.
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
    const canvas = map.getCanvas();
    canvas.setAttribute(
      "aria-label",
      "Map. Use arrow keys to pan and plus or minus to zoom. Press I for what is known about the road at the center.",
    );
    canvas.setAttribute("aria-keyshortcuts", "I");
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
    let federal: ReturnType<typeof attachFederalInteraction> | null = null;
    let federalLoading = false;
    let water: ReturnType<typeof attachWaterInteraction> | null = null;
    let waterById = new Map<string, WaterPoint>();
    /** Add the water and restrooms layer when its data has come, then show or hide it with the switch. */
    const syncWater = () => {
      const prefs = callbacks.current.waterPrefs ?? { on: false, basic: true, untreated: true };
      if (map.getSource(WATER_SOURCE_ID)) {
        setWaterPrefs(map as unknown as WaterMap, prefs);
        water?.close();
        return;
      }
      const data = callbacks.current.water;
      if (!data || data.length === 0) return;
      waterById = new Map(data.map((p) => [p.id, p]));
      // Over the stress overlay and the stations, directly under the route (railLayer.ts's order).
      addWaterRestrooms(map as unknown as WaterMap, data, prefs, iconPixelRatio(), ROUTE_BOTTOM_LAYER);
    };
    const anyPopupOpen = () => popupsOpen(popup.current, rail);
    /** Bring the federal-land layers in line with props.federalVisible, loading the data the first time. */
    const syncFederal = () => {
      const visible = callbacks.current.federalVisible;
      if (map.getSource("federal-land")) {
        setFederalVisibility(map, visible);
        if (!visible) federal?.close();
        return;
      }
      if (!(visible || callbacks.current.federalWanted) || federalLoading) return;
      federalLoading = true;
      callbacks.current.onFederalStatus("loading");
      void loadFederalLand(federalLandUrl).then((data) => {
        federalLoading = false;
        if (disposed) return;
        if (!data) {
          callbacks.current.onFederalStatus("unavailable");
          return;
        }
        addFederalLand(map as unknown as FederalMap, data, callbacks.current.federalVisible, STRESS_SOURCE_ID);
        callbacks.current.onFederalStatus("ready");
        callbacks.current.onFederalData?.(data);
      });
    };
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
      const leg = legOfSegment(edit.ends, near.segment);
      return { leg, at: near.point, points: edit.points, legPoints: edit.legPoints };
    };
    let grabbed: { leg: number; at: LonLat; points: LonLat[]; legPoints: LonLat[] } | null = null;
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
        if (grabbed) showEdit(grabbed.at, dragPreview(grabbed.legPoints, grabbed.leg, grabbed.at));
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
      showEdit(cursor, dragPreview(grabbed.legPoints, grabbed.leg, cursor));
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

    // The road panel (OWNER-DECISIONS 441a): a right-click, or a finger held still on the
    // map off the route line (which a held finger picks up instead). The long press
    // never prevents a default, so the map pans and pinches under it as ever; a drift,
    // a second finger or the finger lifting calls it off.
    let infoAt = 0;
    const openInfo = (point: { x: number; y: number }, origin: InfoRequest["origin"]) => {
      const now = performance.now();
      if (repeatsInfoAsk(origin, now, infoAt, INFO_REPEAT_MS)) return;
      if (origin === "spot") {
        infoAt = now;
        // The finger's lift (or the right button's) is not also a tap that adds a point.
        clickSuppressedUntil = now + INFO_REPEAT_MS;
      }
      callbacks.current.onRoadInfo?.({ point: lonLatAt(point), origin });
    };
    const longPress = new LongPress((at) => openInfo(at, "spot"));
    // Where the right button went down, while it is held; and a contextmenu that came
    // with the press (macOS and Linux send it then, Windows on release), waiting for the
    // release to show whether the press was a click or a drag that rotated the map.
    let rightDown: { x: number; y: number } | null = null;
    let menuWaiting = false;
    // Whether the last right press, released, moved (a rotation): Windows sends its
    // contextmenu after the release.
    let rightMoved = false;
    const onRightDown = (event: MouseEvent) => {
      if (event.button !== 2) return;
      rightDown = local(event.clientX, event.clientY);
      rightMoved = false;
      menuWaiting = false;
    };
    const onRightUp = (event: MouseEvent) => {
      if (event.button !== 2 || !rightDown) return;
      const from = rightDown;
      rightDown = null;
      const at = local(event.clientX, event.clientY);
      rightMoved = Math.hypot(from.x - at.x, from.y - at.y) > RIGHT_DRAG_PX;
      if (!menuWaiting) return;
      menuWaiting = false;
      if (!rightMoved) openInfo(from, "spot");
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
        // A second finger is a pinch, never a drag of the line nor a long press.
        longPress.cancel();
        if (gesture.active) finish(null);
        return;
      }
      if (event.originalEvent.target !== canvas) return;
      const hit = grabAt(event.point, TOUCH_HIT_PX);
      if (!hit) {
        // Off the line: a finger held here opens the road panel.
        if (!anyPopupOpen()) longPress.press(event.point.x, event.point.y);
        return;
      }
      grabbed = hit;
      gesture.press("touch", event.point.x, event.point.y);
    });
    const onTouchMove = (event: TouchEvent) => {
      if (longPress.pending) {
        const touch = event.touches[0];
        if (event.touches.length !== 1 || !touch) longPress.cancel();
        else {
          const at = local(touch.clientX, touch.clientY);
          longPress.move(at.x, at.y);
        }
      }
      if (!gesture.active) return;
      if (event.touches.length !== 1) {
        finish(null);
        return;
      }
      const touch = event.touches[0];
      if (follow(local(touch.clientX, touch.clientY))) event.preventDefault();
    };
    const onTouchEnd = (event: TouchEvent) => {
      longPress.cancel();
      if (!gesture.active) return;
      const touch = event.changedTouches[0];
      finish(event.type === "touchend" && touch ? local(touch.clientX, touch.clientY) : null);
    };
    const onKey = (event: KeyboardEvent) => {
      // I, on the focused map: the road at the map's centre (the crosshair shows it).
      if (event.target === canvas && isInfoKey(event)) {
        event.preventDefault();
        const box = canvas.getBoundingClientRect();
        openInfo({ x: box.width / 2, y: box.height / 2 }, "centre");
        return;
      }
      if (event.key !== "Escape") return;
      // Escape calls off a drag; otherwise it closes a via's Remove, and the
      // focus goes back where it was; otherwise a junction's card, likewise.
      if (gesture.active) finish(null);
      else if (closePopup(true)) event.preventDefault();
      else if (escapeClosesCard(junctionCard.current !== null, focusPlace(junctionCard.current, map))) {
        event.preventDefault();
        junctionCard.current?.remove();
      }
    };
    // A long press on a phone also asks for the browser's context menu; on the map
    // itself the menu is the road panel's (a right-click, or a phone's long press,
    // whichever comes first; openInfo takes one of the two).
    const onContextMenu = (event: MouseEvent) => {
      if (gesture.active) {
        event.preventDefault();
        return;
      }
      if (event.target !== canvas) return;
      event.preventDefault();
      longPress.cancel();
      if (rightDown) {
        // Sent with the press (macOS, Linux): the release decides (onRightUp).
        menuWaiting = true;
        return;
      }
      // A right-button drag rotated the map; its contextmenu at the end is not a request.
      const moved = rightMoved;
      rightMoved = false;
      if (moved) return;
      openInfo(local(event.clientX, event.clientY), "spot");
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    window.addEventListener("mouseup", onRightUp);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd);
    window.addEventListener("touchcancel", onTouchEnd);
    window.addEventListener("keydown", onKey);
    canvas.addEventListener("contextmenu", onContextMenu);
    canvas.addEventListener("mousedown", onRightDown);

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
    const addStress = () => {
      // The mode before the layers, so they are added drawn for it (stressStyle.js, massRide).
      setMassMode(null, callbacks.current.massCapacity === true, callbacks.current.when, callbacks.current.stressVisible, callbacks.current.massArea === true);
      return addStressOverlay(map, origin, callbacks.current.stressVisible, callbacks.current.when);
    };

    // Ask the endpoint; if it does not answer, say so and ask again later, so
    // one bad minute does not take the overlay away for the whole visit
    // (stressProtocol.ts, stressProbe).
    const stressCheck = stressProbe(origin, STRESS_RECHECK_MS, {
      add: addStress,
      report: (availability) => callbacks.current.onStressAvailability(availability),
      disposed: () => disposed,
    });

    // A pan or zoom that got under way is not a long press.
    map.on("movestart", () => longPress.cancel());

    map.on("load", () => {
      loaded.current = true;
      // The grey outside the District, shown in Mass Ride mode only (OWNER-DECISIONS 418; lib/dcBoundary.ts):
      // over the base map, under its labels, the overlays and the route.
      addDcMask(map, callbacks.current.massArea === true, new Set(stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id)));
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
      // A one-pixel halo under each section, dark or white by class, so the
      // section is 3:1 from what touches it (lib/routeColours.ts, ROUTE_HALO_PATH).
      // The near-black ring outside the halo of a two-tone LTS 3 or LTS 4 section (OWNER-DECISIONS 371).
      // Butt caps (the re-check's NT3): a round cap showed a pixel of near-black past a ringed
      // section's end, under the next section's narrower halo.
      map.addLayer({
        id: "route-ring",
        type: "line",
        source: ROUTE_STRESS_SOURCE,
        layout: { "line-join": "round", "line-cap": "butt" },
        paint: { "line-color": ["get", "ring"], "line-width": ["coalesce", ["get", "ringWidth"], 0], "line-opacity": 0 },
      });
      map.addLayer({
        id: "route-halo",
        type: "line",
        source: ROUTE_STRESS_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ["get", "halo"], "line-width": ["coalesce", ["get", "haloWidth"], ROUTE_HALO_WIDTH], "line-opacity": 0 },
      });
      map.addLayer({
        id: "route-stress",
        type: "line",
        source: ROUTE_STRESS_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        filter: solidRouteFilter() as never,
        paint: { "line-color": ["get", "color"], "line-width": ["coalesce", ["get", "width"], ROUTE_LINE_WIDTH] },
      });
      // A Mass Ride's dashed sections (the cue besides colour, OWNER-DECISIONS 327).
      for (const layer of routeDashLayers()) map.addLayer(layer as never);
      // The dotted mark over an unpaved section, in its halo colour (OWNER-DECISIONS 302):
      // brown is not the only thing that says unpaved.
      map.addLayer(routeUnpavedLayer(ROUTE_STRESS_SOURCE) as never);
      // The white dash-dot over a paved Avoid section (397): magenta is not the only thing that says Avoid.
      map.addLayer(routeAvoidLayer(ROUTE_STRESS_SOURCE) as never);
      map.addLayer({
        id: "route-line",
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ROUTE_BLUE, "line-width": ROUTE_LINE_WIDTH },
      });
      // Under the route (before its casing), so the circle's tint never covers the line.
      map.addSource(ACCURACY_SOURCE, { type: "geojson", data: accuracyData(callbacks.current.accuracy) });
      map.addLayer({
        id: "location-accuracy-fill",
        type: "fill",
        source: ACCURACY_SOURCE,
        paint: { "fill-color": "#1d4ed8", "fill-opacity": 0.12 },
      }, "route-casing");
      map.addLayer({
        id: "location-accuracy-line",
        type: "line",
        source: ACCURACY_SOURCE,
        paint: { "line-color": "#1d4ed8", "line-width": 1.5, "line-opacity": 0.6 },
      }, "route-casing");
      map.addSource(WALK_SOURCE, { type: "geojson", data: walkFeatures(null), attribution: BIKESHARE_CREDIT });
      map.addLayer({
        id: "bikeshare-walk-casing",
        type: "line",
        source: WALK_SOURCE,
        layout: { "line-join": "round", "line-cap": "round", visibility: "none" },
        paint: { "line-color": WALK_CASING, "line-width": WALK_CASING_WIDTH, "line-opacity": 0.95 },
      });
      map.addLayer({
        id: "bikeshare-walk",
        type: "line",
        source: WALK_SOURCE,
        layout: { "line-join": "round", "line-cap": "round", visibility: "none" },
        paint: { "line-color": WALK_COLOUR, "line-width": WALK_LINE_WIDTH, "line-dasharray": WALK_DASH },
      });
      syncBikeshare(map, callbacks.current.route);
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
        loop: () => callbacks.current.loopVias === true,
        onStationPoint: (role, point) => callbacks.current.onStationPoint(role, point),
      });
      // The federal-land shading, for a Mass Ride (lib/federalLand.ts): fetched
      // the first time it is shown, under the stress overlay and the route.
      // The water and restrooms card first, so a tap on a fountain on federal land shows the fountain's.
      water = attachWaterInteraction(map, {
        visible: () => callbacks.current.waterPrefs?.on === true,
        otherPopupOpen: () => anyPopupOpen(),
        point: (id) => waterById.get(id),
      });
      waterSync.current = () => syncWater();
      syncWater();
      federal = attachFederalInteraction(map, {
        visible: () => callbacks.current.federalVisible,
        otherPopupOpen: () => anyPopupOpen() || water?.open() === true,
      });
      federalSync.current = () => syncFederal();
      syncFederal();
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
      federal?.detach();
      federalSync.current = null;
      water?.detach();
      waterSync.current = null;
      stressCheck.cancel();
      if (hoverFrame) cancelAnimationFrame(hoverFrame);
      gesture.cancel();
      longPress.cancel();
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("mouseup", onRightUp);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
      window.removeEventListener("keydown", onKey);
      canvas.removeEventListener("mouseleave", onCanvasLeave);
      canvas.removeEventListener("contextmenu", onContextMenu);
      canvas.removeEventListener("mousedown", onRightDown);
      closePopup(false);
      loaded.current = false;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      mapRef.current = null;
      setToolsHost(null);
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
      const { text, name, kind } = pointLabel(index, props.points.length, props.loopVias === true);
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
  }, markerDeps(props.points, props.markerReset, props.loopVias));

  // The route line.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    syncRoute(map, callbacks.current, fitted);
  }, [props.route, props.stale]);

  // A bikeshare plan's walk legs and the docks it uses. The markers are not buttons, since they
  // do nothing when pressed: each is an image with its whole text equivalent as its name, and
  // the route panel lists the same steps.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    syncBikeshare(map, props.route);
    const drawn = dockMarkers(bikeshareOf(props.route)).map((dock) => {
      const element = document.createElement("div");
      element.className = `dock-marker dock-${dock.role}`;
      element.setAttribute("role", "img");
      element.setAttribute("aria-label", dock.label);
      element.innerHTML = `${dockWheelSvg()}<span class="dock-badge" aria-hidden="true">${dock.badge}</span>`;
      // A click on a marker is not a click on the map: it must not add a via point.
      element.addEventListener("click", (event) => event.stopPropagation());
      return new maplibregl.Marker({ element, anchor: "center" }).setLngLat([dock.lon, dock.lat]).addTo(map);
    });
    return () => drawn.forEach((marker) => marker.remove());
  }, [props.route]);

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

  // Mass Ride: the map is coloured by capacity, and the stress colours and rails give way (OWNER-DECISIONS 325).
  useEffect(() => {
    setMassMode(
      loaded.current ? mapRef.current : null,
      props.massCapacity === true,
      callbacks.current.when,
      callbacks.current.stressVisible,
      props.massArea === true,
    );
  }, [props.massCapacity, props.massArea]);

  // The "Show bike lanes on high-stress roads" switch (OWNER-DECISIONS 275):
  // the rails' filters are set again in place, from the same tiles.
  useEffect(
    () =>
      subscribeHighStressLanes(() => onLaneSwitch(mapRef.current, loaded.current, callbacks.current.when)),
    [],
  );

  // The "Mountain-bike trails" layer (OWNER-DECISIONS 454): shown or hidden in place, from the same tiles.
  useEffect(
    () =>
      subscribeMtbTrails(() => {
        const map = mapRef.current;
        if (map && loaded.current) setStressVisibility(map, callbacks.current.stressVisible);
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
      // A marker with the focus (a zoom by keyboard from it, or a group's
      // zoom) hands it to its junction's new marker.
      const focused = junctionMarkers.current.find(({ marker }) => marker.getElement() === document.activeElement);
      if (focused && focusAfterZoom.current === null) focusAfterZoom.current = focused.group.members[0].index;
      junctionMarkers.current.forEach(({ marker }) => marker.remove());
      const groups = groupJunctions(junctionList.current, map.getZoom(), (item) => map.project([item.lon, item.lat]));
      junctionMarkers.current = groups.map((group) => {
        const [first] = group.members;
        const single = group.members.length === 1;
        const element = document.createElement("button");
        element.type = "button";
        element.className = `junction-marker junction-${group.severity}${single ? "" : " junction-group"}`;
        element.dataset.junctionIndex = String(first.index);
        element.innerHTML =
          warningIconSvg(group.severity, ICON_PX) +
          (single ? "" : `<span class="junction-count" aria-hidden="true">${group.members.length}</span>`);
        // The name alone: a title as well was read a second time, as the
        // description (a11y review, int-2).
        element.setAttribute("aria-label", single ? first.label : groupLabel(group));
        const marker = new maplibregl.Marker({ element, anchor: "center" }).setLngLat([first.lon, first.lat]).addTo(map);
        element.addEventListener("click", (event) => {
          // A click on a marker is not a click on the map: it must not add a via point.
          event.stopPropagation();
          if (single) {
            openCard(first, "marker");
            return;
          }
          const bounds = new maplibregl.LngLatBounds();
          group.members.forEach((m) => bounds.extend([m.lon, m.lat]));
          // The redraw at the zoom's end takes this button away; the focus
          // goes to the first member's new marker, not to the page's body.
          focusAfterZoom.current = document.activeElement === element ? first.index : null;
          // A fit that leaves the zoom as it was has no zoomend to redraw on.
          map.once("moveend", () => {
            if (focusAfterZoom.current !== null) draw();
          });
          map.fitBounds(bounds, { padding: 120, maxZoom: map.getMaxZoom(), duration: 500 });
        });
        element.addEventListener("dblclick", (event) => event.stopPropagation());
        return { group, marker };
      });
      const wanted = focusAfterZoom.current;
      focusAfterZoom.current = null;
      if (wanted !== null) markerFor(wanted)?.focus();
    };
    draw();
    map.on("zoomend", draw);
    return () => {
      map.off("zoomend", draw);
    };
  }, [props.route, props.stale]);

  // The Avoid-rated junctions the route passes (OWNER-DECISIONS 307-310): the skull and
  // crossbones on a ringed disc, drawn above the warning markers and larger than them. An
  // image whose name is the rating, the reason and the plea (309; the owner, 2026-10-10:
  // "this is a really bad idea, please reconsider"), never the glyph's; the list and the
  // description say the same in text. A button, as the junction markers are, so Tab reaches
  // it: a click, a tap, Enter or Space opens the road panel on the junction, which leads
  // with its warning ("Yes, also when clicking on the intersection"), and the focus comes
  // back to it when the panel closes. The I key or "Road info at map center" does the same.
  const avoidMarkers = useRef<Marker[]>([]);
  useEffect(() => {
    const map = mapRef.current;
    avoidMarkers.current.forEach((marker) => marker.remove());
    avoidMarkers.current = [];
    if (!map || !props.route || props.stale) return;
    avoidMarkers.current = avoidItems(props.route).map((item) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "avoid-marker";
      // The name alone, as the junction markers (a title as well is read twice).
      element.setAttribute("aria-label", avoidMarkerName(item));
      element.setAttribute("aria-haspopup", "dialog");
      element.innerHTML = avoidMarkerSvg();
      element.addEventListener("click", (event) => {
        // A click on a marker is not a click on the map: it must not add a via point.
        event.stopPropagation();
        callbacks.current.onRoadInfo?.({ point: [item.lon, item.lat], origin: "spot" });
      });
      element.addEventListener("dblclick", (event) => event.stopPropagation());
      return new maplibregl.Marker({ element, anchor: "center" }).setLngLat([item.lon, item.lat]).addTo(map);
    });
  }, [props.route, props.stale]);

  // A click on the summary's list: take the map there and say why.
  useEffect(() => {
    const map = mapRef.current;
    const focus = props.junctionFocus;
    if (!map || !focus) return;
    const found = junctionList.current.find((item) => item.index === focus.index);
    if (!found) return;
    // Centred in the part of the map the panel does not cover, so on a phone
    // the card is not under the sheet.
    map.easeTo({
      center: [found.lon, found.lat],
      zoom: Math.max(map.getZoom(), 15),
      duration: 500,
      padding: callbacks.current.framePadding(),
    });
    openCard(found, "list");
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

  // The accuracy circle of "Use my location" (drawn only; the marker is the point).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    (map.getSource(ACCURACY_SOURCE) as GeoJSONSource | undefined)?.setData(accuracyData(props.accuracy));
  }, [props.accuracy?.centre, props.accuracy?.radiusM]);

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

  // The elevation chart's scrub marker (OWNER-DECISIONS 322): a ring with a cross, so it is a shape and not a
  // colour, over the route; aria-hidden, because the chart says where it is in words. It stays on the screen.
  const scrubMarker = useRef<Marker | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    const point = props.scrubPoint ?? null;
    if (!map) return;
    if (point === null) {
      scrubMarker.current?.remove();
      scrubMarker.current = null;
      return;
    }
    if (!scrubMarker.current) {
      const element = document.createElement("div");
      element.className = "scrub-marker";
      element.setAttribute("aria-hidden", "true");
      scrubMarker.current = new maplibregl.Marker({ element, anchor: "center" }).setLngLat(point).addTo(map);
    } else {
      scrubMarker.current.setLngLat(point);
    }
    if (!map.getBounds().contains(point)) map.easeTo({ center: point, duration: 250, padding: callbacks.current.framePadding() });
  }, [props.scrubPoint]);

  // Ride mode's "you" marker and the follow camera.
  const riderMarker = useRef<Marker | null>(null);
  const following = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    const rider = props.rider ?? null;
    if (!map) return;
    if (rider === null) {
      riderMarker.current?.remove();
      riderMarker.current = null;
      following.current = false;
      return;
    }
    if (!riderMarker.current) {
      const element = document.createElement("div");
      element.className = "rider-marker";
      // The ride's own words say where the rider is (Where am I?); the arrow is for the eye.
      element.setAttribute("aria-hidden", "true");
      riderMarker.current = new maplibregl.Marker({ element, anchor: "center", rotationAlignment: "map", pitchAlignment: "map" })
        .setLngLat(rider.point)
        .addTo(map);
    } else {
      riderMarker.current.setLngLat(rider.point);
    }
    riderMarker.current.setRotation(rider.headingDeg ?? 0);
    riderMarker.current.getElement().classList.toggle("rider-marker-still", rider.headingDeg === null);
    if (!props.follow) {
      following.current = false;
      return;
    }
    const bearing = props.headingUp && rider.headingDeg !== null ? rider.headingDeg : props.headingUp ? map.getBearing() : 0;
    // Close in once as following starts; a pinch out after that is kept (it does not stop following).
    const zoom = following.current ? map.getZoom() : Math.max(map.getZoom(), 16);
    following.current = true;
    // A moving map once a second is too much for some: with reduced motion asked for, it jumps.
    const still = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    map.easeTo({ center: rider.point, bearing, zoom, duration: still ? 0 : 400 });
  }, [props.rider, props.follow, props.headingUp]);
  useEffect(() => () => void riderMarker.current?.remove(), []);

  // A pan or a turn of the map by hand pauses following (Re-centre resumes it). MapLibre's start events
  // carry the DOM event only when the rider made the move, not for the camera's own easeTo.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.follow) return;
    const broken = (event: { originalEvent?: unknown }) => {
      if (event.originalEvent) callbacks.current.onFollowBroken?.();
    };
    map.on("dragstart", broken);
    map.on("rotatestart", broken);
    return () => {
      map.off("dragstart", broken);
      map.off("rotatestart", broken);
    };
  }, [props.follow]);

  // The rail stations' toggles.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded.current) return;
    setRailVisibility(map, RAIL_STATIONS, props.rail);
  }, [props.rail.metro, props.rail.marc]);

  // The federal-land shading: on for a Mass Ride, off for any other ride type.
  useEffect(() => {
    federalSync.current?.();
  }, [props.federalVisible, props.federalWanted]);

  // The water and restrooms layer: its data when it comes, and the switch.
  useEffect(() => {
    waterSync.current?.();
  }, [props.water, props.waterPrefs]);

  return (
    <>
      <div ref={container} className="map" role="region" aria-label="Map" />
      {toolsHost && props.tools ? createPortal(props.tools, toolsHost) : null}
    </>
  );
}

/** The summary list's row for the junction at `index`. */
function rowFor(index: number): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.junction-item[data-junction-index="${index}"]`);
}

/** Where the focus is, for Escape and the junction card (lib/junctionCard.ts escapeClosesCard). */
function focusPlace(card: Popup | null, map: MapLibreMap): "card" | "opener" | "map" | "body" | "other" {
  const active = document.activeElement;
  if (active === null || active === document.body) return "body";
  if (card?.getElement().contains(active)) return "card";
  if (active.matches(".junction-marker, .junction-item")) return "opener";
  if (active === map.getCanvas()) return "map";
  return "other";
}

/**
 * The card a junction marker opens: its reason, and the way to avoid it. A
 * dialog named for the junction, so a screen reader says what it is rather
 * than "Close popup, button".
 */
function showJunctionCard(map: MapLibreMap, item: JunctionItem, takeFocus: boolean): Popup {
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
  const card = new maplibregl.Popup({
    closeButton: true,
    closeOnClick: true,
    // Taken below, if at all, once the card has its name.
    focusAfterOpen: false,
    offset: 16,
    className: `junction-popup junction-popup-${item.severity}`,
  })
    .setLngLat([item.lon, item.lat])
    .setDOMContent(body)
    .addTo(map);
  const element = card.getElement();
  element.setAttribute("role", "dialog");
  element.setAttribute("aria-label", cardName(item));
  const close = element.querySelector<HTMLButtonElement>(".maplibregl-popup-close-button");
  close?.setAttribute("aria-label", CARD_CLOSE_LABEL);
  if (takeFocus) close?.focus();
  return card;
}

/** A wheel: a plain circle with spokes, no operator's mark. */
function dockWheelSvg(): string {
  return (
    '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">' +
    '<circle cx="13" cy="13" r="11" fill="#ffffff" stroke="#1f1f1f" stroke-width="2.5"/>' +
    '<circle cx="13" cy="13" r="2" fill="#1f1f1f"/>' +
    '<path d="M13 4v18M4 13h18M6.6 6.6l12.8 12.8M19.4 6.6L6.6 19.4" stroke="#1f1f1f" stroke-width="1.2" fill="none"/>' +
    "</svg>"
  );
}

/** The walk legs on the map, and the layers' visibility, which is what shows the source citation. */
function syncBikeshare(map: MapLibreMap, route: RouteResponse | null): void {
  const source = map.getSource(WALK_SOURCE) as GeoJSONSource | undefined;
  if (!source) return;
  const plan = bikeshareOf(route);
  source.setData(walkFeatures(plan));
  const visibility = plan ? "visible" : "none";
  for (const id of ["bikeshare-walk-casing", "bikeshare-walk"]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
  }
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
  // A ride's camera follows the rider; a re-planned route is not framed over it.
  if (!route || stale || route.geometry.coordinates.length < 2 || props.rider) return;
  const padding = props.framePadding();
  if (fitted.current && routeInView(map, route.geometry.coordinates, padding)) return;
  fitted.current = true;
  const bounds = new maplibregl.LngLatBounds();
  route.geometry.coordinates.forEach((c) => bounds.extend(c));
  map.fitBounds(bounds, { padding, maxZoom: 15, duration: 600 });
}
