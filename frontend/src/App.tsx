import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
import { canDragLine, dropStillValid, insertIntoLeg, legEnds } from "./lib/lineEdit.ts";
import { EditHistory, isRedoKey, isUndoKey, step, typesText } from "./lib/editHistory.ts";
import { requestRoute, type RouteError, type RouteResponse, type RouteResult } from "./lib/api.ts";
import { MAX_POINTS, addPoint, insideCoverage, type LonLat } from "./lib/geo.ts";
import { formatClimb, formatDistance, formatDuration, formatSeconds } from "./lib/format.ts";
import { PRESETS, presetLabel, type PresetId } from "./lib/presets.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { stressSegments } from "./lib/stressBar.ts";
import { RouteScheduler, type SchedulerState } from "./lib/routeScheduler.ts";
import { confirmedUpTo, sendsConfirmation, spanKm } from "./lib/longRide.ts";
import { planToOpen, rememberPlan } from "./lib/signIn.ts";
import { announceRoute, detourNotice, paceText } from "./lib/summary.ts";
import { focusesPlanButton, isCancelKey, opensSheet, sheetOrder, type SheetSection } from "./lib/sheet.ts";
import { CASING_EXTRA_PX, STRESS_TIERS } from "./stressStyle.js";

interface Plan {
  points: LonLat[];
  preset: PresetId;
  confirmLong: boolean;
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

/** A point's name in the list: Start, Via 1, Via 2, ..., End. */
function pointName(index: number, count: number): string {
  if (index === 0) return "Start";
  if (index === count - 1 && count > 1) return "End";
  return `Via ${index}`;
}
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
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [routedPoints, setRoutedPoints] = useState<LonLat[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [notice, setNotice] = useState<string | null>(null);
  const [stress, setStress] = useState<StressAvailability>("checking");
  const [stressVisible, setStressVisible] = useState(true);
  const [panelOpen, setPanelOpen] = useState(true);
  // The span, in km, the rider has said yes to planning (longRide.ts).
  const [confirmedKm, setConfirmedKm] = useState<number | null>(null);
  const [crosshair, setCrosshair] = useState({ button: false, canvas: false });
  // Bumped to put the markers back where the points are, without changing
  // the points (which would plan the same route again).
  const [markerReset, setMarkerReset] = useState(0);
  // Undo and redo (editHistory.ts), and whether each has anything to give
  // back, which is what their buttons need to know.
  const history = useRef(new EditHistory<LonLat[]>());
  const [can, setCan] = useState({ undo: false, redo: false });
  // What an edit on the map did, for a screen reader: the map itself says
  // nothing. The count makes the same sentence twice a new announcement.
  const [said, setSaid] = useState({ text: "", count: 0 });
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

  // One scheduler for the page: one request in flight, the latest plan only,
  // Retry-After waited out (routeScheduler.ts).
  const scheduler = useRef<RouteScheduler<Plan> | null>(null);
  if (scheduler.current === null) {
    scheduler.current = new RouteScheduler<Plan>({
      send: (plan) => requestRoute(plan.points, plan.preset, { confirmLong: plan.confirmLong }),
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
    const hash = encodePlan(points, preset);
    writtenHash.current = hash;
    window.history.replaceState(null, "", hash);
  }, [points, preset]);

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
      setPoints(plan.points);
      setPreset(plan.preset);
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
    scheduler.current?.request({ points, preset, confirmLong: sendsConfirmation(points, confirmedKm) });
  }, [points, preset, confirmedKm]);

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

  /** Every edit of the points goes through here, so undo can give the list before it back. */
  const commit = useCallback((next: LonLat[]) => {
    const before = pointsRef.current;
    history.current.record(before);
    syncHistory();
    // Kept current at once, so a second edit before the next render builds on this one.
    pointsRef.current = next;
    setPoints(next);
  }, [syncHistory]);

