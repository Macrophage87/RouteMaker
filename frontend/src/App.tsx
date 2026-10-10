import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactElement, type ReactNode, type RefObject } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
import { RoadInfoDialog } from "./RoadInfoDialog.tsx";
import { MapTools } from "./MapTools.tsx";
import { ACCESS_HELP, ACCESS_LABEL, accessModeToggle, readAccessMode, writeAccessMode } from "./lib/accessMode.ts";
import { infoHelp, placeAtSpot, requestAfterClose, type InfoRequest } from "./lib/roadInfo.ts";
import { stationNearSpot } from "./lib/stationLinks.ts";
import { canDragLine, dropStillValid, insertIntoRide, legEnds, legPoints } from "./lib/lineEdit.ts";
import { EditHistory, isRedoKey, isUndoKey, typesText } from "./lib/editHistory.ts";
import { requestRoute, type RouteError, type RouteResponse, type RouteResult } from "./lib/api.ts";
import { MAX_POINTS, addPoint, insideCoverage, type LonLat } from "./lib/geo.ts";
import { formatClimb, formatDistance, formatDuration, formatSeconds } from "./lib/format.ts";
import { presetLabel, type PresetId } from "./lib/presets.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { stressSegments } from "./lib/stressBar.ts";
import { RouteScheduler, type SchedulerState } from "./lib/routeScheduler.ts";
import { confirmedUpTo, sendsConfirmation, spanKm } from "./lib/longRide.ts";
import { forgetPlan, isPlainClick, planToOpen, rememberPlanForSignIn, tabSession } from "./lib/signIn.ts";
import { STILL_PLANNING_AFTER_MS, announceRoute, calmSearchNote, detourView, paceText, pointName, stillPlanningSaid, movedPointsNote } from "./lib/summary.ts";
import { focusesPlanButton, isCancelKey, opensSheet, sheetOrder, type SheetSection } from "./lib/sheet.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, setMtbTrails, neutralPaletteSearch } from "./stressStyle.js";
import { HighStressLanesSwitch } from "./lib/highStressLanesSwitch.ts";
import { MtbTrailsSwitch } from "./lib/mtbTrailsSwitch.ts";
import { useHighStressLanes, useMtbTrails } from "./useStressStyle.ts";
import { useStressStyle } from "./useStressStyle.ts";
import { ANNOUNCE_SETTLE_MS, SettledText } from "./lib/settle.ts";
import { skipToPlanner, SKIP_LINK_TEXT, SKIP_TO_RIDE_TEXT } from "./lib/skipLink.ts";
import { AccessibilitySwitch } from "./lib/accessibilitySwitch.ts";
import { CandidatePicker } from "./lib/candidatePicker.ts";
import { BetaBanner, betaReportUrl, isBetaBuild } from "./lib/betaBanner.ts";
import { DialsPanel } from "./DialsPanel.tsx";
import { announceHow, candidateRoute, candidateRows } from "./lib/candidates.ts";
import { canReverse, loopNote, loopStops, loopView, reversedPoints, withLoop } from "./lib/loop.ts";
import {
  BEST_ORDER_LABEL,
  FINDING_ORDER_SAID,
  STILL_FINDING_ORDER_SAID,
  applyAnswer,
  requestStopOrder,
  stopsThatMove,
} from "./lib/stopOrder.ts";
import {
  addedSaid,
  editingTips,
  emptyPlanHint,
  insertedSaid,
  loneStartHint,
  loopChangeSaid,
  removedSaid,
  reversedSaid,
  reverseUnavailableHint,
  stationSaid,
} from "./lib/pointText.ts";
import { FacilityBreakdown } from "./FacilityBreakdown.tsx";
import { IntersectionList } from "./IntersectionList.tsx";
import { ElevationChart } from "./ElevationChart.tsx";
import { chartKind, foldName, usableProfile } from "./lib/profileChart.ts";
import { RouteDescription } from "./RouteDescription.tsx";
import { RIDE_SAFETY, RideMode, RideSettingsFields, startRideGesture, type RideView } from "./RideMode.tsx";
import { readRidePrefs, writeRidePrefs, type RidePrefs } from "./lib/rideOutput.ts";
import { RIDE_MAX_M, RIDE_TOO_LONG } from "./lib/navigate.ts";
import { RideTypePicker } from "./RideTypePicker.tsx";
import type { Dials } from "./lib/dials.ts";
import { WeightStore, withWeight, type StoredWeight } from "./lib/weight.ts";
import { stationEdit, type RailVisibility, type StationRole } from "./lib/railStations.ts";
import { RailStationsSection } from "./RailStations.tsx";
import { RAIL_STATIONS, WMATA_SLUGS } from "./lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "./lib/federalLand.ts";
import { FederalLandFor, FederalPointsList, type FederalStatus } from "./lib/federalLegend.ts";
import { addCoverageMask, fetchCoverage, watchForCapacity, watchForFacilities, watchZoom } from "./lib/mapGlue.ts";
import {
  CAPACITY_FOLD_TITLE,
  CAPACITY_LEGEND_TITLE,
  capacitySummary,
  isMassRide,
  massBandsChangeSaid,
  massBandsSaid,
} from "./lib/massCapacity.ts";
import { CapacityFigures, CapacityStats, MassLegend, MassZoomNotes } from "./lib/massLegend.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY, outsideDcNote } from "./lib/dcBoundary.ts";
import { MtbTrailLegend, StressLegend } from "./lib/stressLegend.ts";
import { PointsList } from "./lib/pointsList.ts";
import { movePoint, planEdits, travelSaid, type Snapshot as PlanSnapshot } from "./lib/planEdits.ts";
import { mapWhen } from "./lib/rideTime.ts";
import { registerStressProtocol } from "./lib/stressProtocol.ts";
import { refreshStressTiles } from "./lib/mapStyle.ts";
import * as maplibregl from "maplibre-gl";
import { PlaceSearch } from "./PlaceSearch.tsx";
import {
  FINDING_LOCATION,
  approximateHint,
  browserEnv,
  linkLocationNote,
  locate,
  locateSupport,
  maxPointsNotice,
  locateGate,
  movedFromHere,
  placeFix,
  type Fix,
} from "./lib/geolocation.ts";
import { usePlaceNames } from "./usePlaceNames.ts";
import { pickIntoPlan, pointRows, type Place, type PlaceChoice } from "./lib/geocode.ts";
import { GpxPanel, downloadGpx } from "./GpxPanel.tsx";
import {
  HighContrastShortcut,
  BottomBar,
  Fold,
  JunctionLegend,
  MoreTips,
  PlannerZoomNotice,
  QuickFigures,
  RideSettings,
  SheetFrame,
} from "./Sidebar.tsx";
import {
  COPY_LINK,
  MASS_RIDE_LAYERS_NOTE,
  PLANNER_EXTRAS,
  ROUTE_FOLDS,
  SHEET_TITLES,
  chartFoldOpen,
  copyText,
  PLANNER_TITLE,
  focusOnViewChange,
  foldTitle,
  linkSaidFor,
  linkSpokenFor,
  linkToCopy,
  noticeSaidElsewhere,
  rescueCompactFocus,
  searchLede,
  selectionCopy,
  type BarItem,
  type PanelView,
  type ViewCause,
} from "./lib/sidebar.ts";
import { rideSummary, rideSummarySpoken } from "./lib/rideSummary.ts";
import { quickFigures, stressBarKey, stressBarLabel } from "./lib/quickFigures.ts";
import { junctionItems } from "./lib/intersectionMarkers.ts";
import type { ImportedPlan } from "./lib/gpxPlan.ts";
import { loadWaterRestrooms, readWaterPrefs, saveWaterPrefs, waterAlongRoute, waterTitle, waterVisible, type WaterAlong, type WaterPoint, type WaterPrefs, type WaterStatus } from "./lib/waterRestrooms.ts";
import { WaterAlongList, WaterSection } from "./lib/waterLegend.ts";
import waterRestroomsUrl from "./amenity-data/water-restrooms.json?url";
import {
  findingSaid,
  requestNearest,
  searchNearest,
  NEAREST_STALE,
  STILL_SEARCHING,
  type Found,
  type Nearby,
  type NearestFrom,
  type NearestKind,
} from "./lib/nearest.ts";
import { NearestFinder } from "./lib/nearestFinder.ts";
import { namesToKeep, rideAfterImport, type Ride } from "./lib/gpxEdit.ts";

// Before the map adds the stress source (MapView, after its first probe).
registerStressProtocol(maplibregl);

/**
 * One entry of the undo history: the points as they were, and, for an edit
 * that also changed the ride type or the opened file (a GPX import, or Clear
 * of an imported plan), those too, so undo takes the whole edit back.
 */
type Snapshot = PlanSnapshot<LonLat[], Ride>;

interface Plan {
  points: LonLat[];
  preset: PresetId;
  confirmLong: boolean;
  dials: Dials;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "waiting"; seconds: number }
  | { kind: "ok" }
  | { kind: "error"; error: RouteError }
  | { kind: "confirm"; error: RouteError };

const initialPlan = decodePlan(planToOpen(tabSession(), window.location.hash));

const NARROW = "(max-width: 720px)";

/** Whether the phone layout (the bottom sheet) is showing, kept up to date. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const onChange = () => setNarrow(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

/** The points notice for a point outside the map, from a click, a station, or the rider's location. */
/** During a ride the map takes no edits and shows no plan pins (plan Q2: the plan stays as started). */
const NO_POINTS: LonLat[] = [];
const ignore = () => undefined;

const OUTSIDE_NOTICE = "That point is outside the area this map covers (the DC region to Baltimore).";

