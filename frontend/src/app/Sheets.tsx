// Moved out of App.tsx unchanged (UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"): the same
// elements, in the same order, with App's state and handlers passed in under the names App gives them,
// so the DOM, the focus and every announcement are as they were. App.tsx keeps the state and the effects.
import type { Dispatch, RefObject, SetStateAction } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { StressAvailability } from "../MapView.tsx";
import { SuggestionReview } from "../SuggestionReview.tsx";
import type { RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import type { PresetId } from "../lib/presets.ts";
import { isPlainClick, rememberPlanForSignIn, tabSession } from "../lib/signIn.ts";
import { pointName } from "../lib/summary.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, setMtbTrails } from "../stressStyle.js";
import { HighStressLanesSwitch } from "../lib/highStressLanesSwitch.ts";
import { MtbTrailsSwitch } from "../lib/mtbTrailsSwitch.ts";
import { AccessibilitySwitch } from "../lib/accessibilitySwitch.ts";
import { RideSettingsFields } from "../RideMode.tsx";
import type { RidePrefs } from "../lib/rideOutput.ts";
import type { RailVisibility } from "../lib/railStations.ts";
import { RailStationsSection } from "../RailStations.tsx";
import { RAIL_STATIONS } from "../lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "../lib/federalLand.ts";
import { FederalLandFor, type FederalStatus } from "../lib/federalLegend.ts";
import { CAPACITY_LEGEND_TITLE, isMassRide } from "../lib/massCapacity.ts";
import { MassLegend, MassZoomNotes } from "../lib/massLegend.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { MtbTrailLegend, StressLegend } from "../lib/stressLegend.ts";
import { refreshStressTiles } from "../lib/mapStyle.ts";
import { GpxPanel } from "../GpxPanel.tsx";
import { JunctionLegend, SheetFrame } from "../Sidebar.tsx";
import { MASS_RIDE_LAYERS_NOTE, SHEET_TITLES, type PanelView } from "../lib/sidebar.ts";
import type { ImportedPlan } from "../lib/gpxPlan.ts";
import type { WaterAlong, WaterPrefs, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterSection } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbsStatus } from "../lib/climbs.ts";
import { ClimbsLayerControls } from "../lib/climbsLegend.ts";
import { InstallOffer, KeptRoutes } from "../InstallableApp.tsx";
import type { KeptRoute } from "../lib/offlineRoutes.ts";
import { anyKept } from "../lib/offlineRouteStore.ts";
import { HAZARD_REVIEW } from "../lib/reviewSources.ts";
import type { Status } from "./RoutePanel.tsx";

export interface LayersSheetProps {
  view: PanelView;
  backToPlanner: () => void;
  layersHeadingRef: RefObject<HTMLHeadingElement | null>;
  massMap: boolean;
  stress: StressAvailability;
  stressVisible: boolean;
  setStressVisible: (on: boolean) => void;
  showHighLanes: boolean;
  preset: PresetId;
  federalOn: boolean;
  setFederalOn: (on: boolean) => void;
  federalStatus: FederalStatus;
  federalData: FederalData | null;
  points: LonLat[];
  waterPrefs: WaterPrefs;
  changeWaterPrefs: (next: WaterPrefs) => void;
  waterStatus: WaterStatus;
  waterAlong: WaterAlong[] | null;
  /** The Climbs layer (lib/climbs.ts): the switch, its data's status and the climbs the route rides. */
  climbsOn: boolean;
  changeClimbsOn: (on: boolean) => void;
  climbsStatus: ClimbsStatus;
  climbsAlong: ClimbAlong[] | null;
  addWaterStop: (item: WaterAlong) => void;
  rail: RailVisibility;
  setRail: (next: RailVisibility) => void;
  showMtbTrails: boolean;
  legendHeadingRef: RefObject<HTMLHeadingElement | null>;
  zoom: number | null;
  facilitiesShown: ReadonlySet<string>;
}

/** The bottom bar's Map layers sheet (Legend opens it at its legend). */
export function LayersSheet(props: LayersSheetProps) {
  const { view, backToPlanner, layersHeadingRef, massMap, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn, setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus, waterAlong, addWaterStop, rail, setRail, showMtbTrails, legendHeadingRef, zoom, facilitiesShown, climbsOn, changeClimbsOn, climbsStatus, climbsAlong } = props;
  return (
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
          join the mountain-bike trails and climbs here once their data is built (docs/MTB-TOPO-PLAN.md). */}
      <section aria-labelledby="terrain-heading">
        <h3 id="terrain-heading">Trails and terrain</h3>
        <MtbTrailsSwitch on={showMtbTrails} onChange={(on) => setMtbTrails(on)} overlay={stress === "available"} />
        <ClimbsLayerControls on={climbsOn} onChange={changeClimbsOn} status={climbsStatus} items={climbsAlong} />
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
  );
}

export interface GpxSheetProps {
  view: PanelView;
  backToPlanner: () => void;
  gpxHeadingRef: RefObject<HTMLHeadingElement | null>;
  shown: RouteResponse | null;
  routedPoints: LonLat[];
  routedLoop: boolean;
  federalRoute: readonly string[];
  points: LonLat[];
  status: Status;
  imported: ImportedPlan | null;
  openImported: (plan: ImportedPlan) => void;
  refineImported: (next: LonLat[]) => void;
  getMap: () => MapLibreMap | null;
}

/** The bottom bar's GPX sheet. */
export function GpxSheet(props: GpxSheetProps) {
  const { view, backToPlanner, gpxHeadingRef, shown, routedPoints, routedLoop, federalRoute, points, status, imported, openImported, refineImported, getMap } = props;
  return (
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
        federal={federalRoute}
        points={points}
        planStatus={status.kind}
        imported={imported}
        onImport={openImported}
        onRefine={refineImported}
        getMap={getMap}
      />
    </SheetFrame>
  );
}

export interface SettingsSheetProps {
  view: PanelView;
  backToPlanner: () => void;
  settingsHeadingRef: RefObject<HTMLHeadingElement | null>;
  ridePrefs: RidePrefs;
  changeRidePrefs: (next: RidePrefs) => void;
  keepShown: boolean;
  keptVersion: number;
  openKept: (kept: KeptRoute) => void;
  announce: (text: string) => void;
  linkNote: string;
  mapRef: RefObject<MapLibreMap | null>;
  setHazardsAsked: Dispatch<SetStateAction<number>>;
}

/** The bottom bar's Settings sheet. */
export function SettingsSheet(props: SettingsSheetProps) {
  const { view, backToPlanner, settingsHeadingRef, ridePrefs, changeRidePrefs, keepShown, keptVersion, openKept, announce, linkNote, mapRef, setHazardsAsked } = props;
  return (
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
      {/* The installable app (WEB-NAV-plan.md section 8, P3 and P4): the routes kept on this device, and the install offer. */}
      {(keepShown || anyKept()) && <KeptRoutes version={keptVersion} onOpen={openKept} onSay={announce} />}
      <InstallOffer idBase="settings-install" onSay={announce} />
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
      {/* An instance admin's review of rider suggestions (OWNER-DECISIONS 460.5); nothing for anyone else. */}
      <SuggestionReview
        onStressChanged={(generation) => {
          const map = mapRef.current;
          if (map) refreshStressTiles(map, window.location.origin, generation);
        }}
      />
      {/* The same review for riders' Mass Ride hazard reports (FOLLOWUP-MASSRIDE-MAP part 3). */}
      <SuggestionReview source={HAZARD_REVIEW} onApproved={() => setHazardsAsked((n) => n + 1)} />
    </SheetFrame>
  );
}
