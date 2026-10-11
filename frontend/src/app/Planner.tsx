// Moved out of App.tsx unchanged (UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"): the same
// elements, in the same order, with App's state and handlers passed in under the names App gives them,
// so the DOM, the focus and every announcement are as they were. App.tsx keeps the state and the effects.
import type { Dispatch, ReactNode, RefObject, SetStateAction } from "react";
import type { StressAvailability } from "../MapView.tsx";
import { ACCESS_HELP, ACCESS_LABEL } from "../lib/accessMode.ts";
import { infoHelp } from "../lib/roadInfo.ts";
import type { RouteResponse } from "../lib/api.ts";
import { MAX_POINTS, type LonLat } from "../lib/geo.ts";
import type { PresetId } from "../lib/presets.ts";
import { accessibilityOn, paletteSetByAddress, setAccessibility } from "../stressStyle.js";
import { DialsPanel } from "../DialsPanel.tsx";
import { withLoop, type LoopView } from "../lib/loop.ts";
import { BEST_ORDER_LABEL } from "../lib/stopOrder.ts";
import { editingTips, emptyPlanHint, loneStartHint } from "../lib/pointText.ts";
import { NearbyStations } from "../NearbyStations.tsx";
import type { NearbyStation, Pins, StationAction } from "../lib/stations.ts";
import { RideTypePicker } from "../RideTypePicker.tsx";
import type { Dials } from "../lib/dials.ts";
import type { StoredWeight, WeightStore } from "../lib/weight.ts";
import { isMassRide } from "../lib/massCapacity.ts";
import { MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { PointsList } from "../lib/pointsList.ts";
import { PlaceSearch } from "../PlaceSearch.tsx";
import { approximateHint, type Fix, type locateSupport } from "../lib/geolocation.ts";
import type { usePlaceNames } from "../usePlaceNames.ts";
import { pointRows, type Place, type PlaceChoice } from "../lib/geocode.ts";
import { HighContrastShortcut, MoreTips, PlannerZoomNotice, RideSettings } from "../Sidebar.tsx";
import { PLANNER_EXTRAS, searchLede } from "../lib/sidebar.ts";
import { rideSummary, rideSummarySpoken } from "../lib/rideSummary.ts";
import type { Found, Nearby, NearestFrom, NearestKind } from "../lib/nearest.ts";
import { NearestFinder } from "../lib/nearestFinder.ts";
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
  removeAt: (index: number) => void;
  pointWarnings: (string | null)[];
  removeRefs: RefObject<Array<HTMLButtonElement | null>>;
  preset: PresetId;
  stationChoice: Pins;
  chooseStation: (action: StationAction, station: NearbyStation | null, point: LonLat) => void;
  routeShownForPoints: boolean;
  editPointsRef: RefObject<HTMLButtonElement | null>;
  setEditPoints: Dispatch<SetStateAction<boolean>>;
  /** Mass Ride's "no point is on federal land" line, or nothing. */
  federalPlanner: ReactNode;
  /** The Find food panel (lib/foodFinder.ts), beside the nearest finder. */
  foodFinder: ReactNode;
  nearestFrom: NearestFrom;
  nearestFromOptions: NearestFrom[];
  setNearestFrom: (from: NearestFrom) => void;
  findNearest: (kind: NearestKind) => Promise<void>;
  nearestBusy: boolean;
  nearestStatus: string;
  nearestList: Found | null;
  rideToNearest: (item: Nearby) => void;
  addNearestStop: (item: Nearby) => void;
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
  clearAll: () => void;
  coverageShown: boolean;
  toggleAccessMode: (focusTools: boolean) => void;
  announce: (text: string) => void;
  notice: string | null;
}

/** The planner's Points section: the search, the loop toggle, the points, the nearest finder and the point tools. */
export function PointsSection(props: PointsSectionProps) {
  const { pointsHeadingRef, zoom, stressVisible, stress, pointsSearchRef, compactPoints, points, loopVias, geoGate, searchBias, pickPlace, locateReady, locating, hereInPlan, here, useMyLocation, loop, loopHintId, commitDials, dials, accessMode, namer, removeAt, pointWarnings, removeRefs, preset, stationChoice, chooseStation, routeShownForPoints, editPointsRef, setEditPoints, federalPlanner, foodFinder, nearestFrom, nearestFromOptions, setNearestFrom, findNearest, nearestBusy, nearestStatus, nearestList, rideToNearest, addNearestStop, pointsEditRef, reverseButton, reverse, reverseHint, orderShown, bestOrder, orderFocused, ordering, narrow, undo, can, redo, clearAll, coverageShown, toggleAccessMode, announce, notice } = props;
  return (
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
          warnings={pointWarnings}
          removeRef={(index, button) => {
            removeRefs.current[index] = button;
          }}
        />
      )}
      {points.length === 1 && <p className="hint">{loneStartHint(preset, loopVias, accessMode)}</p>}
      {preset === "bikeshare" && (
        <p className="hint">
          Bikeshare plans take a start and an end only: the docks and the walks are chosen for you, unless you choose a station below. Remove any stops
          to plan one.
        </p>
      )}
      {preset === "bikeshare" && <NearbyStations points={points} pins={stationChoice} onChoose={chooseStation} />}
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
      {foodFinder}
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
        <InstallOffer idBase="tips-install" compact onSay={announce} />
      </MoreTips>
      </div>
      {/* Always rendered, empty when there is no notice: a live region that is created already holding
          its text is often not spoken (VoiceOver with Safari, NVDA with Firefox). */}
      <p className={notice ? "notice" : "notice notice-empty"} role="status">
        {notice ?? ""}
      </p>
    </section>
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
}

/** The Ride line and, behind its Edit, the ride type and every dial (OWNER-DECISIONS 312). */
export function RideSection(props: RideSectionProps) {
  const { preset, dials, choosePreset, commitDials, weight, weightRemembered, weightStore, setWeightRemembered, setWeight, route } = props;
  const presetsSection = <RideTypePicker key="presets" preset={preset} dials={dials} onChoose={choosePreset} />;
  return (
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
  );
}