export function App() {
  const [points, setPoints] = useState<LonLat[]>(initialPlan.points);
  const [preset, setPreset] = useState<PresetId>(initialPlan.preset);
  const [dials, setDials] = useState<Dials>(initialPlan.dials);
  // The rider and bike weight (OWNER-DECISIONS 313-318): kept apart from `dials`, which
  // the link carries, and added only to the request (planDials).
  const weightStore = useRef<WeightStore | null>(null);
  if (weightStore.current === null) weightStore.current = new WeightStore();
  const [weight, setWeight] = useState<StoredWeight | null>(() => weightStore.current?.load() ?? null);
  const [weightRemembered, setWeightRemembered] = useState(() => weightStore.current?.remembered() ?? false);
  const planDials = useMemo(() => withWeight(dials, weight), [dials, weight]);
  // "Make it a loop" chosen (OWNER-DECISIONS 374): the first point is the start and finish, every later one a stop.
  const loopVias = loopStops(preset, dials.loop);
  // What the planner answered, and which of its routes to choose from is shown
  // (OWNER-DECISIONS 265): 0 is the answer, the others its candidates.
  const [answer, setRoute] = useState<RouteResponse | null>(null);
  const [choice, setChoice] = useState(0);
  // Whether the rider chose the route shown (it is then said as chosen, not as planned: the a11y review's N4).
  const [chosen, setChosen] = useState(false);
  useEffect(() => {
    setChoice(0);
    setChosen(false);
  }, [answer]);
  const choose = useCallback((index: number) => {
    setChoice(index);
    setChosen(true);
  }, []);
  const route = candidateRoute(answer, choice);
  const [routedPoints, setRoutedPoints] = useState<LonLat[]>([]);
  // Whether that route was planned as a loop the rider chose, recorded with its
  // points: during a replan the toggle may already say otherwise, and the GPX
  // names the route shown, not the one asked for (OWNER-DECISIONS 374).
  const [routedLoop, setRoutedLoop] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [notice, setNotice] = useState<string | null>(null);
  const [stress, setStress] = useState<StressAvailability>("checking");
  const [stressVisible, setStressVisible] = useState(true);
  useStressStyle();
  const showHighLanes = useHighStressLanes();
  const showMtbTrails = useMtbTrails();
  const [rail, setRail] = useState<RailVisibility>({ metro: true, marc: true });
  // The Mass Ride map's federal-land shading (lib/federalLand.ts): the rider's
  // own switch, on by default, and whether its data has arrived.
  const [federalOn, setFederalOn] = useState(true);
  const [federalStatus, setFederalStatus] = useState<FederalStatus>("loading");
  const [federalData, setFederalData] = useState<FederalData | null>(null);
  // Public water and restrooms (lib/waterRestrooms.ts): on by default for every ride type, its
  // switches kept on this device; the data is fetched the first time it is shown.
  const [waterPrefs, setWaterPrefsState] = useState<WaterPrefs>(() => readWaterPrefs());
  const changeWaterPrefs = (next: WaterPrefs) => {
    setWaterPrefsState(next);
    saveWaterPrefs(next);
  };
  const [waterStatus, setWaterStatus] = useState<WaterStatus>("loading");
  const [waterData, setWaterData] = useState<WaterPoint[] | null>(null);
  // One load at a time, shared by the layer and the nearest-water search (which loads it with the layer
  // off too); a load that failed is forgotten, so the next asks again.
  const waterLoad = useRef<Promise<WaterPoint[] | null> | null>(null);
  const ensureWater = useCallback(() => {
    if (!waterLoad.current) {
      setWaterStatus("loading");
      waterLoad.current = loadWaterRestrooms(waterRestroomsUrl).then((data) => {
        if (!data) waterLoad.current = null;
        setWaterData(data);
        setWaterStatus(data ? "ready" : "unavailable");
        return data;
      });
    }
    return waterLoad.current;
  }, []);
  const waterOn = waterPrefs.on;
  useEffect(() => {
    if (waterOn) void ensureWater();
  }, [waterOn, ensureWater]);
  // Whether the grey coverage mask is on the map, and whether the stress tiles
  // carry bike-facility data; each legend line is shown only when it is true.
  const [coverageShown, setCoverageShown] = useState(false);
  const [facilitiesShown, setFacilitiesShown] = useState<ReadonlySet<string>>(new Set());
  // The stress tiles carry the Mass Ride capacity (a table built before the column does not): the Mass Ride
  // map, legend and panel are then about riders per minute, and otherwise as they were (OWNER-DECISIONS 325, 387).
  const [capacityTiles, setCapacityTiles] = useState(false);
  const massMap = isMassRide(preset) && capacityTiles;
  const [zoom, setZoom] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  // Which view the panel body shows: the planner, or one of the bottom bar's sheets (Map layers,
  // which Legend opens scrolled to the legend, GPX, Settings). The planner stays in the page, hidden,
  // so nothing it holds is lost (OWNER-DECISIONS 312).
  const [view, setView] = useState<PanelView>("planner");
  const [legendTarget, setLegendTarget] = useState(false);
  // With a route shown the points are two or three lines and "Edit points" (the mockup's route view);
  // this opens the search, Add point and the rest again.
  const [editPoints, setEditPoints] = useState(false);
  const barButtons = useRef<Partial<Record<BarItem["id"], HTMLButtonElement | null>>>({});
  const openedBy = useRef<BarItem["id"]>("layers");
  const prevView = useRef<PanelView>("planner");
  // Why the view last changed (lib/sidebar.ts focusOnViewChange): a bar button, Back, or an error or
  // the long-ride question bringing the planner back.
  const viewCause = useRef<ViewCause>("bar");
  const errorRef = useRef<HTMLDivElement>(null);
  const pointsSearchRef = useRef<HTMLDivElement>(null);
  const pointsEditRef = useRef<HTMLDivElement>(null);
  const editPointsRef = useRef<HTMLButtonElement>(null);
  const wasCompact = useRef(false);
  const layersHeadingRef = useRef<HTMLHeadingElement>(null);
  const legendHeadingRef = useRef<HTMLHeadingElement>(null);
  const gpxHeadingRef = useRef<HTMLHeadingElement>(null);
  const plannerHeadingRef = useRef<HTMLHeadingElement>(null);
  const settingsHeadingRef = useRef<HTMLHeadingElement>(null);
  // What "Copy link" answered: said politely, and again for a second press. The spoken one adds the
  // location note when the link includes the rider's location (OWNER-DECISIONS 395).
  const [linkSaid, setLinkSaid] = useState("");
  const [linkSpoken, setLinkSpoken] = useState("");
  const linkPresses = useRef(0);
  // The span, in km, the rider has said yes to planning (longRide.ts).
  const [confirmedKm, setConfirmedKm] = useState<number | null>(null);
  const [crosshair, setCrosshair] = useState({ button: false, canvas: false });
  // The road panel's spot (OWNER-DECISIONS 441a), or null while it is closed.
  const [roadInfo, setRoadInfo] = useState<InfoRequest | null>(null);
  const closeRoadInfo = useCallback(
    (closed: InfoRequest | null) => setRoadInfo((current) => requestAfterClose(current, closed)),
    [],
  );
  // The map is where the focus goes when the road panel's opener cannot take it back (a long press).
  const mapFocus = useCallback(() => mapRef.current?.getCanvas() ?? null, []);
  // Map tools (OWNER-DECISIONS 450) shows the crosshair while it is open.
  // Accessibility mode (OWNER-DECISIONS 455; lib/accessMode.ts): off unless turned on, kept on this device.
  // Map tools is on the page only while it is on.
  const [accessMode, setAccessMode] = useState(() => readAccessMode());
  const toolsToggleRef = useRef<HTMLButtonElement>(null);
  const focusToolsNext = useRef(false);
  const focusAtPress = useRef<Element | null>(null);
  const toolsCrosshair = useCallback((on: boolean) => setCrosshair((c) => (c.button === on ? c : { ...c, button: on })), []);
  // The junction a click on the route summary's list names; `nonce` makes a second
  // click on the same one open its card again.
  const [junctionFocus, setJunctionFocus] = useState<{ index: number; nonce: number } | null>(null);
  // The point on the route the elevation chart is reading (OWNER-DECISIONS 322), or null.
  const [scrubPoint, setScrubPoint] = useState<LonLat | null>(null);
  // Bumped to put the markers back where the points are, without changing
  // the points (which would plan the same route again).
  const [markerReset, setMarkerReset] = useState(0);
  // Undo and redo (editHistory.ts), and whether each has anything to give
  // back, which is what their buttons need to know.
  const history = useRef(new EditHistory<Snapshot>());
  const [can, setCan] = useState({ undo: false, redo: false });
  // What an edit on the map did, for a screen reader: the map itself says
  // nothing. The count makes the same sentence twice a new announcement.
  const [said, setSaid] = useState({ text: "", count: 0 });
  // "Use my location" (OWNER-DECISIONS 395). The fix's accuracy and the flag that a point came from the
  // location are kept in memory only: never in storage, the link, a GPX file or a log. The point itself is
  // in the plan like any clicked point, so it is in the address bar and the link at full precision, by
  // design (and in this tab's sessionStorage for a sign-in round trip only: lib/signIn.ts). Whether a
  // point came from the location is whether its object is in `fromHere` (linkLocationNote); a drag of
  // such a point adds the moved one too (movedFromHere), so the note stays.
  const [here, setHere] = useState<Fix | null>(null);
  // Every point that came from a look-up, or a drag of one, for the link note (the start may be an earlier
  // one than `here`). Not capped: a few points of memory, and a cap could drop a start still in the plan.
  const [fromHere, setFromHere] = useState<LonLat[]>([]);
  const [locating, setLocating] = useState(false);
  // One look-up at a time, set before the await, so a second call in the same tick is refused too.
  const gate = useRef(locateGate()).current;
  // The 150 ms re-set of a look-up's notice; a map edit in that window cancels it (the correctness review's N2).
  const locateNoticeTimer = useRef<number | undefined>(undefined);
  const cancelLocateNotice = () => window.clearTimeout(locateNoticeTimer.current);
  const geoEnv = useMemo(() => browserEnv(), []);
  const locateReady = locateSupport(geoEnv);
  // The GPX file opened last (GpxPanel), until the plan is cleared.
  const [imported, setImported] = useState<ImportedPlan | null>(null);
  // The ride type, the sliders and the opened file as they are now, for the
  // undo history (kept current at once by applyRide, like pointsRef).
  const rideRef = useRef<Ride>({ preset, dials, imported });
  rideRef.current = { preset, dials, imported };
  const narrow = useNarrow();
  // Ride mode (WEB-NAV-plan.md; RideMode.tsx): whether a ride is on, the Start ride question, the ride's
  // own route and the rider for the map (in memory only: never the link, storage or a log), the camera.
  // A ride's re-plans live here, not in `points`, so the address bar keeps the plan as started (plan Q2).
  const [ridePrefs, setRidePrefs] = useState<RidePrefs>(() => readRidePrefs());
  const [riding, setRiding] = useState(false);
  // What the ride started from, captured at Start ride: the ride never follows the planner's own route,
  // which a failed or changed plan could take away mid-ride.
  const [rideStart, setRideStart] = useState<{ route: RouteResponse; points: LonLat[]; loop: boolean; dials: Dials } | null>(null);
  const [rideAsk, setRideAsk] = useState(false);
  const [rideView, setRideView] = useState<RideView | null>(null);
  const [follow, setFollow] = useState(true);
  const [headingUp, setHeadingUp] = useState(false);
  const [bigText, setBigText] = useState(false);
  const startRideRef = useRef<HTMLButtonElement>(null);
  const rideStartFirstRef = useRef<HTMLButtonElement>(null);
  const focusStartAfterRide = useRef(false);
  // The Start ride button pressed (under the figures or in Directions): where the focus goes back to.
  const rideOpener = useRef<HTMLElement | null>(null);
  const rideCircle = rideView?.rider ? { centre: rideView.rider.point, radiusM: rideView.rider.accuracyM } : null;
  const changeRidePrefs = useCallback((next: RidePrefs) => {
    writeRidePrefs(next);
    setRidePrefs(next);
  }, []);
  const mapRef = useRef<MapLibreMap | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const removeRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const planButtonRef = useRef<HTMLButtonElement>(null);
  const routeHeadingRef = useRef<HTMLHeadingElement>(null);
  const pointsHeadingRef = useRef<HTMLHeadingElement>(null);
  const focusAfterRemove = useRef<number | null>(null);
  const writtenHash = useRef<string>("");
  const { gate: geoGate, namer } = usePlaceNames(points);

  // One scheduler for the page: one request in flight, the latest plan only,
  // Retry-After waited out (routeScheduler.ts).
  const scheduler = useRef<RouteScheduler<Plan> | null>(null);
  if (scheduler.current === null) {
    scheduler.current = new RouteScheduler<Plan>({
      send: (plan) => requestRoute(plan.points, plan.preset, { confirmLong: plan.confirmLong, dials: plan.dials }),
      onState: (state: SchedulerState) => {
        if (state.kind === "in-flight" || state.kind === "pending") setStatus({ kind: "loading" });
        else if (state.kind === "waiting") setStatus({ kind: "waiting", seconds: state.seconds });
      },
      onResult: (plan: Plan, result: RouteResult) => {
        if (result.ok) {
          setRoute(result.route);
          setRoutedPoints(plan.points);
          setRoutedLoop(loopStops(plan.preset, plan.dials.loop));
          setStatus({ kind: "ok" });
        } else if (result.error.kind === "confirm-long") {
          setRoute(null);
          setStatus({ kind: "confirm", error: result.error });
        } else {
          setRoute(null);
          setStatus({ kind: "error", error: result.error });
        }
      },
    });
  }

  // An old link's palette value (`cvd`, `blended`) is renamed in the address bar to its
  // neutral name, once, so copying the address does not pass it on (321; S4).
  useEffect(() => {
    const search = neutralPaletteSearch(window.location.search);
    if (search !== null) window.history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
  }, []);

  // Keep the link in step with the plan, without adding history entries. Exactly encodePlan's
  // fragment, which never holds the weight (313); Copy link builds the same one (linkToCopy).
  useEffect(() => {
    const hash = encodePlan(points, preset, dials);
    writtenHash.current = hash;
    window.history.replaceState(null, "", hash);
    // "Link copied." was about the link before this change (the correctness review's N4).
    linkPresses.current += 1;
    setLinkSaid("");
    setLinkSpoken("");
  }, [points, preset, dials]);

  // A link pasted into this tab, or the back button, changes the fragment
  // without a reload: open the plan it names.
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === writtenHash.current) return;
      const plan = decodePlan(window.location.hash);
      setConfirmedKm(null);
      // Another plan: undo does not reach back into the one before it.
      history.current.clear();
      setCan({ undo: false, redo: false });
      rideRef.current = { preset: plan.preset, dials: plan.dials, imported: null };
      setImported(null);
      // Another plan's route opens compact, as a first route does.
      setEditPoints(false);
      setPoints(plan.points);
      setPreset(plan.preset);
      setDials(plan.dials);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // The browser's Back button can restore this page from its back/forward cache with no new load,
  // so `planToOpen` never reads the plan kept for the stress page or the sign-in link. That Back
  // undid the trip the copy was kept for: drop it, so it cannot bring back a plan the rider
  // clears next (the correctness re-check's C8).
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) forgetPlan(tabSession());
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  // Route whenever the plan changes.
  useEffect(() => {
    if (points.length < 2) {
      scheduler.current?.clear();
      setRoute(null);
      setStatus({ kind: "idle" });
      // The next route opens compact again (the correctness review's N1).
      setEditPoints(false);
      return;
    }
    scheduler.current?.request({ points, preset, dials: planDials, confirmLong: sendsConfirmation(points, confirmedKm) });
  }, [points, preset, planDials, confirmedKm]);

  // The long-ride question and every error are in the sheet; on a phone whose
  // sheet is hidden they would otherwise be invisible, so the sheet opens
  // (sheet.ts), for each new one.
  useEffect(() => {
    if (opensSheet(status.kind)) {
      setPanelOpen(true);
      // The question and the errors are in the planner, not in a bar sheet; if a sheet was open, the
      // focus goes to the error or the question, not back to the bar button.
      viewCause.current = status.kind === "confirm" ? "confirm" : "error";
      setView("planner");
    }
  }, [status]);

  // Where the focus goes when the view changes (lib/sidebar.ts focusOnViewChange, where every
  // transition is tested): a sheet's heading (the legend's, for Legend), the bar button that
  // opened it on the way back, or the error or the long-ride question that brought the planner back.
  useEffect(() => {
    const was = prevView.current;
    prevView.current = view;
    const target = focusOnViewChange({ was, view, legendTarget, openedBy: openedBy.current, cause: viewCause.current });
    if (target === null) return;
    if (target.kind === "bar") barButtons.current[target.id]?.focus();
    else if (target.kind === "error") errorRef.current?.focus();
    else if (target.kind === "plan") planButtonRef.current?.focus();
    else if (target.kind === "planner") {
      // The Plan button (OWNER-DECISIONS 392): the planner's heading, at the top of the panel.
      plannerHeadingRef.current?.focus();
      panelBodyRef.current?.scrollTo?.({ top: 0 });
    }
    else {
      const heading = target.legend ? legendHeadingRef : { layers: layersHeadingRef, gpx: gpxHeadingRef, settings: settingsHeadingRef }[target.view];
      heading.current?.focus();
      heading.current?.scrollIntoView?.({ block: "start" });
    }
  }, [view, legendTarget]);

  // The long-ride question takes the focus when it comes, so a keyboard rider lands on it (once the
  // sheet is open: a hidden button cannot take it). Not again on the way back from a bar sheet while
  // it is pending: Back goes to the bar button (the correctness review's N8); a question that came
  // while a sheet was open takes the focus through the effect above.
  const focusPlan = focusesPlanButton(status.kind, panelOpen);
  const viewNow = useRef(view);
  viewNow.current = view;
  useEffect(() => {
    if (focusPlan && viewNow.current === "planner") planButtonRef.current?.focus();
  }, [focusPlan]);

  // After Remove, the focus goes to the next Remove button, or (none left) to the search.
  useEffect(() => {
    const index = focusAfterRemove.current;
    if (index === null) return;
    focusAfterRemove.current = null;
    const target = removeRefs.current[Math.min(index, points.length - 1)];
    (target ?? pointsSearchRef.current?.querySelector<HTMLElement>("input"))?.focus();
  }, [points]);

  // The latest points, for handlers the map holds on to between renders.
  const pointsRef = useRef(points);
  pointsRef.current = points;

  const announce = useCallback((text: string) => setSaid((s) => ({ text, count: s.count + 1 })), []);
  // Turn accessibility mode on or off, say so, and keep it (lib/accessMode.ts accessModeToggle). From the page's
  // first button, turning it on puts the focus on Map tools (focusTools); turning it off leaves the focus on the
  // switch pressed, which is always on the page.
  const toggleAccessMode = useCallback(
    (focusTools: boolean) => {
      const step = accessModeToggle(accessMode, focusTools);
      writeAccessMode(step.next);
      focusToolsNext.current = step.focusTools;
      focusAtPress.current = document.activeElement;
      setAccessMode(step.next);
      announce(step.said);
    },
    [accessMode, announce],
  );
  // Map tools tells App when it is on the page (its onShown). That is the same commit as the press once the map
  // is built, or later while the map is still loading; the move waits for it, and is dropped if the rider has
  // moved on in the meantime (the focus is no longer where it was at the press; the a11y review's N5).
  const toolsShown = useCallback(() => {
    if (!focusToolsNext.current) return;
    focusToolsNext.current = false;
    const now = document.activeElement;
    if (!now || now === document.body || now === focusAtPress.current || now.classList.contains("access-link")) toolsToggleRef.current?.focus();
  }, []);

  // The points notice ("outside the area", "at most 25 points") is a status in the Points section; while a
  // bar sheet or the phone's hidden sheet hides the planner it would say nothing, so it is said through
  // the app-level region then, and only then (no second reading while the planner shows it; recheck S1).
  const plannerShownNow = useRef(true);
  plannerShownNow.current = view === "planner" && panelOpen;
  useEffect(() => {
    if (noticeSaidElsewhere(notice, plannerShownNow.current)) announce(notice as string);
  }, [notice, announce]);

  // Which bands the Mass Ride map shows changes with the zoom (OWNER-DECISIONS 421). The legend's status
  // line says it; while the Map layers sheet is not on screen it is said through the app-level region
  // instead, and only when the set of bands changes (not at every zoom step, nor on coming to the map).
  const massBands = massMap && stressVisible ? massBandsSaid(zoom) : null;
  const massBandsBefore = useRef<string | null>(null);
  const layersShownNow = useRef(false);
  layersShownNow.current = view === "layers" && panelOpen;
  // Only for a zoom the rider made: after the first fit to a route, or a place search's fly-to, the
  // route's or the place's own sentence is what matters (accessibility review S4).
  const zoomByRider = useRef(false);
  useEffect(() => {
    const said = massBandsChangeSaid(massBandsBefore.current, massBands, layersShownNow.current);
    massBandsBefore.current = massBands;
    if (said && zoomByRider.current) announce(said);
  }, [massBands, announce]);

  const syncHistory = useCallback(
    () => setCan({ undo: history.current.canUndo, redo: history.current.canRedo }),
    [],
  );

  const applyRide = useCallback((ride: Ride) => {
    rideRef.current = ride;
    setPreset(ride.preset);
    setDials(ride.dials);
    setImported(ride.imported);
  }, []);

  // The plan's edits and its undo and redo (lib/planEdits.ts, where they are
  // tested). An edit that also sets the ride type or the opened file (`ride`)
  // records those as they were too, and undo restores them with the points:
  // one step.
  const edits = useMemo(
    () =>
      planEdits<LonLat[], Ride>({
        history: history.current,
        current: () => pointsRef.current,
        ride: () => rideRef.current,
        set: (next) => {
          // Kept current at once, so a second edit before the next render builds on this one.
          pointsRef.current = next;
          setPoints(next);
        },
        applyRide,
        sync: syncHistory,
      }),
    [syncHistory, applyRide],
  );

  /** Every edit of the points goes through here, so undo can give the list before it back. */
  const commit = edits.commit;

  /** Undo or redo: the list the history gives back, which is not itself an edit. */
  const travel = useCallback(
    (direction: "undo" | "redo") => {
      const before = rideRef.current;
      const next = edits.travel(direction);
      if (next === undefined) return;
      setNotice(null);
      // A step that brings another loop state back renames the points too (OWNER-DECISIONS 374).
      const renamed = loopChangeSaid(before, rideRef.current, next.length);
      const said = travelSaid(direction, next.length);
      announce(renamed ? `${said} ${renamed}` : said);
    },
    [announce, edits],
  );
  const undo = useCallback(() => travel("undo"), [travel]);
  const redo = useCallback(() => travel("redo"), [travel]);

  // Ctrl+Z (Cmd+Z) undoes; Ctrl+Shift+Z (Cmd+Shift+Z) and Ctrl+Y redo;
  // anywhere but a text field, which has its own.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // A ride keeps the plan as started (plan Q2): no undo or redo under it.
      if (riding || typesText(event.target as HTMLElement | null)) return;
      if (isUndoKey(event)) {
        event.preventDefault();
        undo();
      } else if (isRedoKey(event)) {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo, riding]);

  const place = useCallback((point: LonLat) => {
    cancelLocateNotice();
    if (!insideCoverage(point)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    if (pointsRef.current.length >= MAX_POINTS) {
      setNotice(maxPointsNotice());
      return;
    }
    setNotice(null);
    const next = addPoint(pointsRef.current, point, loopVias);
    commit(next);
    announce(addedSaid(next.indexOf(point), next.length, loopVias));
  }, [commit, announce, loopVias]);

  // "Use my location": one look-up per press (lib/geolocation.ts), then placeFix decides: from the button,
  // the map click's path; from the "Your location" choice, the search's Start / Destination / Stop choice.
  // A failure is the Points notice (a status, said once; through the app region only while the planner is
  // hidden). It is cleared and set again a moment later, so a second press with the same answer is said again.
  const useMyLocation = useCallback(async (choice?: PlaceChoice) => {
    const press = gate.begin();
    if (press === null) {
      // A press while one is under way still gets an answer.
      announce(FINDING_LOCATION);
      return;
    }
    setLocating(true);
    cancelLocateNotice();
    setNotice(null);
    announce(FINDING_LOCATION);
    const result = await locate(geoEnv);
    if (!gate.finish(press)) return;
    setLocating(false);
    // The ride as it is now, not as it was at the press: the rider may have turned the loop on or off meanwhile.
    const ride = rideRef.current;
    const placed = placeFix(result, pointsRef.current, { loop: loopStops(ride.preset, ride.dials.loop), choice });
    if ("refuse" in placed) {
      setNotice(null);
      locateNoticeTimer.current = window.setTimeout(() => {
        if (gate.latest(press)) setNotice(placed.refuse);
      }, 150);
      return;
    }
    setNotice(null);
    commit(placed.next);
    announce(placed.said);
    if (result.ok) setHere(result.fix);
    setFromHere((prior) => [...prior, placed.point]);
    mapRef.current?.flyTo({ center: placed.point, zoom: Math.max(mapRef.current.getZoom(), 14) });
  }, [gate, geoEnv, announce, commit]);
  const hereInPlan = here !== null && points.includes(here.point);
  // The accuracy circle: the located point's while it is in the plan; during a ride, the rider's.
  const hereCircle = hereInPlan && here ? { centre: here.point, radiusM: here.accuracyM } : null;

  const move = useCallback((index: number, point: LonLat) => {
    cancelLocateNotice();
    if (!insideCoverage(point)) {
      setNotice("That point is outside the area this map covers; it was put back.");
      setMarkerReset((n) => n + 1);
      return;
    }
    setNotice(null);
    // A dragged location point keeps the Copy link note: the moved point is still the rider's spot. The old
    // point is read now, not inside the updater: React may run the updater after commit() has replaced
    // pointsRef.current (when an update, such as the setNotice above, is already pending; correctness R1).
    const before = pointsRef.current[index];
    setFromHere((prior) => movedFromHere(prior, before, point));
    commit(movePoint(pointsRef.current, index, point));
  }, [commit]);

  // The route line dragged (or clicked) at `point` from leg `leg`: a via in
  // that leg (lineEdit.ts). `routed` is the list the line was planned for;
  // if the points have changed since, the leg means nothing any more. In a
  // loop the closing leg, back to the start, appends the stop
  // (OWNER-DECISIONS 374).
  const insertOnLine = useCallback(
    (leg: number, point: LonLat, routed: LonLat[]) => {
      if (!dropStillValid(routed, pointsRef.current)) return;
      if (!insideCoverage(point)) {
        setNotice("That point is outside the area this map covers; it was put back.");
        return;
      }
      const next = insertIntoRide(routed, leg, point, loopVias);
      if (next === null) {
        setNotice(`A route can have at most ${MAX_POINTS} points.`);
        return;
      }
      setNotice(null);
      commit(next);
      announce(insertedSaid(leg, next.length, loopVias));
    },
    [commit, announce, loopVias],
  );

  // A station's Start here / End here / Add as stop (railStations.ts): an
  // edit of the points like any other, so it can be undone and redone.
  const placeStation = useCallback((role: StationRole, point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That station is outside the area this map covers.");
      return;
    }
    const edit = stationEdit(pointsRef.current, point, role, loopVias);
    if ("refused" in edit) {
      if (edit.refused === "cap") setNotice(`A route can have at most ${MAX_POINTS} points.`);
      return;
    }
    setNotice(null);
    commit(edit.next);
    announce(stationSaid(edit.index, edit.next.length, loopVias));
  }, [commit, announce, loopVias]);

  // The road panel's Set as start / Set as end / Add as stop (OWNER-DECISIONS 441n): the spot
  // right-clicked or held (or the map's center by keyboard), as the search's choice places a
  // place: the coverage check, the cap, the loop; an edit like any other, undone and redone.
  const placeSpot = useCallback((choice: PlaceChoice, point: LonLat) => {
    cancelLocateNotice();
    if (!insideCoverage(point)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    if (choice === "via" && pointsRef.current.length >= MAX_POINTS) {
      setNotice(maxPointsNotice());
      return;
    }
    setNotice(null);
    const placed = placeAtSpot(pointsRef.current, point, choice, loopVias);
    commit(placed.next);
    announce(placed.said);
  }, [commit, announce, loopVias]);

  // Find the nearest water, restroom or Metro station (lib/nearest.ts; owner, 2026-10-10): from the
  // rider's location, the map's center or the plan's start, the three nearest by bike on this ride's
  // own settings. A pick is an edit like any other: Ride here plans from there to it (one edit, so
  // Undo puts the plan back), Add as stop puts it into the plan. The location look-up is this
  // search's own; its fix is kept only as Use my location's is (in memory, in `here`).
  const nearestFromOptions: NearestFrom[] = [
    ...(locateReady.available ? (["location"] as const) : []),
    "centre",
    ...(points.length > 0 ? (["start"] as const) : []),
  ];
  const [nearestFromChosen, setNearestFrom] = useState<NearestFrom>(locateReady.available ? "location" : "centre");
  const nearestFrom = nearestFromOptions.includes(nearestFromChosen) ? nearestFromChosen : nearestFromOptions[0];
  const [nearestBusy, setNearestBusy] = useState(false);
  const nearestBusyRef = useRef(false);
  const [nearestStatus, setNearestStatus] = useState("");
  const [nearestList, setNearestList] = useState<Found | null>(null);
  // The status line is cleared and set again a moment later, so the same words twice are said twice
  // (as the Points notice is); with the planner out of sight it is said through the app's region.
  const nearestTimer = useRef<number | undefined>(undefined);
  const sayNearest = (text: string) => {
    window.clearTimeout(nearestTimer.current);
    setNearestStatus("");
    nearestTimer.current = window.setTimeout(() => setNearestStatus(text), 150);
    if (!plannerShownNow.current) announce(text);
  };
  // A list is for the ride and the spot it was found for: a new ride type or slider (other distances),
  // a new "Search from", or a start that moved under a "start" search put it away.
  // Not the loop: Ride here turns it off in its own edit, and the list stays for a second pick. A search
  // under way when one changes is thrown away when it answers (the epoch).
  const nearestKey = JSON.stringify([preset, { ...dials, loop: false }, nearestFrom]);
  const nearestEpoch = useRef(0);
  useEffect(() => {
    nearestEpoch.current += 1;
    setNearestList(null);
  }, [nearestKey]);
  useEffect(() => {
    if (nearestList?.from === "start" && String(points[0]) !== String(nearestList.origin)) setNearestList(null);
  }, [points, nearestList]);
  const findNearest = async (kind: NearestKind) => {
    if (nearestBusyRef.current) {
      sayNearest(STILL_SEARCHING);
      return;
    }
    nearestBusyRef.current = true;
    setNearestBusy(true);
    setNearestList(null);
    sayNearest(findingSaid(kind));
    const ride = rideRef.current;
    const epoch = nearestEpoch.current;
    try {
      const outcome = await searchNearest({
        kind,
        from: nearestFrom,
        locate: async () => {
          // Use my location's gate: one look-up at a time, whichever asked.
          const press = gate.begin();
          if (press === null) return "busy";
          setLocating(true);
          const result = await locate(geoEnv);
          gate.finish(press);
          setLocating(false);
          return result;
        },
        start: () => pointsRef.current[0] ?? null,
        centre: () => {
          const centre = mapRef.current?.getCenter();
          return centre ? [centre.lng, centre.lat] : null;
        },
        inside: insideCoverage,
        water: ensureWater,
        stations: RAIL_STATIONS,
        request: (from, places) => requestNearest(from, places, ride.preset, ride.dials),
      });
      if (outcome.fix) setHere(outcome.fix);
      if (outcome.found && epoch !== nearestEpoch.current) {
        sayNearest(NEAREST_STALE);
        return;
      }
      if (outcome.found) setNearestList(outcome.found);
      sayNearest(outcome.said);
    } finally {
      nearestBusyRef.current = false;
      setNearestBusy(false);
    }
  };
  const rideToNearest = (item: Nearby) => {
    if (!nearestList) return;
    const { origin, from } = nearestList;
    const had = pointsRef.current.length > 0;
    namer.remember(item.place.point, item.place.title);
    const ride = rideRef.current;
    // To a place and no further: a loop the rider had on is turned off, in the same edit.
    commit([origin, item.place.point], ride.dials.loop ? { ...ride, dials: { ...ride.dials, loop: false } } : undefined);
    if (from === "location") setFromHere((prior) => [...prior, origin]);
    setNotice(null);
    announce(`Planning a route to ${item.place.title}.${had ? " Undo puts your plan back." : ""}`);
  };
  const addNearestStop = (item: Nearby) => {
    namer.remember(item.place.point, item.place.title);
    placeSpot("via", item.place.point);
  };

  // A place picked from search: the start, the destination or a stop, as chosen
  // (geocode.ts, applyPlace), named as it was found, and the map goes there.
  const pickPlace = (found: Place, choice: PlaceChoice) => {
    cancelLocateNotice();
    const point = pickIntoPlan(found, choice, {
      current: () => pointsRef.current,
      commit,
      loop: loopVias,
      remember: (p, name, label) => namer.remember(p, name, label),
    });
    if (point === null) return;
    setNotice(null);
    const map = mapRef.current;
    map?.flyTo({ center: point, zoom: Math.max(map.getZoom(), 14) });
  };
  const searchBias = (): LonLat | undefined => {
    const centre = mapRef.current?.getCenter();
    if (!centre) return undefined;
    const point: LonLat = [centre.lng, centre.lat];
    return insideCoverage(point) ? point : undefined;
  };

  const removeAt = (index: number) => {
    focusAfterRemove.current = index;
    commit(pointsRef.current.filter((_, i) => i !== index));
  };
  // From the map: the focus stays where it was (on a phone the sheet may be
  // hidden), and the removal is said instead.
  const removeFromMap = useCallback(
    (index: number) => {
      const current = pointsRef.current;
      if (index < 0 || index >= current.length) return;
      const said = removedSaid(index, current.length, loopVias);
      commit(current.filter((_, i) => i !== index));
      announce(said);
    },
    [commit, announce, loopVias],
  );
  // Reverse: in a loop the start stays and the stops go the other way around
  // (OWNER-DECISIONS 374); with a start and one stop that is no change, so a
  // press says why and changes nothing.
  const reverseHint = reverseUnavailableHint(points, loopVias);
  const reverse = () => {
    const current = pointsRef.current;
    const unavailable = reverseUnavailableHint(current, loopVias);
    if (unavailable) {
      announce(unavailable);
      return;
    }
    if (!canReverse(current, loopVias)) return;
    commit(reversedPoints(current, loopVias));
    announce(reversedSaid(loopVias));
  };
  // Best order (OWNER-DECISIONS 449): the stops in the order the router rates best, as
  // one edit Undo takes back. The answer is used only for the ride it was asked about
  // (stopOrder.applyAnswer). What came of it is the Points notice, a status, so it is seen
  // and said once; it is cleared once the points change again.
  const [ordering, setOrdering] = useState(false);
  const orderingRef = useRef(false);
  const orderNoticeFor = useRef<readonly LonLat[] | null>(null);
  // Shown only with two or more stops to order: on a ride of a start, an end and at
  // most one stop it could change nothing, and a standing reason would crowd every
  // short ride's tools (More tips says when it appears).
  // Never on a Mass Ride (OWNER-DECISIONS 449), whose field rides the stops in the order set.
  const orderShown = !isMassRide(preset) && stopsThatMove(points, loopVias) >= 2;
  const reverseButton = useRef<HTMLButtonElement>(null);
  const orderFocused = useRef(false);
  // The button leaves when the stops drop below two (an undo, a removal, the loop): if it
  // had the focus, the focus goes to Reverse beside it rather than to the page's top.
  useLayoutEffect(() => {
    if (orderShown || !orderFocused.current) return;
    orderFocused.current = false;
    if (document.activeElement === null || document.activeElement === document.body) reverseButton.current?.focus();
  }, [orderShown]);
  useEffect(() => {
    if (orderNoticeFor.current !== null && orderNoticeFor.current !== points) {
      orderNoticeFor.current = null;
      setNotice(null);
    }
  }, [points]);
  const orderNotice = (text: string, after: readonly LonLat[]) => {
    // Cleared and set again a moment later, as the location's notice is, so the same
    // answer twice is said twice.
    // The location's timer, shared, so a later notice of either is not overwritten by the other's.
    cancelLocateNotice();
    setNotice(null);
    locateNoticeTimer.current = window.setTimeout(() => {
      if (pointsRef.current !== after) return;
      orderNoticeFor.current = after;
      setNotice(text);
    }, 150);
  };
  const bestOrder = async () => {
    if (orderingRef.current) {
      announce(STILL_FINDING_ORDER_SAID);
      return;
    }
    const current = pointsRef.current;
    const ride = rideRef.current;
    const loop = loopStops(ride.preset, ride.dials.loop);
    if (isMassRide(ride.preset) || stopsThatMove(current, loop) < 2) return;
    orderingRef.current = true;
    setOrdering(true);
    announce(FINDING_ORDER_SAID);
    const result = await requestStopOrder(current, ride.preset, ride.dials);
    orderingRef.current = false;
    setOrdering(false);
    const now = rideRef.current;
    const applied = applyAnswer(
      { points: current, preset: ride.preset, dials: ride.dials, loop },
      { points: pointsRef.current, preset: now.preset, dials: now.dials },
      result,
      namer,
    );
    if (applied.commit) commit(applied.commit);
    orderNotice(applied.say, pointsRef.current);
  };
  const clearAll = () => {
    setConfirmedKm(null);
    setEditPoints(false);
    // Clearing an opened file's plan puts the file away too; undo brings both back.
    const ride = rideRef.current;
    commit([], ride.imported ? { ...ride, imported: null } : undefined);
  };
  // An opened GPX file (GpxPanel): one edit, so one undo takes it back -
  // its points, the ride type it names (through the ride-type choice, which
  // moves the sliders; gpxEdit.ts) and its faint line. It holds at most
  // MAX_POINTS points (gpxPlan.ts); names the file gives its points are kept
  // like a search pick's, and the rest are looked up as any point is.
  const openImported = (plan: ImportedPlan) => {
    setConfirmedKm(null);
    setNotice(null);
    for (const [point, name] of namesToKeep(plan)) namer.remember(point, name);
    commit(plan.points.slice(0, MAX_POINTS), { ...rideAfterImport(plan, rideRef.current), imported: plan });
  };
  const getMap = useCallback(() => mapRef.current, []);
  // A fitting round for an opened track: part of the same edit as the import
  // (the rider did not make it), so it is not an undo step of its own.
  const refineImported = useCallback((next: LonLat[]) => {
    pointsRef.current = next;
    setPoints(next);
  }, []);
  const addAtCentre = () => {
    const map = mapRef.current;
    if (!map) return;
    const { lng, lat } = map.getCenter();
    place([lng, lat]);
  };
  // The keyboard's way to the road panel (OWNER-DECISIONS 441a): the road at the map's center.
  const roadInfoAtCentre = () => {
    const map = mapRef.current;
    if (!map) return;
    const { lng, lat } = map.getCenter();
    setRoadInfo({ point: [lng, lat], origin: "centre" });
  };
  const retry = () =>
    scheduler.current?.request({ points, preset, dials: planDials, confirmLong: sendsConfirmation(points, confirmedKm) });
  // The Adjust panel's sliders and toggles. Turning the loop on or off renames
  // the points (OWNER-DECISIONS 374), which a screen reader would not hear.
  const commitDials = (next: Dials) => {
    const said = loopChangeSaid({ preset, dials }, { preset, dials: next }, points.length);
    if (said) announce(said);
    setDials(next);
  };
  // A new ride type moves the sliders to where it starts them (RideTypePicker)
  // and keeps Make it a loop (rideTypeDialog.choose). Mass Ride has no loop, so
  // into or out of it renames the points; between two others nothing is said.
  const choosePreset = (id: PresetId, next: Dials) => {
    const said = loopChangeSaid({ preset, dials }, { preset: id, dials: next }, points.length);
    if (said) announce(said);
    setPreset(id);
    setDials(next);
  };
  const confirmLong = () => {
    const asked = status.kind === "confirm" && status.error.spanKm !== undefined ? status.error.spanKm : spanKm(points);
    const upTo = confirmedUpTo(Math.max(asked, spanKm(points)));
    setConfirmedKm(upTo);
    // "Not planned", from an earlier Cancel, is no longer true.
    setNotice(null);
    // Sent here as well as by the effect, which does not run again when the
    // confirmed span is unchanged; the debounce folds the two into one.
    scheduler.current?.request({ points, preset, dials: planDials, confirmLong: true });
    // The question goes away; the focus goes to where the answer will be.
    routeHeadingRef.current?.focus();
  };
  const cancelLong = () => {
    setStatus({ kind: "idle" });
    setNotice("Not planned. Move or remove points for a shorter ride; any change asks again.");
    // To the points, which are what the rider changes next.
    pointsHeadingRef.current?.focus();
  };

  // The bottom bar: a sheet opens in the panel body (Legend opens Map layers at its legend), and
  // Back, or Escape, closes it and gives the focus back to the button that opened it.
  // The Plan button: the planner's view, and the focus on its heading (OWNER-DECISIONS 392). The phone
  // header's "Show planner" also shows the planner but leaves the focus on the toggle (cause panelToggle). From a sheet the view changes and focusOnViewChange (cause planButton) does it;
  // already on the planner nothing changes, so the heading is focused and the panel scrolled to the top here.
  const showPlanner = (focusHeading = true) => {
    viewCause.current = focusHeading ? "planButton" : "panelToggle";
    setLegendTarget(false);
    if (viewNow.current === "planner") {
      if (focusHeading) {
        plannerHeadingRef.current?.focus();
        panelBodyRef.current?.scrollTo?.({ top: 0 });
      }
    } else setView("planner");
  };
  const openSheet = (item: BarItem) => {
    if (item.opens === "planner") {
      showPlanner();
      return;
    }
    openedBy.current = item.id;
    viewCause.current = "bar";
    setLegendTarget(item.toLegend === true);
    setView(item.opens);
  };
  const backToPlanner = () => {
    viewCause.current = "back";
    setView("planner");
  };
  // "Copy link": this page with the plan's fragment from encodePlan, which never holds the weight
  // (OWNER-DECISIONS 313). Cleared first and set again a moment later, so a second press is said again.
  const copyLink = async () => {
    const press = ++linkPresses.current;
    setLinkSaid("");
    setLinkSpoken("");
    const note = linkNote;
    const done = await copyText(linkToCopy(window.location, points, preset, dials), navigator.clipboard, selectionCopy);
    window.setTimeout(() => {
      if (press === linkPresses.current) setLinkSaid(linkSaidFor(done));
      if (press === linkPresses.current) setLinkSpoken(linkSpokenFor(done, note));
    }, 150);
  };

  // Start ride (plan Q1, Q3): the first ride asks how to say the cues; later rides start at once. The
  // voice is unlocked inside this press (iOS speaks only after a gesture).
  const beginRide = (prefs: RidePrefs) => {
    if (!shown) return;
    startRideGesture(prefs);
    setRideStart({ route: shown, points: routedPoints, loop: routedLoop, dials: planDials });
    setRideAsk(false);
    setFollow(true);
    setBigText(false);
    setRideView(null);
    setRiding(true);
  };
  const startRide = () => {
    const opener = document.activeElement;
    rideOpener.current = opener instanceof HTMLElement && opener.closest(".start-ride, .description-actions") ? opener : startRideRef.current;
    if (!ridePrefs.chosen) {
      setRideAsk(true);
      return;
    }
    beginRide(ridePrefs);
  };
  const backToRideOpener = () => {
    const opener = rideOpener.current;
    (opener?.isConnected ? opener : startRideRef.current)?.focus();
  };
  const endRide = useCallback(() => {
    setRiding(false);
    setRideStart(null);
    setRideView(null);
    setBigText(false);
    focusStartAfterRide.current = true;
  }, []);
  // After End ride the focus goes back to Start ride, once the planner shows again.
  useEffect(() => {
    if (riding || !focusStartAfterRide.current) return;
    focusStartAfterRide.current = false;
    backToRideOpener();
  }, [riding]);
  // The first ride's question takes the focus to its heading, so its safety note is read before the
  // choices (VoiceOver skips a dialog's description when the focus lands inside it).
  useEffect(() => {
    if (rideAsk) document.getElementById("ride-ask-title")?.focus();
  }, [rideAsk]);
  // Big text hides the map; shown again, it fits its box.
  useEffect(() => {
    if (!bigText) mapRef.current?.resize();
  }, [bigText]);

  // The map frames a route in the part the panel does not cover.
  const framePadding = useCallback((): Frame => {
    const panel = panelRef.current?.getBoundingClientRect();
    if (window.matchMedia(NARROW).matches) {
      // The attribution sits above the sheet on a phone; leave room for it too.
      return { top: 40, left: 30, right: 30, bottom: (panel?.height ?? 0) + 90 };
    }
    return { top: 60, bottom: 60, right: 60, left: (panel?.right ?? 0) + 40 };
  }, []);

  // Copy link keeps full precision; when the rider's location is in the plan it says so, in one line.
  const linkNote = linkLocationNote(points, fromHere);

  const stale = status.kind === "loading" || status.kind === "waiting";
  const shown = status.kind === "error" || status.kind === "confirm" ? null : route;
  // The layer in words: the points along the route shown, in riding order.
  const waterAlong = useMemo(
    () =>
      waterOn && waterData && shown
        ? waterAlongRoute(shown.geometry.coordinates, waterData.filter((p) => waterVisible(p, waterPrefs)))
        : null,
    [waterOn, waterData, waterPrefs, shown],
  );
  // Named in the plan as the list says it, as a place picked from search is.
  const addWaterStop = (item: WaterAlong) => {
    const point: LonLat = [item.point.lon, item.point.lat];
    namer.remember(point, waterTitle(item.point));
    placeSpot("via", point);
  };
  // The line can be dragged when it is the route of the points as they are:
  // not while a new one is being planned, when its legs are the old list's.
  const lineEdit = useMemo<LineEdit | null>(() => {
    const routeShown = shown !== null;
    const vertexCount = shown?.geometry.coordinates.length ?? 0;
    if (!shown || !canDragLine({ routeShown, stale, routedIsCurrent: routedPoints === points, vertexCount })) return null;
    const path = shown.geometry.coordinates;
    // A loop's legs close on the start (OWNER-DECISIONS 374), so the API's
    // leg ends fit them.
    const legs = legPoints(routedPoints, loopVias);
    return { path, ends: legEnds(path, legs, shown.leg_ends), points: routedPoints, legPoints: legs };
  }, [shown, stale, routedPoints, points, loopVias]);
  // On a phone the sheet is half the screen; a route that is showing (a
  // shared link, usually), a question or an error comes first in it, before
  // the ride types (sheet.ts).
  const order = sheetOrder(narrow, status.kind, shown !== null);
  const routeFirst = order[0] === "route";

  // Reordering the sheet moves sections in the DOM, and a focused element
  // that moves loses the focus; put it back where it was. When the route
  // comes first, the sheet shows it from the top: the stats, not whatever
  // the sheet was scrolled to for the question or error before it.
  const focusBeforeRender = useRef<Element | null>(null);
  focusBeforeRender.current = document.activeElement;
  // What scrolls is .panel-scroll, or on a short or zoomed screen the whole panel (styles.css).
  const scrollPanelToTop = () => {
    panelBodyRef.current?.scrollTo({ top: 0 });
    panelRef.current?.scrollTo?.({ top: 0 });
  };
  useLayoutEffect(() => {
    const before = focusBeforeRender.current;
    if (
      before instanceof HTMLElement &&
      before !== document.body &&
      before.isConnected &&
      document.activeElement !== before
    ) {
      before.focus({ preventScroll: true });
    }
    if (routeFirst) scrollPanelToTop();
  }, [routeFirst]);

  // Each new question or error is shown from the top of the sheet, where the
  // Route section now is: a sheet left scrolled down to the ride types would
  // open with the reason it opened out of sight.
  const attention = opensSheet(status.kind) ? status : null;
  useLayoutEffect(() => {
    if (attention && routeFirst) scrollPanelToTop();
  }, [attention]);

  const announcement =
    status.kind === "loading"
      ? `Planning a ${presetLabel(preset)} route…`
      : status.kind === "waiting"
        ? `The planner is busy; trying again in ${formatSeconds(status.seconds)}.`
        : status.kind === "ok" && route
          ? announceRoute(route, routedPoints, announceHow(answer, choice, chosen))
          : "";
  // The route's sentence once it has stood a moment (lib/settle.ts): routes
  // that replace each other quickly are said once, the last. "Planning..." is
  // shown but not said, so a release is one announcement, not two.
  const routeSaid = useSettled(status.kind === "ok" ? announcement : "", ANNOUNCE_SETTLE_MS);
  // A plan still going after a few seconds is said once, so a screen-reader rider
  // can tell a slow plan (a calm route at the top of the slider takes up to half a
  // minute) from a dead one (the a11y review's SF1).
  const slow = useLongerThan(status.kind === "loading", STILL_PLANNING_AFTER_MS);

  const presetsSection = <RideTypePicker key="presets" preset={preset} dials={dials} onChoose={choosePreset} />;
  // A route is on screen: the points are compact unless the rider is editing them.
  const routeShownForPoints = shown !== null;
  const compactPoints = routeShownForPoints && points.length >= 2 && !editPoints;
  // A route arriving while the focus is in the search or the point tools hides
  // them: the focus goes to "Edit points" rather than dropping to the page (lib/sidebar.ts
  // rescueCompactFocus; the review's B1). After the sheet-order effect above, which may put the
  // focus back on the element it had.
  useLayoutEffect(() => {
    rescueCompactFocus({
      wasCompact: wasCompact.current,
      compact: compactPoints,
      before: focusBeforeRender.current,
      hidden: [pointsSearchRef.current, pointsEditRef.current],
      editPoints: editPointsRef.current,
    });
    wasCompact.current = compactPoints;
  }, [compactPoints]);
  const federalPlanner = federalShown(preset, true) && (
    // Mass Ride's points on federal land, in words, in the planner as well as the Map layers
    // sheet: the text the map's permit shading stands for (the correctness review's S3).
    <FederalPointsList
      found={federalData ? federalPoints(points, federalData) : null}
      count={points.length}
      nameOf={(index) => pointName(index, points.length) /* Mass Ride: no loop */}
      headingId="federal-points-planner-heading"
    />
  );
  const loop = loopView(preset, dials.loop, points);
  const loopHintId = useId();
  const pointsSection = (
    <section key="points" aria-labelledby="points-heading">
      <h2 id="points-heading" ref={pointsHeadingRef} tabIndex={-1}>
        Points
      </h2>
      {PLANNER_EXTRAS.zoomNotice && <PlannerZoomNotice zoom={zoom} shown={stressVisible && stress === "available"} />}
      {PLANNER_EXTRAS.highContrastShortcut && (
        <HighContrastShortcut on={accessibilityOn()} paletteFromAddress={paletteSetByAddress()} onChange={(on) => setAccessibility(on)} />
      )}
      {/* The controls stay in the page while the points are compact (hidden), so the search keeps its state. */}
      <div id="points-search" ref={pointsSearchRef} className="points-controls" hidden={compactPoints}>
        <PlaceSearch
          pointCount={points.length}
          loop={loopVias}
          full={points.length >= MAX_POINTS}
          gate={geoGate}
          bias={searchBias}
          onPick={pickPlace}
          locate={{
            support: locateReady,
            busy: locating,
            note: hereInPlan && here ? approximateHint(here.accuracyM) : "",
            onLocate: (choice) => void useMyLocation(choice),
          }}
        />
      </div>
      {/* Make it a loop (OWNER-DECISIONS 388, 389): by the search, not behind the Ride line's Edit; there
          with no point placed too, and not on Mass Ride. Outside the hidden parts, so it stays when the points compact. */}
      {loop && (
        <div className="dial loop-toggle">
          <label className="toggle">
            {/* aria-disabled, not disabled, when the ride is a loop already: it stays in the Tab order
                with its reason as its description (the a11y review's N6), and a press changes nothing. */}
            <input
              type="checkbox"
              checked={loop.checked}
              aria-disabled={loop.implied || undefined}
              aria-describedby={loopHintId}
              onChange={(event) => {
                if (loop.implied) return;
                commitDials(withLoop(dials, event.target.checked));
              }}
            />
            {loop.label}
          </label>
          <p className="hint" id={loopHintId}>
            {loop.hint}
          </p>
        </div>
      )}
      {points.length === 0 ? (
        <p className="hint">{searchLede(loopVias, accessMode)}</p>
      ) : (
        <PointsList
          rows={pointRows(points, namer, loopVias)}
          onRemove={removeAt}
          removeRef={(index, button) => {
            removeRefs.current[index] = button;
          }}
        />
      )}
      {points.length === 1 && <p className="hint">{loneStartHint(preset, loopVias, accessMode)}</p>}
      {routeShownForPoints && points.length >= 2 && (
        <button
          type="button"
          ref={editPointsRef}
          className="secondary edit-points"
          aria-expanded={!compactPoints}
          aria-controls="points-search points-edit"
          onClick={() => setEditPoints((on) => !on)}
        >
          {compactPoints ? "Edit points" : "Done editing points"}
        </button>
      )}
      {/* Mass Ride planning covers DC only for now (OWNER-DECISIONS 418), in words beside the gray map. */}
      {isMassRide(preset) && <p className="hint mass-dc-only">{MASS_DC_ONLY}</p>}
      {federalPlanner}
      <NearestFinder
        from={nearestFrom}
        fromOptions={nearestFromOptions}
        onFrom={setNearestFrom}
        onFind={(kind) => void findNearest(kind)}
        busy={nearestBusy}
        status={nearestStatus}
        list={nearestList}
        canAddStop={points.length >= 2}
        onRide={rideToNearest}
        onAddStop={addNearestStop}
      />
      <div id="points-edit" ref={pointsEditRef} hidden={compactPoints}>
      {/* The two map-center actions (add a point, the road panel) are in Map tools, by the map's
          zoom buttons (OWNER-DECISIONS 450; MapTools.tsx). */}
      {/* The compact row: Reverse, Best order, Undo, Redo and Clear. */}
      <div className="actions point-tools">
        {/* aria-disabled, not disabled, in a loop of a start and one stop: it stays in
            the Tab order with its reason as its description, as the loop toggle does
            (DialsPanel), and a press says the reason. */}
        <button
          type="button"
          ref={reverseButton}
          onClick={reverse}
          disabled={points.length < 2}
          aria-disabled={reverseHint ? true : undefined}
          aria-describedby={reverseHint ? "reverse-hint" : undefined}
        >
          Reverse
        </button>
        {/* Best order (OWNER-DECISIONS 449), with two or more stops to order; aria-disabled
            while the order is found (the focus stays on it, a press says it is still working),
            with the same label, so the row does not reflow under a finger. */}
        {orderShown && (
          <button
            type="button"
            onClick={() => void bestOrder()}
            onFocus={() => (orderFocused.current = true)}
            onBlur={(event) => {
              // Only a move to another element clears the mark: a blur from the button's own removal
              // has none, so the effect above moves the focus (and only if it is on nothing).
              if (event.relatedTarget) orderFocused.current = false;
            }}
            aria-disabled={ordering ? true : undefined}
          >
            {BEST_ORDER_LABEL}
          </button>
        )}
        {!narrow && (
          <button type="button" onClick={undo} disabled={!can.undo} aria-keyshortcuts="Control+Z Meta+Z">
            Undo
          </button>
        )}
        {!narrow && can.redo && (
          <button type="button" onClick={redo} aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y">
            Redo
          </button>
        )}
        <button type="button" onClick={clearAll} disabled={points.length === 0}>
          Clear
        </button>
      </div>
      {reverseHint && <p className="hint" id="reverse-hint">{reverseHint}</p>}
      {/* The how-to, collapsed (the mockup's "More tips"). */}
      <MoreTips>
        {/* The start-up how-to before any point; with points, how to change them (the correctness review's N5). */}
        {points.length > 0 ? <p className="hint">{editingTips(accessMode)}</p> : <p className="hint">{emptyPlanHint(preset, loopVias, accessMode)}</p>}
        {coverageShown && <p className="hint">Gray areas are outside what RouteMaker covers.</p>}
        <p className="hint">{infoHelp(accessMode)}</p>
        <p className="hint">{ACCESS_HELP}</p>
        <button type="button" className="link access-toggle" aria-pressed={accessMode} onClick={() => toggleAccessMode(false)}>
          {ACCESS_LABEL}
        </button>
      </MoreTips>
      </div>
      {/* Always rendered, empty when there is no notice: a live region that is created already holding
          its text is often not spoken (VoiceOver with Safari, NVDA with Firefox). */}
      <p className={notice ? "notice" : "notice notice-empty"} role="status">
        {notice ?? ""}
      </p>
    </section>
  );
  const routeSection = (
    <section key="route" aria-labelledby="route-heading" aria-busy={stale}>
      <h2 id="route-heading" ref={routeHeadingRef} tabIndex={-1}>
        Route
      </h2>
      {status.kind === "loading" && <p className="loading">{announcement}</p>}
      {status.kind === "loading" && <progress className="planning" aria-label="Planning the route" />}
      {/* What the route's live region says (routeStatus, outside the panel), shown here; a screen
          reader hears it there, so it is not read twice. */}
      <div className="status-shown" aria-hidden="true">
        {status.kind === "loading" && slow && <p className="loading">{stillPlanningSaid(preset, dials)}</p>}
        {status.kind === "waiting" && <p className="loading">{announcement}</p>}
      </div>
      {/* Read where it stands, not spoken: it never changes while shown (recheck N-new-2). */}
      {status.kind === "idle" && points.length < 2 && <p className="hint">No route yet.</p>}
      {status.kind === "confirm" && (
        <div
          className="confirm"
          role="alertdialog"
          aria-labelledby="confirm-title"
          aria-describedby="confirm-text"
          onKeyDown={(event) => {
            if (isCancelKey(event.key)) {
              event.preventDefault();
              cancelLong();
            }
          }}
        >
          <p id="confirm-title">
            <strong>{status.error.title}</strong>
          </p>
          <p id="confirm-text">{status.error.message} Plan it?</p>
          <div className="actions">
            <button type="button" ref={planButtonRef} onClick={confirmLong}>
              Plan it
            </button>
            <button type="button" className="secondary" onClick={cancelLong}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {status.kind === "error" && (
        <div ref={errorRef} tabIndex={-1} className={`error error-${status.error.kind}`} role="alert">
          <p>
            <strong>{status.error.title}.</strong> {status.error.message}
          </p>
          {["router-down", "timed-out", "server", "network", "rate-limited"].includes(status.error.kind) && (
            <button type="button" onClick={retry}>
              Try again
            </button>
          )}
        </div>
      )}
      {shown && (
        <RouteSummary
          route={shown}
          points={routedPoints}
          narrow={narrow}
          onSelectJunction={(index) => setJunctionFocus((f) => ({ index, nonce: (f?.nonce ?? 0) + 1 }))}
          onScrub={setScrubPoint}
          picker={
            candidateRows(answer) === null ? null : (
              <CandidatePicker answer={answer} choice={choice} onChoose={choose} />
            )
          }
          pickerCount={candidateRows(answer)?.length ?? 0}
          ride={{ onStart: startRide, startRef: startRideRef }}
        />
      )}
      {shown && waterOn && waterStatus === "ready" && (
        <WaterAlongList items={waterAlong} onAddStop={addWaterStop} headingId="water-along-planner-heading" level="h3" />
      )}
      {shown && rideAsk && (
        <div className="ride-ask" role="dialog" aria-labelledby="ride-ask-title" aria-describedby="ride-ask-safety"
          onKeyDown={(event) => {
            if (isCancelKey(event.key)) {
              event.preventDefault();
              setRideAsk(false);
              backToRideOpener();
            }
          }}
        >
          <h3 id="ride-ask-title" tabIndex={-1}>
            Start ride
          </h3>
          <p id="ride-ask-safety" className="hint">
            {RIDE_SAFETY}
          </p>
          <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="ride-ask" />
          <div className="actions">
            <button
              type="button"
              ref={rideStartFirstRef}
              onClick={() => {
                const prefs = { ...ridePrefs, chosen: true };
                changeRidePrefs(prefs);
                beginRide(prefs);
              }}
            >
              Start
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setRideAsk(false);
                backToRideOpener();
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );

  const sections: Record<SheetSection, ReactElement> = {
    presets: (
      <RideSettings key="presets" summary={rideSummary(preset, dials)} spoken={rideSummarySpoken(preset, dials)}>
        {presetsSection}
        <DialsPanel
          preset={preset}
          dials={dials}
          onCommit={commitDials}
          weight={{
            saved: weight,
            remembered: weightRemembered,
            onSave: (next, remember) => {
              weightStore.current?.save(next, remember);
              setWeightRemembered(remember && (weightStore.current?.remembered() ?? false));
              setWeight(next);
            },
            onClear: () => {
              weightStore.current?.clear();
              setWeightRemembered(false);
              setWeight(null);
            },
          }}
          resolvedWhen={route?.dials?.when ?? null}
        />
      </RideSettings>
    ),
    points: pointsSection,
    route: routeSection,
  };

  return (
    <div className={`app${riding ? " riding" : ""}${riding && bigText ? " riding-big" : ""}`}>
      {/* Past the map, its markers and its controls (up to 150 junction
          markers come before the planner), to the planner (lib/skipLink.ts). */}
      {/* The page's first stop and first in a screen reader's order, hidden until focused: accessibility mode's
          switch (OWNER-DECISIONS 455, 455a): a button with aria-pressed and a constant name. */}
      <button type="button" className="access-link" aria-pressed={accessMode} onClick={() => toggleAccessMode(true)}>
        {ACCESS_LABEL}
      </button>
      {riding ? (
        // During a ride the planner is hidden: the link goes to Ride mode instead.
        <a className="skip-link" href="#ride-heading" onClick={(event) => skipToPlanner(event, document.getElementById("ride-heading"))}>
          {SKIP_TO_RIDE_TEXT}
        </a>
      ) : (
        <a className="skip-link" href="#route-planner" onClick={(event) => skipToPlanner(event, panelRef.current)}>
          {SKIP_LINK_TEXT}
        </a>
      )}
      <MapView
        points={riding ? NO_POINTS : points}
        loopVias={loopVias}
        route={riding && rideView ? rideView.route : shown}
        stale={riding ? false : stale}
        stressVisible={stressVisible && stress === "available"}
        when={mapWhen(dials.when ?? null)}
        framePadding={framePadding}
        onStressAvailability={setStress}
        onMapClick={riding ? ignore : place}
        onMovePoint={riding ? ignore : move}
        lineEdit={riding ? null : lineEdit}
        onLineDrop={riding ? ignore : insertOnLine}
        onRemovePoint={riding ? ignore : removeFromMap}
        markerReset={markerReset}
        accuracy={riding ? rideCircle : hereCircle}
        rider={riding && rideView?.rider ? rideView.rider : null}
        follow={riding && follow && !bigText /* Big text hides the map: no camera work for it */}
        headingUp={headingUp}
        onFollowBroken={() => setFollow(false)}
        junctionFocus={junctionFocus}
        scrubPoint={scrubPoint}
        onReady={(map) => {
          mapRef.current = map;
          void fetchCoverage(window.location.origin).then((coverage) => {
            if (coverage && mapRef.current === map && addCoverageMask(map, coverage)) setCoverageShown(true);
          });
          watchForFacilities(map, setFacilitiesShown);
          watchForCapacity(map, () => setCapacityTiles(true));
          watchZoom(map, (z, byRider) => {
            zoomByRider.current = byRider;
            setZoom(z);
          });
        }}
        onCanvasFocus={(focused) => setCrosshair((c) => ({ ...c, canvas: focused }))}
        rail={rail}
        massCapacity={massMap}
        massArea={isMassRide(preset)}
        water={waterData}
        waterPrefs={waterPrefs}
        federalVisible={federalShown(preset, federalOn)}
        federalWanted={federalShown(preset, true) /* Mass Ride: the planner's points list needs the data whatever the switch says */}
        onFederalStatus={setFederalStatus}
        onFederalData={setFederalData}
        onStationPoint={riding ? ignore : placeStation}
        onRoadInfo={riding ? ignore : setRoadInfo /* no road panel (and its Add a stop) during a ride */}
        tools={
          accessMode && !riding ? (
          <MapTools
            toggleRef={toolsToggleRef}
            onAddPoint={addAtCentre}
            addDisabled={points.length >= MAX_POINTS}
            onRoadInfo={roadInfoAtCentre}
            onCrosshair={toolsCrosshair}
            onShown={toolsShown}
          />
          ) : null
        }
      />
      <RoadInfoDialog
        request={roadInfo}
        massRide={massMap}
        station={roadInfo ? stationNearSpot(RAIL_STATIONS, rail, roadInfo.point, WMATA_SLUGS)?.station ?? null : null}
        onClose={closeRoadInfo}
        fallbackFocus={mapFocus}
        onStressChanged={(generation) => {
          // An instance admin changed a road (OWNER-DECISIONS 441h): the map asks for its tiles again.
          const map = mapRef.current;
          if (map) refreshStressTiles(map, window.location.origin, generation);
        }}
        plan={{ count: points.length, loop: loopVias }}
        onPlace={placeSpot}
      />
      {(crosshair.button || crosshair.canvas) && <div className="crosshair" aria-hidden="true" />}
      {!riding && narrow && (can.undo || can.redo) && (
        // On a phone the sheet may be hidden while the rider edits the map,
        // so Undo and Redo sit on the map there (and only there: one of each
        // per layout), each shown while it has something to give back.
        <div className="map-history">
          {can.undo && (
            <button type="button" onClick={undo}>
              Undo
            </button>
          )}
          {can.redo && (
            <button type="button" onClick={redo}>
              Redo
            </button>
          )}
        </div>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {said.text}
        {said.count % 2 === 1 ? " " : ""}
      </p>
      {/* The route's live region: outside the panel, so it is heard while a bar sheet is open or the
          phone's sheet is hidden (a region in a hidden part of the page says nothing; the reviews' S1, S2). */}
      <div role="status" aria-live="polite" className="status-line visually-hidden">
        {status.kind === "loading" && slow && <p>{stillPlanningSaid(preset, dials)}</p>}
        {status.kind === "waiting" && <p>{announcement}</p>}
        {status.kind === "ok" && routeSaid && <p>{routeSaid}</p>}
      </div>
      {riding && rideStart && (
        <RideMode
          route={rideStart.route}
          points={rideStart.points}
          loop={rideStart.loop}
          preset={rideStart.route.preset}
          dials={rideStart.dials}
          prefs={ridePrefs}
          onPrefs={changeRidePrefs}
          follow={follow}
          onFollow={setFollow}
          headingUp={headingUp}
          onHeadingUp={setHeadingUp}
          big={bigText}
          onBig={setBigText}
          onView={setRideView}
          onEnd={endRide}
          water={ensureWater}
        />
      )}
      {/* Hidden, not removed, during a ride: the planner keeps its state, and Sign in is out of reach (plan section 7). */}
      <aside
        ref={panelRef}
        id="route-planner"
        tabIndex={-1}
        className={`panel ${panelOpen ? "open" : "closed"}`}
        aria-label="Route planner"
        hidden={riding}
      >
        <header className="panel-header">
          <div>
            <h1 ref={plannerHeadingRef} tabIndex={-1}>
              {PLANNER_TITLE}
            </h1>
            <p className="tagline">Bike routes for the DC region and Baltimore. No sign-in needed.</p>
          </div>
          <button
            type="button"
            className="panel-toggle"
            aria-expanded={panelOpen}
            aria-controls="panel-body"
            onClick={() => {
              // Hiding the panel only hides it; showing it always shows the planner, even if a sheet was
              // open when it was hidden (OWNER-DECISIONS 392).
              if (panelOpen) setPanelOpen(false);
              else {
                setPanelOpen(true);
                // The focus stays on this toggle; the heading focus is the Plan button's.
                showPlanner(false);
              }
            }}
          >
            {panelOpen ? "Hide planner" : "Show planner"}
          </button>
        </header>
        <div id="panel-body" className="panel-body" hidden={!panelOpen}>
          <BetaBanner
            enabled={isBetaBuild(import.meta.env.VITE_BETA)}
            reportUrl={betaReportUrl(import.meta.env.VITE_BETA_REPORT_URL)}
          />
          <div ref={panelBodyRef} className="panel-scroll">
            <div className="planner-view" hidden={view !== "planner"}>
              {order.map((id) => sections[id])}
            </div>

            {/* The bottom bar's sheets stay in the page while hidden, so the opened GPX file
                and the switches keep their state. */}
            <SheetFrame
              id="sheet-layers"
              title={SHEET_TITLES.layers}
              open={view === "layers"}
              onBack={backToPlanner}
              headingRef={layersHeadingRef}
            >
              {/* In 312's order: traffic stress, high-stress lanes, high contrast, federal land
                  (Mass Ride's alone), water and restrooms, rail stations; trails and terrain (454); then the full legend. */}
              <section aria-labelledby="layers-heading">
                <h3 id="layers-heading">{massMap ? CAPACITY_LEGEND_TITLE : "Traffic stress"}</h3>
                {stress === "available" && (
                  <label className="toggle">
                    <input
                      id="show-stress"
                      type="checkbox"
                      checked={stressVisible}
                      onChange={(event) => setStressVisible(event.target.checked)}
                    />
                    {massMap ? "Show riders per minute on the map" : "Show traffic stress on the map"}
                  </label>
                )}
                {stress === "checking" && <p className="hint">Checking the stress map…</p>}
                {stress === "unavailable" && (
                  <p className="hint">
                    Stress map unavailable for now. Routes still show how much of each ride is on each stress level.
                  </p>
                )}
                {/* Shown with or without the stress map: it also changes the route's facility totals
                    and description (the a11y review's SF4). */}
                <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} massMap={massMap} />
                <AccessibilitySwitch
                  on={accessibilityOn()}
                  source={accessibilitySource()}
                  paletteFromAddress={paletteSetByAddress()}
                  onChange={(on) => setAccessibility(on)}
                />
              </section>

              {/* Mass Ride's alone (OWNER-DECISIONS 324): null for every other ride type. */}
              <FederalLandFor
                preset={preset}
                on={federalOn}
                onChange={setFederalOn}
                status={federalStatus}
                points={federalData ? federalPoints(points, federalData) : null}
                pointCount={points.length}
                nameOf={(index) => pointName(index, points.length) /* Mass Ride: no loop */}
              />

              <WaterSection
                prefs={waterPrefs}
                onChange={changeWaterPrefs}
                status={waterStatus}
                items={waterAlong}
                onAddStop={addWaterStop}
              />

              {RAIL_STATIONS.length > 0 && <RailStationsSection visibility={rail} onChange={setRail} />}

              {/* OWNER-DECISIONS 454's optional layers, off until turned on, in every ride type. Topo lines
                  and climbs join the mountain-bike trails here once the tiles carry them (docs/MTB-TOPO-PLAN.md). */}
              <section aria-labelledby="terrain-heading">
                <h3 id="terrain-heading">Trails and terrain</h3>
                <MtbTrailsSwitch on={showMtbTrails} onChange={(on) => setMtbTrails(on)} overlay={stress === "available"} />
              </section>

              {/* Mockup v3's line; the Mass Ride layers sheet itself waits on FOLLOWUP-MASSRIDE-MAP (324-334). */}
              {!federalShown(preset, true) && <p className="hint mass-ride-layers">{MASS_RIDE_LAYERS_NOTE}</p>}

              <section aria-labelledby="legend-heading">
                <h3 id="legend-heading" ref={legendHeadingRef} tabIndex={-1}>
                  Legend
                </h3>
                {stress === "available" ? (
                  massMap ? (
                    <>
                      <MassLegend />
                      <MassZoomNotes zoom={zoom} shown={stressVisible} />
                      {/* 454: the mountain-bike trails' layer shows in Mass Ride too, so its row does. */}
                      <MtbTrailLegend />
                    </>
                  ) : (
                    <>
                      <StressLegend facilities={facilitiesShown} zoom={zoom} shown={stressVisible} foldedZoom />
                      {/* A Mass Ride before the tiles carry a capacity: the stress map stays, and the grey
                          outside DC still shows, so its words and its credit do too (accessibility review S2). */}
                      {isMassRide(preset) && (
                        <>
                          <p className="hint mass-dc-only">{MASS_DC_ONLY}</p>
                          <p className="hint dc-boundary-source">{DC_BOUNDARY_CREDIT}</p>
                        </>
                      )}
                    </>
                  )
                ) : (
                  <p className="hint">The traffic stress legend shows here when the stress map is available.</p>
                )}
                {/* The junction markers are drawn with or without the stress map (spec review SF1). */}
                <JunctionLegend />
              </section>
            </SheetFrame>

            <SheetFrame
              id="sheet-gpx"
              title={SHEET_TITLES.gpx}
              open={view === "gpx"}
              onBack={backToPlanner}
              headingRef={gpxHeadingRef}
            >
              <GpxPanel
                route={shown}
                routedPoints={routedPoints}
                loop={routedLoop}
                points={points}
                planStatus={status.kind}
                imported={imported}
                onImport={openImported}
                onRefine={refineImported}
                getMap={getMap}
              />
            </SheetFrame>

            <SheetFrame
              id="sheet-settings"
              title={SHEET_TITLES.settings}
              open={view === "settings"}
              onBack={backToPlanner}
              headingRef={settingsHeadingRef}
            >
              {/* The same switch and the same state as in Map layers (one module state, so a flip in
                  either shows in both), with ids of its own: both sheets are in the page at once. */}
              <section aria-labelledby="settings-display-heading">
                <h3 id="settings-display-heading">Display</h3>
                <AccessibilitySwitch
                  idBase="settings-contrast"
                  on={accessibilityOn()}
                  source={accessibilitySource()}
                  paletteFromAddress={paletteSetByAddress()}
                  onChange={(on) => setAccessibility(on)}
                />
              </section>
              {/* Ride mode's choices (WEB-NAV-plan.md section 3): the same ones the first Start ride asks, kept on this device. */}
              <section aria-labelledby="settings-ride-heading">
                <h3 id="settings-ride-heading">Ride mode</h3>
                <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="settings-ride" />
              </section>
              <section aria-labelledby="settings-signin-heading">
                <h3 id="settings-signin-heading">Signing in</h3>
                <p className="hint">
                  Planning works without signing in, and a plan made signed out is not saved; the link in the address bar
                  reopens it. Saving routes and peer review are coming for riders who{" "}
                  <a href="/auth/login" onClick={(e) => isPlainClick(e) && rememberPlanForSignIn(tabSession(), window.location.hash, linkNote !== "")}>
                    sign in with Discord
                  </a>
                  ; your current plan is kept across the sign-in.
                </p>
              </section>
            </SheetFrame>
          </div>

          {/* Pinned under the scrolling part while a route is shown: its file and its link. */}
          {view === "planner" && shown && (
            <div className="route-actions">
              <button type="button" onClick={() => downloadGpx(shown, routedPoints, routedLoop)}>
                Download GPX
              </button>
              <button type="button" className="secondary" onClick={copyLink} aria-describedby={linkNote ? "link-note" : undefined}>
                {COPY_LINK}
              </button>
              <span role="status" className="visually-hidden">
                {linkSpoken}
              </span>
              {linkSaid && (
                <span className="hint link-said" aria-hidden="true">
                  {linkSaid}
                </span>
              )}
              {linkNote && (
                <p id="link-note" className="hint link-note">
                  {linkNote}
                </p>
              )}
            </div>
          )}

          <BottomBar view={view} legend={legendTarget} onOpen={openSheet} buttonRef={(id, button) => (barButtons.current[id] = button)} />
        </div>
      </aside>
    </div>
  );
}

/** Whether `on` has been true for `afterMs` without a break: false again at once when it goes false. */
function useLongerThan(on: boolean, afterMs: number): boolean {
  const [long, setLong] = useState(false);
  useEffect(() => {
    if (!on) {
      setLong(false);
      return;
    }
    const timer = window.setTimeout(() => setLong(true), afterMs);
    return () => window.clearTimeout(timer);
  }, [on, afterMs]);
  return on && long;
}

/** `text` once it has stood for `waitMs`; "" at once (lib/settle.ts SettledText). */
function useSettled(text: string, waitMs: number): string {
  const [shown, setShown] = useState("");
  const settled = useRef<SettledText | null>(null);
  if (settled.current === null) settled.current = new SettledText(waitMs, setShown);
  useEffect(() => settled.current?.offer(text), [text]);
  useEffect(() => () => settled.current?.cancel(), []);
  return shown;
}

function RouteSummary({
  route,
  points,
  narrow,
  onSelectJunction,
  onScrub,
  picker,
  pickerCount,
  ride,
}: {
  route: RouteResponse;
  points: LonLat[];
  narrow: boolean;
  /** Ride mode's Start ride (WEB-NAV-plan.md Q1): offered under the figures and with the directions. */
  ride: { onStart: () => void; startRef: RefObject<HTMLButtonElement | null> };
  onSelectJunction: (index: number) => void;
  /** The chart's scrub: the map point it reads, or null. */
  onScrub: (point: LonLat | null) => void;
  /** The routes to choose from (CandidatePicker), or null with one route. */
  picker: ReactNode;
  pickerCount: number;
}) {
  useStressStyle();
  // A Mass Ride's panel is about riders per minute, in place of the LTS breakdown (OWNER-DECISIONS 325).
  const capacity = capacitySummary(route.stress_spans);
  const segments = capacity ? [] : stressSegments(route.stress_m);
  const detour = detourView(route, points);
  const calmNote = calmSearchNote(route);
  const loopSaid = loopNote(route);
  // A Mass Ride that leaves the District (OWNER-DECISIONS 418a): shown here, and said in the route's
  // live region with the rest of the route's sentence (lib/summary.ts announceRoute).
  const outsideDc = outsideDcNote(route);
  // A point inside the National Zoo was moved to its bike racks (291(4)): shown here, and said with the route.
  const moved = movedPointsNote(route, points.length);
  const pace = paceText(route);
  // The sidebar's route view (OWNER-DECISIONS 312): the totals, the stress bar and four quick
  // figures in view; Elevation and stress (322; Riders per minute, corker load and elevation on a Mass Ride),
  // Stress and facilities, Directions, Junctions to watch and Routes to choose from as folds.
  const profile = usableProfile(route);
  const junctions = route.intersections == null ? null : junctionItems(route).length;
  // Start ride is offered with the directions too (plan Q1).
  const rideable = route.distance_m <= RIDE_MAX_M;
  const rideAction = rideable ? (
    <button type="button" className="secondary" onClick={ride.onStart}>
      Start ride
    </button>
  ) : null;
  return (
    <div className="summary">
      {moved && (
        <p className="notice moved-points" role="note">
          {moved}
        </p>
      )}
      {outsideDc && (
        <p className="notice mass-outside-dc" role="note">
          {outsideDc}
        </p>
      )}
      {detour && (
        <p className={`notice detour detour-${detour.level}`} role="note">
          {detour.text}
        </p>
      )}
      {calmNote && (
        <p className="hint calm-search" role="note">
          {calmNote}
        </p>
      )}
      {loopSaid && (
        <p className="hint loop-note" role="note">
          {loopSaid}
        </p>
      )}
      {/* Headings for a screen reader's list, out of sight: the route's figures, then each fold (the a11y review's S5). */}
      <h3 className="visually-hidden">Totals</h3>
      <dl className="stats totals">
        <div className="stat-distance">
          <dt>Distance</dt>
          <dd>{formatDistance(route.distance_m)}</dd>
        </div>
        <div>
          <dt>Moving time</dt>
          <dd>{formatDuration(route.duration_s)}</dd>
        </div>
        <div>
          <dt>Climb</dt>
          <dd>{formatClimb(route.climb_m)}</dd>
        </div>
        <div>
          <dt>Descent</dt>
          <dd>{formatClimb(route.descent_m)}</dd>
        </div>
      </dl>
      {pace && <p className="hint pace">Moving time at {pace}, without stops.</p>}
      <CapacityStats route={route} />
      {segments.length > 0 && (
        <figure className="stress stress-main" aria-labelledby="stress-figure-caption">
          <figcaption id="stress-figure-caption">Traffic stress along the route</figcaption>
          {/* One image to a screen reader, named with each share; the line under it says the same in text. */}
          <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
            {segments
              .filter((s) => s.fraction > 0)
              .map((s) => (
                <span
                  key={s.key}
                  className={`stress-seg stress-seg-${s.key}`}
                  style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color, ["--seg-accent" as string]: s.casing }}
                  title={`${s.short}: ${s.percent}%`}
                />
              ))}
          </div>
          <p className="stress-key" aria-hidden="true">
            {stressBarKey(segments)}
          </p>
        </figure>
      )}
      <QuickFigures figures={quickFigures(route)} />
      {/* Start ride (WEB-NAV-plan.md Q1): short rides only; a longer one goes to a bike computer (OD 255). */}
      {rideable ? (
        <div className="actions start-ride">
          <button type="button" ref={ride.startRef} onClick={ride.onStart}>
            Start ride
          </button>
          <p className="hint">Turn-by-turn directions on this phone, said as you chose. Keep the screen on and this page in front.</p>
        </div>
      ) : (
        <p className="hint start-ride-long">{RIDE_TOO_LONG}</p>
      )}
      <FacilityBreakdown route={route} part="notices" />
      {profile && (
        <Fold
          title={foldName(chartKind(route))}
          heading={foldName(chartKind(route))}
          // Offered collapsed on a small screen (OWNER-DECISIONS 322); open beside the map.
          open={chartFoldOpen(narrow)}
        >
          <ElevationChart route={route} profile={profile} onScrub={onScrub} />
        </Fold>
      )}
      {capacity && (
        // A Mass Ride's fold is about riders per minute, in place of the stress and facility figures (OWNER-DECISIONS 325).
        <Fold title={CAPACITY_FOLD_TITLE} heading={CAPACITY_FOLD_TITLE} open={ROUTE_FOLDS.facilities.open}>
          <CapacityFigures route={route} />
        </Fold>
      )}
      {!capacity && (
      <Fold title={ROUTE_FOLDS.facilities.title} heading={ROUTE_FOLDS.facilities.title} open={ROUTE_FOLDS.facilities.open}>
        {segments.length > 0 && (
          <figure className="stress" aria-labelledby="stress-detail-caption">
            <figcaption id="stress-detail-caption">Traffic stress, stretch by stretch</figcaption>
            <ul className="stress-list">
              {segments.map((s) => (
                <li key={s.key}>
                  <span className={`swatch stress-seg-${s.key}`} style={{ backgroundColor: s.color, ["--seg-accent" as string]: s.casing }} aria-hidden="true" />
                  <span className="stress-name">{s.short}</span>
                  <span className="visually-hidden">, </span>
                  <span className="stress-pct">{s.percent}%</span>
                  <span className="visually-hidden">, </span>
                  <span className="stress-label">{s.label}</span>
                </li>
              ))}
            </ul>
          </figure>
        )}
        <FacilityBreakdown route={route} part="figures" />
      </Fold>
      )}
      <RouteDescription route={route} fold rideAction={rideAction} />
      {junctions !== null && (
        <Fold title={foldTitle(ROUTE_FOLDS.junctions.title, junctions)} heading={ROUTE_FOLDS.junctions.title} open={ROUTE_FOLDS.junctions.open}>
          <IntersectionList route={route} onSelect={onSelectJunction} />
        </Fold>
      )}
      {picker && (
        <Fold title={foldTitle(ROUTE_FOLDS.choices.title, pickerCount)} heading={ROUTE_FOLDS.choices.title} open={ROUTE_FOLDS.choices.open}>
          {picker}
        </Fold>
      )}
      {/* Riders often arrive by a shared link, straight into a route, and a
          phone has no hover to show the handle: say that the line moves. */}
      <p className="hint reshape">
        {narrow
          ? "To reshape the route, press and hold the line, then drag it."
          : "To reshape the route, drag the line."}
      </p>
      <p className="route-credit">Route data: {route.attribution.join("; ")}.</p>
    </div>
  );
}
