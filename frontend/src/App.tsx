import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
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
import { planToOpen, rememberPlan } from "./lib/signIn.ts";
import { STILL_PLANNING_AFTER_MS, announceRoute, calmSearchNote, detourView, paceText, pointName, stillPlanningSaid } from "./lib/summary.ts";
import { focusesPlanButton, isCancelKey, opensSheet, sheetOrder, type SheetSection } from "./lib/sheet.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, neutralPaletteSearch } from "./stressStyle.js";
import { HighStressLanesSwitch } from "./lib/highStressLanesSwitch.ts";
import { useHighStressLanes } from "./useStressStyle.ts";
import { useStressStyle } from "./useStressStyle.ts";
import { ANNOUNCE_SETTLE_MS, SettledText } from "./lib/settle.ts";
import { skipToPlanner, SKIP_LINK_TEXT } from "./lib/skipLink.ts";
import { AccessibilitySwitch } from "./lib/accessibilitySwitch.ts";
import { CandidatePicker } from "./lib/candidatePicker.ts";
import { BetaBanner, betaReportUrl, isBetaBuild } from "./lib/betaBanner.ts";
import { DialsPanel } from "./DialsPanel.tsx";
import { announceHow, candidateRoute, candidateRows } from "./lib/candidates.ts";
import { canReverse, loopNote, loopStops, reversedPoints } from "./lib/loop.ts";
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
import { RouteDescription } from "./RouteDescription.tsx";
import { RideTypePicker } from "./RideTypePicker.tsx";
import type { Dials } from "./lib/dials.ts";
import { WeightStore, withWeight, type StoredWeight } from "./lib/weight.ts";
import { stationEdit, type RailVisibility, type StationRole } from "./lib/railStations.ts";
import { RailStationsSection } from "./RailStations.tsx";
import { RAIL_STATIONS } from "./lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "./lib/federalLand.ts";
import { FederalLandFor, FederalPointsList, type FederalStatus } from "./lib/federalLegend.ts";
import { addCoverageMask, fetchCoverage, watchForFacilities, watchZoom } from "./lib/mapGlue.ts";
import { StressLegend } from "./lib/stressLegend.ts";
import { PointsList } from "./lib/pointsList.ts";
import { planEdits, travelSaid, type Snapshot as PlanSnapshot } from "./lib/planEdits.ts";
import { mapWhen } from "./lib/rideTime.ts";
import { registerStressProtocol } from "./lib/stressProtocol.ts";
import * as maplibregl from "maplibre-gl";
import { PlaceSearch } from "./PlaceSearch.tsx";
import { usePlaceNames } from "./usePlaceNames.ts";
import { pickIntoPlan, pointRows, type Place, type PlaceChoice } from "./lib/geocode.ts";
import { GpxPanel, downloadGpx } from "./GpxPanel.tsx";
import {
  AccessibilityShortcut,
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
  copyText,
  focusOnViewChange,
  foldTitle,
  linkSaidFor,
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

function session(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const initialPlan = decodePlan(planToOpen(session(), window.location.hash));

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
  const [rail, setRail] = useState<RailVisibility>({ metro: true, marc: true });
  // The Mass Ride map's federal-land shading (lib/federalLand.ts): the rider's
  // own switch, on by default, and whether its data has arrived.
  const [federalOn, setFederalOn] = useState(true);
  const [federalStatus, setFederalStatus] = useState<FederalStatus>("loading");
  const [federalData, setFederalData] = useState<FederalData | null>(null);
  // Whether the grey coverage mask is on the map, and whether the stress tiles
  // carry bike-facility data; each legend line is shown only when it is true.
  const [coverageShown, setCoverageShown] = useState(false);
  const [facilitiesShown, setFacilitiesShown] = useState<ReadonlySet<string>>(new Set());
  const [zoom, setZoom] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  // Which view the panel body shows: the planner, or one of the bottom bar's sheets (Map layers,
  // which Legend opens scrolled to the legend, GPX, About). The planner stays in the page, hidden,
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
  const aboutHeadingRef = useRef<HTMLHeadingElement>(null);
  // What "Copy link" answered: said politely, and again for a second press.
  const [linkSaid, setLinkSaid] = useState("");
  const linkPresses = useRef(0);
  // The span, in km, the rider has said yes to planning (longRide.ts).
  const [confirmedKm, setConfirmedKm] = useState<number | null>(null);
  const [crosshair, setCrosshair] = useState({ button: false, canvas: false });
  // The junction a click on the route summary's list names; `nonce` makes a second
  // click on the same one open its card again.
  const [junctionFocus, setJunctionFocus] = useState<{ index: number; nonce: number } | null>(null);
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
  // The GPX file opened last (GpxPanel), until the plan is cleared.
  const [imported, setImported] = useState<ImportedPlan | null>(null);
  // The ride type, the sliders and the opened file as they are now, for the
  // undo history (kept current at once by applyRide, like pointsRef).
  const rideRef = useRef<Ride>({ preset, dials, imported });
  rideRef.current = { preset, dials, imported };
  const narrow = useNarrow();
  const mapRef = useRef<MapLibreMap | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const removeRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const addRef = useRef<HTMLButtonElement>(null);
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
    else {
      const heading = target.legend ? legendHeadingRef : { layers: layersHeadingRef, gpx: gpxHeadingRef, about: aboutHeadingRef }[target.view];
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

  // After Remove, the focus goes to the next Remove button, or to Add.
  useEffect(() => {
    const index = focusAfterRemove.current;
    if (index === null) return;
    focusAfterRemove.current = null;
    const target = removeRefs.current[Math.min(index, points.length - 1)];
    (target ?? addRef.current)?.focus();
  }, [points]);

  // The latest points, for handlers the map holds on to between renders.
  const pointsRef = useRef(points);
  pointsRef.current = points;

  const announce = useCallback((text: string) => setSaid((s) => ({ text, count: s.count + 1 })), []);

  // The points notice ("outside the area", "at most 25 points") is a status in the Points section; while a
  // bar sheet or the phone's hidden sheet hides the planner it would say nothing, so it is said through
  // the app-level region then, and only then (no second reading while the planner shows it; recheck S1).
  const plannerShownNow = useRef(true);
  plannerShownNow.current = view === "planner" && panelOpen;
  useEffect(() => {
    if (noticeSaidElsewhere(notice, plannerShownNow.current)) announce(notice as string);
  }, [notice, announce]);

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
      if (typesText(event.target as HTMLElement | null)) return;
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
  }, [undo, redo]);

  const place = useCallback((point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That point is outside the area this map covers (the DC region to Baltimore).");
      return;
    }
    if (pointsRef.current.length >= MAX_POINTS) {
      setNotice(`A route can have at most ${MAX_POINTS} points.`);
      return;
    }
    setNotice(null);
    const next = addPoint(pointsRef.current, point, loopVias);
    commit(next);
    announce(addedSaid(next.indexOf(point), next.length, loopVias));
  }, [commit, announce, loopVias]);

  const move = useCallback((index: number, point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That point is outside the area this map covers; it was put back.");
      setMarkerReset((n) => n + 1);
      return;
    }
    setNotice(null);
    commit(pointsRef.current.map((p, i) => (i === index ? point : p)));
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

  // A place picked from search: the start, the destination or a stop, as chosen
  // (geocode.ts, applyPlace), named as it was found, and the map goes there.
  const pickPlace = (found: Place, choice: PlaceChoice) => {
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
  const openSheet = (item: BarItem) => {
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
    const done = await copyText(linkToCopy(window.location, points, preset, dials), navigator.clipboard, selectionCopy);
    window.setTimeout(() => {
      if (press === linkPresses.current) setLinkSaid(linkSaidFor(done));
    }, 150);
  };

  // The map frames a route in the part the panel does not cover.
  const framePadding = useCallback((): Frame => {
    const panel = panelRef.current?.getBoundingClientRect();
    if (window.matchMedia(NARROW).matches) {
      // The attribution sits above the sheet on a phone; leave room for it too.
      return { top: 40, left: 30, right: 30, bottom: (panel?.height ?? 0) + 90 };
    }
    return { top: 60, bottom: 60, right: 60, left: (panel?.right ?? 0) + 40 };
  }, []);

  const stale = status.kind === "loading" || status.kind === "waiting";
  const shown = status.kind === "error" || status.kind === "confirm" ? null : route;
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
  // A route arriving while the focus is in the search, Add point at map center or the tools hides
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
  const pointsSection = (
    <section key="points" aria-labelledby="points-heading">
      <h2 id="points-heading" ref={pointsHeadingRef} tabIndex={-1}>
        Points
      </h2>
      {PLANNER_EXTRAS.zoomNotice && <PlannerZoomNotice zoom={zoom} shown={stressVisible && stress === "available"} />}
      {PLANNER_EXTRAS.accessibilityShortcut && (
        <AccessibilityShortcut on={accessibilityOn()} paletteFromAddress={paletteSetByAddress()} onChange={(on) => setAccessibility(on)} />
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
        />
      </div>
      {points.length === 0 ? (
        <p className="hint">{searchLede(loopVias)}</p>
      ) : (
        <PointsList
          rows={pointRows(points, namer, loopVias)}
          onRemove={removeAt}
          removeRef={(index, button) => {
            removeRefs.current[index] = button;
          }}
        />
      )}
      {points.length === 1 && <p className="hint">{loneStartHint(preset, loopVias)}</p>}
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
      {federalPlanner}
      <div id="points-edit" ref={pointsEditRef} hidden={compactPoints}>
      <div className="actions point-add">
        <button
          type="button"
          ref={addRef}
          onClick={addAtCentre}
          onFocus={() => setCrosshair((c) => ({ ...c, button: true }))}
          onBlur={() => setCrosshair((c) => ({ ...c, button: false }))}
          onMouseEnter={() => setCrosshair((c) => ({ ...c, button: true }))}
          onMouseLeave={() => setCrosshair((c) => ({ ...c, button: false }))}
          disabled={points.length >= MAX_POINTS}
        >
          Add point at map center
        </button>
      </div>
      {/* The compact row: Reverse, Undo, Redo and Clear. */}
      <div className="actions point-tools">
        {/* aria-disabled, not disabled, in a loop of a start and one stop: it stays in
            the Tab order with its reason as its description, as the loop toggle does
            (DialsPanel), and a press says the reason. */}
        <button
          type="button"
          onClick={reverse}
          disabled={points.length < 2}
          aria-disabled={reverseHint ? true : undefined}
          aria-describedby={reverseHint ? "reverse-hint" : undefined}
        >
          Reverse
        </button>
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
        {points.length > 0 ? <p className="hint">{editingTips()}</p> : <p className="hint">{emptyPlanHint(preset, loopVias)}</p>}
        {coverageShown && <p className="hint">Gray areas are outside what RouteMaker covers.</p>}
      </MoreTips>
      </div>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
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
          picker={
            candidateRows(answer) === null ? null : (
              <CandidatePicker answer={answer} choice={choice} onChoose={choose} />
            )
          }
          pickerCount={candidateRows(answer)?.length ?? 0}
        />
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
          points={points}
          resolvedWhen={route?.dials?.when ?? null}
        />
      </RideSettings>
    ),
    points: pointsSection,
    route: routeSection,
  };

  return (
    <div className="app">
      {/* Past the map, its markers and its controls (up to 150 junction
          markers come before the planner), to the planner (lib/skipLink.ts). */}
      <a className="skip-link" href="#route-planner" onClick={(event) => skipToPlanner(event, panelRef.current)}>
        {SKIP_LINK_TEXT}
      </a>
      <MapView
        points={points}
        loopVias={loopVias}
        route={shown}
        stale={stale}
        stressVisible={stressVisible && stress === "available"}
        when={mapWhen(dials.when ?? null)}
        framePadding={framePadding}
        onStressAvailability={setStress}
        onMapClick={place}
        onMovePoint={move}
        lineEdit={lineEdit}
        onLineDrop={insertOnLine}
        onRemovePoint={removeFromMap}
        markerReset={markerReset}
        junctionFocus={junctionFocus}
        onReady={(map) => {
          mapRef.current = map;
          void fetchCoverage(window.location.origin).then((coverage) => {
            if (coverage && mapRef.current === map && addCoverageMask(map, coverage)) setCoverageShown(true);
          });
          watchForFacilities(map, setFacilitiesShown);
          watchZoom(map, setZoom);
        }}
        onCanvasFocus={(focused) => setCrosshair((c) => ({ ...c, canvas: focused }))}
        rail={rail}
        federalVisible={federalShown(preset, federalOn)}
        federalWanted={federalShown(preset, true) /* Mass Ride: the planner's points list needs the data whatever the switch says */}
        onFederalStatus={setFederalStatus}
        onFederalData={setFederalData}
        onStationPoint={placeStation}
      />
      {(crosshair.button || crosshair.canvas) && <div className="crosshair" aria-hidden="true" />}
      {narrow && (can.undo || can.redo) && (
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
      <aside
        ref={panelRef}
        id="route-planner"
        tabIndex={-1}
        className={`panel ${panelOpen ? "open" : "closed"}`}
        aria-label="Route planner"
      >
        <header className="panel-header">
          <div>
            <h1>RouteMaker</h1>
            <p className="tagline">Bike routes for the DC region and Baltimore. No sign-in needed.</p>
          </div>
          <button
            type="button"
            className="panel-toggle"
            aria-expanded={panelOpen}
            aria-controls="panel-body"
            onClick={() => setPanelOpen((open) => !open)}
          >
            {panelOpen ? "Hide" : "Plan"}
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
              {/* In 312's order: traffic stress, high-stress lanes, accessibility colors, federal land
                  (Mass Ride's alone), rail stations; then the full legend. */}
              <section aria-labelledby="layers-heading">
                <h3 id="layers-heading">Traffic stress</h3>
                {stress === "available" && (
                  <label className="toggle">
                    <input
                      id="show-stress"
                      type="checkbox"
                      checked={stressVisible}
                      onChange={(event) => setStressVisible(event.target.checked)}
                    />
                    Show traffic stress on the map
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
                <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} />
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

              {RAIL_STATIONS.length > 0 && <RailStationsSection visibility={rail} onChange={setRail} />}

              {/* Mockup v3's line; the Mass Ride layers sheet itself waits on FOLLOWUP-MASSRIDE-MAP (324-334). */}
              {!federalShown(preset, true) && <p className="hint mass-ride-layers">{MASS_RIDE_LAYERS_NOTE}</p>}

              <section aria-labelledby="legend-heading">
                <h3 id="legend-heading" ref={legendHeadingRef} tabIndex={-1}>
                  Legend
                </h3>
                {stress === "available" ? (
                  <StressLegend facilities={facilitiesShown} zoom={zoom} shown={stressVisible} foldedZoom />
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
              id="sheet-about"
              title={SHEET_TITLES.about}
              open={view === "about"}
              onBack={backToPlanner}
              headingRef={aboutHeadingRef}
            >
              <p className="hint">
                Planning works without signing in, and a plan made signed out is not saved; the link in the address bar
                reopens it. Saving routes and peer review are coming for riders who{" "}
                <a href="/auth/login" onClick={() => rememberPlan(session(), window.location.hash)}>
                  sign in with Discord
                </a>
                ; your current plan is kept across the sign-in.
              </p>
            </SheetFrame>
          </div>

          {/* Pinned under the scrolling part while a route is shown: its file and its link. */}
          {view === "planner" && shown && (
            <div className="route-actions">
              <button type="button" onClick={() => downloadGpx(shown, routedPoints, routedLoop)}>
                Download GPX
              </button>
              <button type="button" className="secondary" onClick={copyLink}>
                {COPY_LINK}
              </button>
              <span role="status" className="visually-hidden">
                {linkSaid}
              </span>
              {linkSaid && (
                <span className="hint link-said" aria-hidden="true">
                  {linkSaid}
                </span>
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
  picker,
  pickerCount,
}: {
  route: RouteResponse;
  points: LonLat[];
  narrow: boolean;
  onSelectJunction: (index: number) => void;
  /** The routes to choose from (CandidatePicker), or null with one route. */
  picker: ReactNode;
  pickerCount: number;
}) {
  useStressStyle();
  const segments = stressSegments(route.stress_m);
  const detour = detourView(route, points);
  const calmNote = calmSearchNote(route);
  const loopSaid = loopNote(route);
  const pace = paceText(route);
  // The sidebar's route view (OWNER-DECISIONS 312): the totals, the stress bar and four quick
  // figures in view; Stress and facilities, Directions, Junctions to watch and Routes to choose
  // from as folds. There is no elevation chart yet (322), so no fold for one.
  const junctions = route.intersections == null ? null : junctionItems(route).length;
  return (
    <div className="summary">
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
      <FacilityBreakdown route={route} part="notices" />
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
      <RouteDescription route={route} fold />
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