  /** Undo or redo: the list the history gives back, which is not itself an edit. */
  const travel = useCallback(
    (direction: "undo" | "redo") => {
      const current = pointsRef.current;
      const next = step(history.current, direction, current);
      if (next === undefined) return;
      syncHistory();
      pointsRef.current = next;
      setPoints(next);
      setNotice(null);
      const count = `${next.length} ${next.length === 1 ? "point" : "points"}`;
      announce(`${direction === "undo" ? "Undone" : "Redone"}. The route has ${count}.`);
    },
    [announce, syncHistory],
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
      announce(`Via point ${leg + 1} added, between ${pointName(leg, next.length)} and ${pointName(leg + 2, next.length)}.`);
    },
    [commit, announce],
  );

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
    commit([]);
  };
  const addAtCentre = () => {
    const map = mapRef.current;
    if (!map) return;
    const { lng, lat } = map.getCenter();
    place([lng, lat]);
  };
  const retry = () => scheduler.current?.request({ points, preset, confirmLong: sendsConfirmation(points, confirmedKm) });
  const confirmLong = () => {
    const asked = status.kind === "confirm" && status.error.spanKm !== undefined ? status.error.spanKm : spanKm(points);
    const upTo = confirmedUpTo(Math.max(asked, spanKm(points)));
    setConfirmedKm(upTo);
    // "Not planned", from an earlier Cancel, is no longer true.
    setNotice(null);
    // Sent here as well as by the effect, which does not run again when the
    // confirmed span is unchanged; the debounce folds the two into one.
    scheduler.current?.request({ points, preset, confirmLong: true });
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
          ? announceRoute(route)
          : "";

  const presetsSection = (
    <fieldset key="presets" className="presets">
      <legend>Ride type</legend>
      {PRESETS.map((option) => (
        <label key={option.id} className="preset">
          <input
            type="radio"
            name="preset"
            value={option.id}
            checked={preset === option.id}
            onChange={() => setPreset(option.id)}
          />
          <span>
            <strong>{option.label}</strong>
            <span className="hint">{option.description}</span>
          </span>
        </label>
      ))}
      <p className="hint">The ride types differ most on longer and rural routes; in town they often agree.</p>
    </fieldset>
  );
  const pointsSection = (
    <section key="points" aria-labelledby="points-heading">
      <h2 id="points-heading" ref={pointsHeadingRef} tabIndex={-1}>
        Points
      </h2>
      {points.length === 0 ? (
        <p className="hint">
          Click the map to set a start, then an end. Later clicks add a via point on the
          nearest leg. Drag any marker to move it, or drag the route line to pull it through
          somewhere else (on a phone, press and hold the line first). Click a via point for
          Remove. From the keyboard, move the map with the arrow keys and use "Add point at
          map centre"; Ctrl+Z undoes the last change and Ctrl+Shift+Z redoes it.
        </p>
      ) : (
        <ol className="points">
          {points.map((point, index) => {
            const name = pointName(index, points.length);
            return (
              <li key={index}>
                <span className="point-name">{name}</span>
                <span className="coords">
                  {point[1].toFixed(4)}, {point[0].toFixed(4)}
                </span>
                <button
                  type="button"
                  className="link"
                  ref={(el) => {
                    removeRefs.current[index] = el;
                  }}
                  onClick={() => removeAt(index)}
                  aria-label={`Remove ${name}`}
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ol>
      )}
      {points.length === 1 && <p className="hint">Now click the map where you want to finish.</p>}
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
      <div role="status" aria-live="polite" className="status-line">
        {status.kind === "loading" && <p className="loading">{announcement}</p>}
        {status.kind === "waiting" && <p className="loading">{announcement}</p>}
        {status.kind === "ok" && <p className="visually-hidden">{announcement}</p>}
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
      {shown && <RouteSummary route={shown} points={routedPoints} narrow={narrow} />}
    </section>
  );

  const sections: Record<SheetSection, ReactElement> = {
    presets: presetsSection,
    points: pointsSection,
    route: routeSection,
  };

  return (
    <div className="app">
      <MapView
        points={points}
        route={shown}
        stale={stale}
        stressVisible={stressVisible && stress === "available"}
        framePadding={framePadding}
        onStressAvailability={setStress}
        onMapClick={place}
        onMovePoint={move}
        lineEdit={lineEdit}
        onLineDrop={insertOnLine}
        onRemovePoint={removeFromMap}
        markerReset={markerReset}
        onReady={(map) => {
          mapRef.current = map;
        }}
        onCanvasFocus={(focused) => setCrosshair((c) => ({ ...c, canvas: focused }))}
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
      <aside ref={panelRef} className={`panel ${panelOpen ? "open" : "closed"}`} aria-label="Route planner">
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

          <section aria-labelledby="layers-heading">
            <h2 id="layers-heading">Traffic stress</h2>
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
                <StressLegend />
              </>
            )}
            {stress === "checking" && <p className="hint">Checking the stress map…</p>}
            {stress === "unavailable" && (
              <p className="hint">
                Stress map unavailable for now. Routes still show how much of each ride is on each stress level.
              </p>
            )}
          </section>

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

function RouteSummary({ route, points, narrow }: { route: RouteResponse; points: LonLat[]; narrow: boolean }) {
  const segments = stressSegments(route.stress_m);
  const detourText = detourNotice(route, points);
  const pace = paceText(route);
  return (
    <div className="summary">
      {detourText && (
        <p className="notice detour" role="note">
          {detourText}
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
                  style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color }}
                  title={`${s.short}: ${s.percent}%`}
                />
              ))}
          </div>
          <ul className="stress-list">
            {segments.map((s) => (
              <li key={s.key}>
                <span className={`swatch stress-seg-${s.key}`} style={{ backgroundColor: s.color }} aria-hidden="true" />
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

function StressLegend() {
  return (
    <>
      <ul className="legend" aria-label="Traffic stress legend">
        {STRESS_TIERS.map((tier) => (
          <li key={tier.tier}>
            <svg width="44" height="12" aria-hidden="true">
              <line x1="2" y1="6" x2="42" y2="6" stroke={tier.casing} strokeWidth={tier.width + CASING_EXTRA_PX} />
              <line
                x1="2"
                y1="6"
                x2="42"
                y2="6"
                stroke={tier.color}
                strokeWidth={tier.width}
                strokeDasharray={tier.dash.map((d: number) => d * tier.width).join(" ")}
              />
            </svg>
            <span className="stress-name">{tier.short}</span>
            <span className="stress-label">{tier.label}</span>
          </li>
        ))}
      </ul>
      <p className="hint">Streets with no stress rating are not drawn.</p>
    </>
  );
}
