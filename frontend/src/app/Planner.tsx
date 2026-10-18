// Moved out of App.tsx unchanged (UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"): the same
// elements, in the same order, with App's state and handlers passed in under the names App gives them,
// so the DOM, the focus and every announcement are as they were. App.tsx keeps the state and the effects.
import { useEffect, useRef, useState, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import type { StressAvailability } from "../MapView.tsx";
import { ACCESS_HELP, ACCESS_LABEL } from "../lib/accessMode.ts";
import { infoHelp } from "../lib/roadInfo.ts";
import type { RouteResponse } from "../lib/api.ts";
import { MAX_POINTS, type LonLat } from "../lib/geo.ts";
import { YOUR_LOCATION } from "../lib/appMode.ts";
import { usesBikeshare, type PresetId } from "../lib/presets.ts";
import { accessibilityOn, paletteSetByAddress, setAccessibility } from "../stressStyle.js";
import { DialsPanel } from "../DialsPanel.tsx";
import { withLoop, type LoopView } from "../lib/loop.ts";
import { BEST_ORDER_LABEL } from "../lib/stopOrder.ts";
import { editingTips, emptyPlanHint, loneStartHint } from "../lib/pointText.ts";
import { RideTypePicker } from "../RideTypePicker.tsx";
import type { Dials } from "../lib/dials.ts";
import type { StoredWeight, WeightStore } from "../lib/weight.ts";
import { isMassRide } from "../lib/massCapacity.ts";
import { MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { PointsList } from "../lib/pointsList.ts";
import { usePointMover } from "../lib/pointMover.ts";
import { PlaceSearch } from "../PlaceSearch.tsx";
import { approximateHint, type Fix, type locateSupport } from "../lib/geolocation.ts";
import type { usePlaceNames } from "../usePlaceNames.ts";
import { pointRows, type Place, type PlaceChoice } from "../lib/geocode.ts";
import { VIA_MARKS, namePoints } from "../lib/pointKinds.ts";
import { HighContrastShortcut, PlannerZoomNotice, RideSettings } from "../Sidebar.tsx";
import { Icon } from "../Icon.tsx";
import { PLANNER_EXTRAS, searchLede } from "../lib/sidebar.ts";
import { settingsSummary, settingsSummarySpoken } from "../lib/rideSummary.ts";
import { InstallOffer } from "../InstallableApp.tsx";

type PlaceNames = ReturnType<typeof usePlaceNames>;

export interface PointsSectionProps {
  pointsHeadingRef: RefObject<HTMLHeadingElement | null>;
  zoom: number | null;
  stressVisible: boolean;
  stress: StressAvailability;
  pointsSearchRef: RefObject<HTMLDivElement | null>;
  compactPoints: boolean;
  points: LonLat[];
  loopVias: boolean;
  geoGate: PlaceNames["gate"];
  searchBias: () => LonLat | undefined;
  pickPlace: (found: Place, choice: PlaceChoice) => void;
  locateReady: ReturnType<typeof locateSupport>;
  locating: boolean;
  hereInPlan: boolean;
  here: Fix | null;
  useMyLocation: (choice?: PlaceChoice) => Promise<void>;
  loop: LoopView | null;
  loopHintId: string;
  commitDials: (next: Dials) => void;
  dials: Dials;
  accessMode: boolean;
  namer: PlaceNames["namer"];
  /** The points that are the rider's location (App's fromHere): named "Your location" in the list (edit-route redesign). */
  located: readonly LonLat[];
  removeAt: (index: number) => void;
  /** A stop (point `from`) dragged, or moved by a key, to stop `to`'s place: one edit (App.tsx reorderPoint). */
  reorderPoint: (from: number, to: number, by: "drag" | "key") => void;
  pointWarnings: (string | null)[];
  removeRefs: RefObject<Array<HTMLButtonElement | null>>;
  preset: PresetId;
  /** Mass Ride's "no point is on federal land" line, or nothing. */
  federalPlanner: ReactNode;
  pointsEditRef: RefObject<HTMLDivElement | null>;
  reverseButton: RefObject<HTMLButtonElement | null>;
  reverse: () => void;
  reverseHint: string | null;
  orderShown: boolean;
  bestOrder: () => Promise<void>;
  orderFocused: RefObject<boolean>;
  ordering: boolean;
  narrow: boolean;
  undo: () => void;
  can: { undo: boolean; redo: boolean };
  redo: () => void;
  coverageShown: boolean;
  toggleAccessMode: (focusTools: boolean) => void;
  announce: (text: string) => void;
  notice: string | null;
  /**
   * Whether the notice line is a live region: not in Go's Edit route, where the app's own region says it already
   * (App noticeSaidElsewhere), so it is not said twice.
   */
  noticeLive: boolean;
  /** Points' Info (the how-to, behind one button): open or not, and its body's id; App's state. */
  tips: boolean;
  setTips: Dispatch<SetStateAction<boolean>>;
  tipsId: string;
}

/**
 * The planner's Points section (UI-CLEANUP, the approved mockup's Plan): its heading with Swap, Loop, Edit
 * and Info beside it, the search, the points, and the point tools while editing. The nearest finder and
 * Find food moved to the map's Water and Food chips (their own sheets), and Bikeshare's stations to the
 * route's "Choose a station" fold.
 */
export function PointsSection(props: PointsSectionProps) {
  const { pointsHeadingRef, zoom, stressVisible, stress, pointsSearchRef, compactPoints, points, loopVias, geoGate, searchBias, pickPlace, locateReady, locating, hereInPlan, here, useMyLocation, loop, loopHintId, commitDials, dials, accessMode, namer, located, removeAt, reorderPoint, pointWarnings, removeRefs, preset, federalPlanner, pointsEditRef, reverseButton, reverse, reverseHint, orderShown, bestOrder, orderFocused, ordering, narrow, undo, can, redo, coverageShown, toggleAccessMode, announce, notice, noticeLive, tips, setTips, tipsId } = props;
  return (
    <section key="points" aria-labelledby="points-heading" className="points-section">
      <div className="section-head">
        <h2 id="points-heading" ref={pointsHeadingRef} tabIndex={-1}>
          Points
        </h2>
        <div className="section-tools">
          {/* Swap (Reverse), beside Points (the mockup). aria-disabled, not disabled, in a loop of a start and
              one stop: it stays in the Tab order with its reason as its description, and a press says the reason. */}
          {points.length >= 2 && (
            <button
              type="button"
              ref={reverseButton}
              className="secondary icon-button swap-points"
              onClick={reverse}
              aria-disabled={reverseHint ? true : undefined}
              aria-describedby={reverseHint ? "reverse-hint" : "swap-hint"}
            >
              <Icon name="swap" />
              <span>Swap</span>
            </button>
          )}
          {/* Make it a loop (OWNER-DECISIONS 388, 389): by the search, not behind the Ride line's Edit; there
              with no point placed too, and not on Mass Ride. A box styled as the mockup's Loop button. */}
          {loop && (
            <label className="toggle loop-toggle icon-toggle">
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
              <span className="visually-hidden">{loop.label}</span>
              <span aria-hidden="true">Loop</span>
            </label>
          )}
          {/* No "Edit points" any more (v0.7.0): with a route the search and the point tools stay in view, and the
              plan panel holds Route, Reset and Clear, and says the plan in words to a screen reader. */}
          {/* Undo and Redo, beside Swap and Loop (Plan streamline, Stephen 2026-10-17); a phone has Undo in its notices. */}
          {!narrow && (
            <button type="button" className="secondary icon-button" data-history="undo" onClick={undo} disabled={!can.undo} aria-keyshortcuts="Control+Z Meta+Z">
              Undo
            </button>
          )}
          {!narrow && can.redo && (
            <button type="button" className="secondary icon-button" data-history="redo" onClick={redo} aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y">
              Redo
            </button>
          )}
          {/* The how-to, behind Info (it was "More tips" under the tools). */}
          <button type="button" className="secondary icon-button tips-toggle" aria-expanded={tips} aria-controls={tipsId} onClick={() => setTips(!tips)}>
            <Icon name="info" />
            <span>Info</span>
          </button>
        </div>
      </div>
      {reverseHint && <p className="hint" id="reverse-hint">{reverseHint}</p>}
      <span id="swap-hint" hidden>
        Reverses the points: the end becomes the start.
      </span>
      <div id={tipsId} className="tips-body more-tips" hidden={!tips}>
        <p className="hint">Bike routes for the DC region and Baltimore. No sign-in needed.</p>
        {/* The start-up how-to before any point; with points, how to change them (the correctness review's N5). */}
        {points.length > 0 ? <p className="hint">{editingTips(accessMode)}</p> : <p className="hint">{emptyPlanHint(preset, loopVias, accessMode)}</p>}
        {coverageShown && <p className="hint">Gray areas are outside what RouteMaker covers.</p>}
        <p className="hint">{infoHelp(accessMode)}</p>
        <p className="hint">{ACCESS_HELP}</p>
        <button type="button" className="link access-toggle" aria-pressed={accessMode} onClick={() => toggleAccessMode(false)}>
          {ACCESS_LABEL}
        </button>
        <InstallOffer idBase="tips-install" compact onSay={announce} />
      </div>
      {loop && (
        // Shown while the box is checked (what a loop needs next); read as its description either way.
        <p className="hint loop-hint" id={loopHintId} hidden={!loop.checked}>
          {loop.hint}
        </p>
      )}
      {PLANNER_EXTRAS.zoomNotice && <PlannerZoomNotice zoom={zoom} shown={stressVisible && stress === "available"} />}
      {PLANNER_EXTRAS.highContrastShortcut && (
        <HighContrastShortcut on={accessibilityOn()} paletteFromAddress={paletteSetByAddress()} onChange={(on) => setAccessibility(on)} />
      )}
      {/* Plan streamline (Stephen 2026-10-17): From, the points, To, and Add a stop with Best order beside it, each box
          with one job, in place of one search box and its Start / Destination / Stop choice. The boxes stay open with
          a route shown, so more stops can be added by search (Stephen 2026-10-14). */}
      <PointBoxes
        pointsSearchRef={pointsSearchRef}
        points={points}
        loopVias={loopVias}
        geoGate={geoGate}
        searchBias={searchBias}
        pickPlace={pickPlace}
        locateReady={locateReady}
        locating={locating}
        locateNote={hereInPlan && here ? approximateHint(here.accuracyM) : ""}
        useMyLocation={useMyLocation}
        accessMode={accessMode}
        namer={namer}
        located={located}
        removeAt={removeAt}
        reorderPoint={reorderPoint}
        pointWarnings={pointWarnings}
        removeRefs={removeRefs}
        orderShown={orderShown}
        bestOrder={bestOrder}
        orderFocused={orderFocused}
        ordering={ordering}
      />
      {points.length === 1 && <p className="hint">{loneStartHint(preset, loopVias, accessMode)}</p>}
      {usesBikeshare(preset) && (
        <p className="hint">
          Bikeshare plans, Rebalance Rides too, take a start and an end only: the stations and the walks are chosen for you, unless you choose a
          station under Route. Remove any stops to plan one.
        </p>
      )}
      {/* Mass Ride planning covers DC only for now (OWNER-DECISIONS 418), in words beside the gray map. */}
      {isMassRide(preset) && <p className="hint mass-dc-only">{MASS_DC_ONLY}</p>}
      {federalPlanner}
      <div id="points-edit" ref={pointsEditRef} hidden={compactPoints}>
        {/* The two map-center actions (add a point, the road panel) are in Map tools, by the map's
            zoom buttons (OWNER-DECISIONS 450; MapTools.tsx). */}
        {/* The map-center tools are in Map tools (MapTools.tsx); Undo and Redo sit beside Points (Plan streamline). */}
      </div>
      {/* Always rendered, empty when there is no notice: a live region that is created already holding
          its text is often not spoken (VoiceOver with Safari, NVDA with Firefox). */}
      <p className={notice ? "notice" : "notice notice-empty"} role={noticeLive ? "status" : undefined}>
        {notice ?? ""}
      </p>
    </section>
  );
}

type PointBoxesProps = Pick<
  PointsSectionProps,
  | "pointsSearchRef"
  | "points"
  | "loopVias"
  | "geoGate"
  | "searchBias"
  | "pickPlace"
  | "locateReady"
  | "locating"
  | "useMyLocation"
  | "accessMode"
  | "namer"
  | "located"
  | "removeAt"
  | "reorderPoint"
  | "pointWarnings"
  | "removeRefs"
  | "orderShown"
  | "bestOrder"
  | "orderFocused"
  | "ordering"
> & {
  /** What "Use my location" adds under its button once a point is the rider's location (approximate), or "". */
  locateNote: string;
};

/**
 * Plan's points as a form (Plan streamline, Stephen 2026-10-17): From, the points (each start and destination with
 * Change), To, and Add a stop with Best order beside it; each box has one job, in place of one search box and its
 * Start / Destination / Stop choice. It keeps which point a Change opened a box for; App keeps the plan.
 */
function PointBoxes(props: PointBoxesProps) {
  const { pointsSearchRef, points, loopVias, geoGate, searchBias, pickPlace, locateReady, locating, locateNote, useMyLocation, accessMode, namer, located, removeAt, reorderPoint, pointWarnings, removeRefs, orderShown, bestOrder, orderFocused, ordering } = props;
  // Each stop's grip (lib/pointMover.ts): drag, the arrows, or a press for Up and Down. Only the stops move, as with
  // Best order: the start and the end stay, and a via point goes with the stop it leads to (App.tsx reorderPoint).
  const slots = namePoints(points, VIA_MARKS.isVia, loopVias).flatMap((n, i) => (n.role === "stop" ? [i] : []));
  const mover = usePointMover(slots, (from, to, by) => reorderPoint(slots[from], slots[to], by), points);
  // A point that is the rider's location is named so, as Go's route card names it, not by its coordinates.
  const names = {
    name: (point: LonLat) => (located.includes(point) ? { name: YOUR_LOCATION, label: YOUR_LOCATION } : namer.name(point)),
  };
  // The point a "Change" opened a box for (the start or the destination), until a pick, Escape or a removal.
  const [changing, setChanging] = useState<"from" | "to" | null>(null);
  const boxRefs = { from: useRef<HTMLInputElement | null>(null), to: useRef<HTMLInputElement | null>(null), add: useRef<HTMLInputElement | null>(null) };
  useEffect(() => {
    if (changing) boxRefs[changing].current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the refs are stable
  }, [changing]);
  // A pick puts its box away (From once there is a start, To once there is a destination): the focus goes on to the
  // next box shown, as a form's does, so a keyboard or screen reader is not left on the page.
  const afterPick = useRef<"from" | "to" | "add" | null>(null);
  const hasEnd = !loopVias && points.length >= 2;
  useEffect(() => {
    // The point being changed went (Remove, Undo, Clear): its box goes with it.
    if ((changing === "from" && points.length === 0) || (changing === "to" && !hasEnd)) setChanging(null);
  }, [changing, points.length, hasEnd]);
  const showFrom = points.length === 0 || changing === "from";
  const showTo = !showFrom && !loopVias && (points.length === 1 || changing === "to");
  const showAdd = !showFrom && !showTo && (loopVias ? points.length >= 1 : points.length >= 2);
  useEffect(() => {
    const from = afterPick.current;
    if (from === null) return;
    afterPick.current = null;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    const next = showTo ? boxRefs.to : showAdd ? boxRefs.add : showFrom ? boxRefs.from : null;
    next?.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per pick, after the plan it made
  }, [points]);
  const full = points.length >= MAX_POINTS;
  const placeName = (index: number) => (points[index] ? (names.name(points[index])?.name ?? "a point on the map") : undefined);
  const search = (variant: "from" | "to" | "add") => (
    <PlaceSearch
      key={variant}
      variant={variant}
      pointCount={points.length}
      loop={loopVias}
      full={full}
      gate={geoGate}
      bias={searchBias}
      current={variant === "from" && changing === "from" ? placeName(0) : variant === "to" && changing === "to" ? placeName(points.length - 1) : undefined}
      inputRef={boxRefs[variant]}
      onDismiss={
        variant === changing
          ? () => {
              // Escape on the empty box puts it away; the focus goes back to that point's row (its Remove).
              const index = variant === "from" ? 0 : points.length - 1;
              setChanging(null);
              window.setTimeout(() => removeRefs.current[index]?.focus(), 0);
            }
          : undefined
      }
      onPick={(place, choice) => {
        setChanging(null);
        afterPick.current = variant;
        pickPlace(place, choice);
      }}
      // "Use my location" beside the first box a plan needs (From, then To); Add a stop has "Your location" in its list.
      locate={{
        support: locateReady,
        busy: locating,
        note: locateNote,
        listOnly: variant === "add",
        onLocate: (choice) => {
          setChanging(null);
          afterPick.current = variant;
          void useMyLocation(choice);
        },
      }}
    />
  );
  // A Change opens its box in that point's row (edit-route redesign, Stephen 2026-10-18), not above the list.
  const editing = changing === "from" && points.length > 0 ? 0 : changing === "to" && hasEnd ? points.length - 1 : null;
  return (
    <div id="points-search" ref={pointsSearchRef} className="points-controls plan-points">
      {showFrom && editing === null && search("from")}
      {points.length === 0 ? (
        <p className="hint">{searchLede(loopVias, accessMode)}</p>
      ) : (
        <PointsList
          rows={pointRows(points, names, loopVias, VIA_MARKS.isVia)}
          onRemove={removeAt}
          warnings={pointWarnings}
          mover={mover}
          slots={slots}
          removeRef={(index, button) => {
            removeRefs.current[index] = button;
          }}
          // A second press puts the box away again (as Escape in the empty box does).
          onChange={(index) => setChanging((now) => (now === (index === 0 ? "from" : "to") ? null : index === 0 ? "from" : "to"))}
          changeable={(index) => index === 0 || (!loopVias && index === points.length - 1 && points.length >= 2)}
          editor={
            editing === null
              ? null
              : {
                  index: editing,
                  node: (
                    <div className="point-editor">
                      {search(changing === "from" ? "from" : "to")}
                      {/* The way out on a touch screen (Escape on a keyboard): the row's place and Remove come back. */}
                      <button
                        type="button"
                        className="link point-cancel"
                        onClick={() => {
                          setChanging(null);
                          window.setTimeout(() => removeRefs.current[editing]?.focus(), 0);
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  ),
                }
          }
        />
      )}
      {showTo && editing === null && search("to")}
      {showAdd && (
        <div className="add-stop-row">
          {/* A full plan: the reason in place of the box, whose pick could add nothing (Best order still works). */}
          {full ? <p className="hint">The route has as many points as it can take, so no stop can be added.</p> : search("add")}
          {/* Best order (OWNER-DECISIONS 449), beside Add a stop (Stephen 2026-10-17), with two or more stops to order;
              aria-disabled while the order is found (the focus stays on it, a press says it is still working),
              with the same label, so the row does not reflow under a finger. */}
          {orderShown && (
            <button
              type="button"
              className="secondary best-order"
              onClick={() => void bestOrder()}
              onFocus={() => (orderFocused.current = true)}
              onBlur={(event) => {
                // Only a move to another element clears the mark: a blur from the button's own removal
                // has none, so App's effect moves the focus (and only if it is on nothing).
                if (event.relatedTarget) orderFocused.current = false;
              }}
              aria-disabled={ordering ? true : undefined}
            >
              {BEST_ORDER_LABEL}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export interface RideSectionProps {
  preset: PresetId;
  dials: Dials;
  choosePreset: (id: PresetId, next: Dials) => void;
  commitDials: (next: Dials) => void;
  weight: StoredWeight | null;
  weightRemembered: boolean;
  weightStore: RefObject<WeightStore | null>;
  setWeightRemembered: Dispatch<SetStateAction<boolean>>;
  setWeight: Dispatch<SetStateAction<StoredWeight | null>>;
  /** The route shown (its resolved "now"), or null. */
  route: RouteResponse | null;
  /** Plan: the ride type's own button, first. Go's Ride sheet lists the ride types itself (RideGroupChips). */
  typeCard: boolean;
}

/**
 * The ride type's button, which opens the ride types at once, and the Ride settings line, which opens every dial
 * (OWNER-DECISIONS 312; edit-route redesign, Stephen 2026-10-18: one press to the ride types, not Edit then Change).
 */
export function RideSection(props: RideSectionProps) {
  const { preset, dials, choosePreset, commitDials, weight, weightRemembered, weightStore, setWeightRemembered, setWeight, route, typeCard } = props;
  const presetsSection = typeCard ? <RideTypePicker key="presets" preset={preset} dials={dials} onChoose={choosePreset} /> : null;
  return (
    <RideSettings key="presets" summary={settingsSummary(preset, dials)} spoken={settingsSummarySpoken(preset, dials)} typeCard={presetsSection}>
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
  );
}
