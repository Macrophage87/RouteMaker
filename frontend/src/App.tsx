import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
import { canDragLine, dropStillValid, insertIntoLeg, legEnds } from "./lib/lineEdit.ts";
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
import { announceRoute, calmSearchNote, detourView, paceText, pointName } from "./lib/summary.ts";
import { focusesPlanButton, isCancelKey, opensSheet, sheetOrder, type SheetSection } from "./lib/sheet.ts";
import { FACILITIES, accessibilityOn, accessibilitySource, currentTiers, legendWidths, paletteSetByAddress, setAccessibility, setHighStressLanes, unpavedWidth, UNPAVED_DASH } from "./stressStyle.js";
import { HighStressLanesSwitch } from "./lib/highStressLanesSwitch.ts";
import { useHighStressLanes } from "./useStressStyle.ts";
import { useStressStyle } from "./useStressStyle.ts";
import { ANNOUNCE_SETTLE_MS, SettledText } from "./lib/settle.ts";
import { skipToPlanner, SKIP_LINK_TEXT } from "./lib/skipLink.ts";
import { AccessibilitySwitch } from "./lib/accessibilitySwitch.ts";
import { DialsPanel } from "./DialsPanel.tsx";
import { FacilityBreakdown } from "./FacilityBreakdown.tsx";
import { IntersectionList } from "./IntersectionList.tsx";
import { RouteDescription } from "./RouteDescription.tsx";
import { RideTypePicker } from "./RideTypePicker.tsx";
import type { Dials } from "./lib/dials.ts";
import { stationEdit, type RailVisibility, type StationRole } from "./lib/railStations.ts";
import { RailStationsSection } from "./RailStations.tsx";
import { RAIL_STATIONS } from "./lib/railData.ts";
import { addCoverageMask, fetchCoverage, watchForFacilities, watchZoom } from "./lib/mapGlue.ts";
import { ROADWAY_LANES, StressZoomNotes } from "./lib/stressLegend.ts";
import { PointsList } from "./lib/pointsList.ts";
import { planEdits, travelSaid, type Snapshot as PlanSnapshot } from "./lib/planEdits.ts";
import { mapWhen } from "./lib/rideTime.ts";
import { registerStressProtocol } from "./lib/stressProtocol.ts";
import * as maplibregl from "maplibre-gl";
import { PlaceSearch } from "./PlaceSearch.tsx";
import { usePlaceNames } from "./usePlaceNames.ts";
import { pickIntoPlan, pointRows, type Place, type PlaceChoice } from "./lib/geocode.ts";
import { GpxPanel } from "./GpxPanel.tsx";
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
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [routedPoints, setRoutedPoints] = useState<LonLat[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [notice, setNotice] = useState<string | null>(null);
  const [stress, setStress] = useState<StressAvailability>("checking");
  const [stressVisible, setStressVisible] = useState(true);
  useStressStyle();
  const showHighLanes = useHighStressLanes();
  const [rail, setRail] = useState<RailVisibility>({ metro: true, marc: true });
  // Whether the grey coverage mask is on the map, and whether the stress tiles
  // carry bike-facility data; each legend line is shown only when it is true.
  const [coverageShown, setCoverageShown] = useState(false);
  const [facilitiesShown, setFacilitiesShown] = useState<ReadonlySet<string>>(new Set());
  const [zoom, setZoom] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
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

  // Keep the link in step with the plan, without adding history entries.
  useEffect(() => {
    const hash = encodePlan(points, preset, dials);
    writtenHash.current = hash;
    window.history.replaceState(null, "", hash);
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
      return;
    }
    scheduler.current?.request({ points, preset, dials, confirmLong: sendsConfirmation(points, confirmedKm) });
  }, [points, preset, dials, confirmedKm]);

  // The long-ride question and every error are in the sheet; on a phone whose
  // sheet is hidden they would otherwise be invisible, so the sheet opens
  // (sheet.ts), for each new one.
  useEffect(() => {
    if (opensSheet(status.kind)) setPanelOpen(true);
  }, [status]);

  // The long-ride question takes the focus, so a keyboard rider lands on it
  // (once the sheet is open: a hidden button cannot take it).
  const focusPlan = focusesPlanButton(status.kind, panelOpen);
  useEffect(() => {
    if (focusPlan) planButtonRef.current?.focus();
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
      const next = edits.travel(direction);
      if (next === undefined) return;
      setNotice(null);
      announce(travelSaid(direction, next.length));
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
    const next = addPoint(pointsRef.current, point);
    commit(next);
    announce(`${pointName(next.indexOf(point), next.length)} added.`);
  }, [commit, announce]);

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
  // if the points have changed since, the leg means nothing any more.
  const insertOnLine = useCallback(
    (leg: number, point: LonLat, routed: LonLat[]) => {
      if (!dropStillValid(routed, pointsRef.current)) return;
      if (!insideCoverage(point)) {
        setNotice("That point is outside the area this map covers; it was put back.");
        return;
      }
      const next = insertIntoLeg(routed, leg, point);
      if (next === null) {
        setNotice(`A route can have at most ${MAX_POINTS} points.`);
        return;
      }
      setNotice(null);
      commit(next);
      announce(`Stop ${leg + 1} added, between ${pointName(leg, next.length)} and ${pointName(leg + 2, next.length)}.`);
    },
    [commit, announce],
  );

  // A station's Start here / End here / Add as stop (railStations.ts): an
  // edit of the points like any other, so it can be undone and redone.
  const placeStation = useCallback((role: StationRole, point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That station is outside the area this map covers.");
      return;
    }
    const edit = stationEdit(pointsRef.current, point, role);
    if ("refused" in edit) {
      if (edit.refused === "cap") setNotice(`A route can have at most ${MAX_POINTS} points.`);
      return;
    }
    setNotice(null);
    commit(edit.next);
    announce(`${pointName(edit.index, edit.next.length)} set at the station.`);
  }, [commit, announce]);

  // A place picked from search: the start, the destination or a stop, as chosen
  // (geocode.ts, applyPlace), named as it was found, and the map goes there.
  const pickPlace = (found: Place, choice: PlaceChoice) => {
    const point = pickIntoPlan(found, choice, {
      current: () => pointsRef.current,
      commit,
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
      const name = pointName(index, current.length);
      commit(current.filter((_, i) => i !== index));
      announce(`${name} removed.`);
    },
    [commit, announce],
  );
  const clearAll = () => {
    setConfirmedKm(null);
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
    scheduler.current?.request({ points, preset, dials, confirmLong: sendsConfirmation(points, confirmedKm) });
  // A new ride type moves the sliders to where it starts them (RideTypePicker).
  const choosePreset = (id: PresetId, next: Dials) => {
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
    scheduler.current?.request({ points, preset, dials, confirmLong: true });
    // The question goes away; the focus goes to where the answer will be.
    routeHeadingRef.current?.focus();
  };
  const cancelLong = () => {
    setStatus({ kind: "idle" });
    setNotice("Not planned. Move or remove points for a shorter ride; any change asks again.");
    // To the points, which are what the rider changes next.
    pointsHeadingRef.current?.focus();
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
    return { path, ends: legEnds(path, routedPoints, shown.leg_ends), points: routedPoints };
  }, [shown, stale, routedPoints, points]);
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
    if (routeFirst) panelBodyRef.current?.scrollTo({ top: 0 });
  }, [routeFirst]);

  // Each new question or error is shown from the top of the sheet, where the
  // Route section now is: a sheet left scrolled down to the ride types would
  // open with the reason it opened out of sight.
  const attention = opensSheet(status.kind) ? status : null;
  useLayoutEffect(() => {
    if (attention && routeFirst) panelBodyRef.current?.scrollTo({ top: 0 });
  }, [attention]);

  const announcement =
    status.kind === "loading"
      ? `Planning a ${presetLabel(preset)} route…`
      : status.kind === "waiting"
        ? `The planner is busy; trying again in ${formatSeconds(status.seconds)}.`
        : status.kind === "ok" && route
          ? announceRoute(route, routedPoints)
          : "";
  // The route's sentence once it has stood a moment (lib/settle.ts): routes
  // that replace each other quickly are said once, the last. "Planning..." is
  // shown but not said, so a release is one announcement, not two.
  const routeSaid = useSettled(status.kind === "ok" ? announcement : "", ANNOUNCE_SETTLE_MS);

  const presetsSection = <RideTypePicker key="presets" preset={preset} dials={dials} onChoose={choosePreset} />;
  const pointsSection = (
    <section key="points" aria-labelledby="points-heading">
      <h2 id="points-heading" ref={pointsHeadingRef} tabIndex={-1}>
        Points
      </h2>
      <PlaceSearch
        pointCount={points.length}
        full={points.length >= MAX_POINTS}
        gate={geoGate}
        bias={searchBias}
        onPick={pickPlace}
      />
      {points.length === 0 ? (
        <p className="hint">
          Search for a place, or click the map to set a start, then an end. Later clicks add a
          stop on the nearest leg. Drag any marker to move it, or drag the route line to
          pull it through somewhere else (on a phone, press and hold the line first). Click a
          stop for Remove. From the keyboard, move the map with the arrow keys and use
          "Add point at map centre"; Ctrl+Z undoes the last change and Ctrl+Shift+Z redoes it.
        </p>
      ) : (
        <PointsList
          rows={pointRows(points, namer)}
          onRemove={removeAt}
          removeRef={(index, button) => {
            removeRefs.current[index] = button;
          }}
        />
      )}
      {points.length === 1 && <p className="hint">Now click the map where you want to finish.</p>}
      {coverageShown && <p className="hint">Grey areas are outside what RouteMaker covers.</p>}
      <div className="actions">
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
          Add point at map centre
        </button>
        <button type="button" onClick={() => commit([...pointsRef.current].reverse())} disabled={points.length < 2}>
          Reverse
        </button>
        <button type="button" onClick={clearAll} disabled={points.length === 0}>
          Clear
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
      <div role="status" aria-live="polite" className="status-line">
        {status.kind === "waiting" && <p className="loading">{announcement}</p>}
        {status.kind === "ok" && routeSaid && <p className="visually-hidden">{routeSaid}</p>}
        {status.kind === "idle" && points.length < 2 && <p className="hint">No route yet.</p>}
      </div>
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
        <div className={`error error-${status.error.kind}`} role="alert">
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
        />
      )}
    </section>
  );

  const sections: Record<SheetSection, ReactElement> = {
    presets: (
      <Fragment key="presets">
        {presetsSection}
        <DialsPanel preset={preset} dials={dials} onCommit={setDials} resolvedWhen={route?.dials?.when ?? null} />
      </Fragment>
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
        <div id="panel-body" ref={panelBodyRef} className="panel-body" hidden={!panelOpen}>
          {order.map((id) => sections[id])}

          <GpxPanel
            route={shown}
            routedPoints={routedPoints}
            points={points}
            planStatus={status.kind}
            imported={imported}
            onImport={openImported}
            onRefine={refineImported}
            getMap={getMap}
          />

          <section aria-labelledby="layers-heading">
            <h2 id="layers-heading">Traffic stress</h2>
            <AccessibilitySwitch
              on={accessibilityOn()}
              source={accessibilitySource()}
              paletteFromAddress={paletteSetByAddress()}
              onChange={(on) => setAccessibility(on)}
            />
            <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} />
            {stress === "available" && (
              <>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={stressVisible}
                    onChange={(event) => setStressVisible(event.target.checked)}
                  />
                  Show traffic stress on the map
                </label>
                <StressLegend facilities={facilitiesShown} zoom={zoom} shown={stressVisible} />
              </>
            )}
            {stress === "checking" && <p className="hint">Checking the stress map…</p>}
            {stress === "unavailable" && (
              <p className="hint">
                Stress map unavailable for now. Routes still show how much of each ride is on each stress level.
              </p>
            )}
          </section>

          {RAIL_STATIONS.length > 0 && <RailStationsSection visibility={rail} onChange={setRail} />}

          <footer className="panel-footer">
            <p>
              Planning works without signing in, and a plan made signed out is not saved; the link in the address bar
              reopens it. Saving routes and peer review are coming for riders who{" "}
              <a href="/auth/login" onClick={() => rememberPlan(session(), window.location.hash)}>
                sign in with Discord
              </a>
              ; your current plan is kept across the sign-in.
            </p>
          </footer>
        </div>
      </aside>
    </div>
  );
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
}: {
  route: RouteResponse;
  points: LonLat[];
  narrow: boolean;
  onSelectJunction: (index: number) => void;
}) {
  useStressStyle();
  const segments = stressSegments(route.stress_m);
  const detour = detourView(route, points);
  const calmNote = calmSearchNote(route);
  const pace = paceText(route);
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
      <dl className="stats">
        <div>
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
      <FacilityBreakdown route={route} />
      <IntersectionList route={route} onSelect={onSelectJunction} />
      <RouteDescription route={route} />
      {/* Riders often arrive by a shared link, straight into a route, and a
          phone has no hover to show the handle: say that the line moves. */}
      <p className="hint reshape">
        {narrow
          ? "To reshape the route, press and hold the line, then drag it."
          : "To reshape the route, drag the line."}
      </p>
      {segments.length > 0 && (
        <figure className="stress">
          <figcaption>Traffic stress along the route</figcaption>
          <div className="stress-bar" aria-hidden="true">
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
          <ul className="stress-list">
            {segments.map((s) => (
              <li key={s.key}>
                <span className={`swatch stress-seg-${s.key}`} style={{ backgroundColor: s.color, ["--seg-accent" as string]: s.casing }} aria-hidden="true" />
                <span className="stress-name">{s.short}</span>
                <span className="stress-label">{s.label}</span>
                <span className="stress-pct">{s.percent}%</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      <p className="route-credit">Route data: {route.attribution.join("; ")}.</p>
    </div>
  );
}

function StressLegend({
  facilities,
  zoom,
  shown,
}: {
  facilities: ReadonlySet<string>;
  zoom: number | null;
  shown: boolean;
}) {
  useStressStyle();
  const showHighLanes = useHighStressLanes();
  const tiers = currentTiers();
  const widths = legendWidths(tiers);
  return (
    <>
      <ul className="legend" aria-label="Traffic stress legend">
        {tiers.map((tier, i) => (
          <li key={tier.tier}>
            <svg width="44" height="12" aria-hidden="true">
              <line x1="2" y1="6" x2="42" y2="6" stroke={tier.casing} strokeWidth={widths.tiers[i].casing} />
              <line
                x1="2"
                y1="6"
                x2="42"
                y2="6"
                stroke={tier.color}
                strokeWidth={widths.tiers[i].line}
                strokeDasharray={tier.dash ? tier.dash.map((d: number) => d * widths.tiers[i].line).join(" ") : undefined}
              />
            </svg>
            <span className="stress-name">{tier.short}</span>
            <span className="stress-label">{tier.label}</span>
          </li>
        ))}
        <li>
          <svg width="44" height="12" aria-hidden="true">
            <line x1="2" y1="6" x2="42" y2="6" stroke={tiers[0].casing} strokeWidth={widths.tiers[0].casing} />
            <line x1="2" y1="6" x2="42" y2="6" stroke={tiers[0].color} strokeWidth={widths.tiers[0].line} />
            <line
              x1="2"
              y1="6"
              x2="42"
              y2="6"
              stroke={tiers[0].casing}
              strokeWidth={unpavedWidth(tiers[0])}
              strokeDasharray={UNPAVED_DASH.map((d: number) => d * unpavedWidth(tiers[0])).join(" ")}
            />
          </svg>
          <span className="stress-name">Unpaved</span>
          <span className="stress-label">A dotted center line on any of the lines above: gravel, dirt or other unpaved surface</span>
        </li>
      </ul>
      {/* What the tiles leave out as the map zooms out (core/stress_tiles.py):
          traffic-free paths and trails alone below STRESS_ZOOMS.busy (lib/stressLegend.ts). */}
      <StressZoomNotes zoom={zoom} shown={shown} />
      {facilities.size > 0 && (
        <>
          <p className="hint">
            Bike facilities are edges on either side of the stress line: a solid dark rail for a path, blocks like posts for a protected lane,
            and a thin dotted rail for paint. Painted lanes on LTS 4 and Avoid roads are{" "}
            {showHighLanes ? "shown because the switch above is on" : "hidden unless you turn on \"Show bike lanes on high-stress roads\""}.
          </p>
          <ul className="legend" aria-label="Bike facility legend">
            {FACILITIES.filter((facility) => facilities.has(facility.facility)).map((facility) => {
              const rails = widths.rails[facility.facility];
              return (
                <li key={facility.facility}>
                  <svg width="44" height="14" aria-hidden="true">
                    <line
                      x1="2"
                      y1="7"
                      x2="42"
                      y2="7"
                      stroke={facility.color}
                      strokeWidth={rails}
                      strokeDasharray={facility.dash ? facility.dash.map((d: number) => d * rails).join(" ") : undefined}
                    />
                    <line x1="2" y1="7" x2="42" y2="7" stroke="#ffffff" strokeWidth={widths.facilityCasing} />
                  </svg>
                  <span className="stress-name">{facility.short}</span>
                  <span className="stress-label">{facility.label}</span>
                </li>
              );
            })}
          </ul>
          <p className="hint">Sharrows count as ordinary streets. {ROADWAY_LANES}</p>
        </>
      )}
    </>
  );
}
