// The panel's sheets (moved out of App.tsx in UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"),
// arranged as the approved UI mockup of 2026-10-11 has them (reports/v0.5.0/ui-mockup.html): Layers is its
// switches, with the legend behind a Legend button at its top (the owner's choice 6); Suggest is the one way
// in to the suggest tools, and Review is an admin's; Settings is Display, Ride mode, This device and Account
// with My Go; and the map's Water and Food chips open the nearest finder and Find food. In Go, Settings is
// the Menu, with Plan, Suggest, GPX and Review above it. App.tsx keeps the state and the effects.
import { useEffect, useState, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { StressAvailability } from "../MapView.tsx";
import { SuggestionReview } from "../SuggestionReview.tsx";
import type { RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { PRESETS, presetLabel, type PresetId } from "../lib/presets.ts";
import { filterRideGroups, rideTypeCount, RideTypeSearch } from "../lib/rideTypeGroups.ts";
import { isPlainClick, rememberPlanForSignIn, tabSession } from "../lib/signIn.ts";
import { pointName } from "../lib/summary.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, setMtbTrails } from "../stressStyle.js";
import { HighStressLanesSwitch } from "../lib/highStressLanesSwitch.ts";
import { MTB_TRAILS_LABEL, MtbTrailsSwitch } from "../lib/mtbTrailsSwitch.ts";
import { setTopoLines, TOPO_LINES_LABEL, TopoLinesSwitch } from "../lib/topoLines.ts";
import { LayerSection } from "../lib/layerSection.ts";
import { AccessibilitySwitch } from "../lib/accessibilitySwitch.ts";
import { ACCESS_HELP, ACCESS_LABEL } from "../lib/accessMode.ts";
import { RideSettingsFields } from "../RideMode.tsx";
import type { RidePrefs } from "../lib/rideOutput.ts";
import type { RailVisibility } from "../lib/railStations.ts";
import { RailStationsLegend, RailStationsSection } from "../RailStations.tsx";
import { RAIL_STATIONS } from "../lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "../lib/federalLand.ts";
import { FederalLandFor, FederalLegendNotes, type FederalStatus } from "../lib/federalLegend.ts";
import { CAPACITY_LEGEND_TITLE, isMassRide } from "../lib/massCapacity.ts";
import { MassLegend, MassZoomNotes } from "../lib/massLegend.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { MtbTrailLegend, StressLegend } from "../lib/stressLegend.ts";
import { refreshStressTiles } from "../lib/mapStyle.ts";
import { GpxPanel } from "../GpxPanel.tsx";
import { JunctionLegend, SheetFrame } from "../Sidebar.tsx";
import { MASS_RIDE_LAYERS_NOTE, MENU_TITLE, SHEET_TITLES, STRESS_CHECKING, STRESS_UNAVAILABLE, type PanelView } from "../lib/sidebar.ts";
import type { ImportedPlan } from "../lib/gpxPlan.ts";
import type { WaterAlong, WaterPrefs, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterLegend, WaterLegendNotes, WaterSection } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbsStatus } from "../lib/climbs.ts";
import { CLIMBS_HELP, CLIMBS_LABEL, ClimbsLayerControls, ClimbsLegend, climbsStatusText } from "../lib/climbsLegend.ts";
import { InstallOffer, KeptRoutes } from "../InstallableApp.tsx";
import type { KeptRoute } from "../lib/offlineRoutes.ts";
import { anyKept } from "../lib/offlineRouteStore.ts";
import { HAZARD_REVIEW } from "../lib/reviewSources.ts";
import { DC_311_ONLINE, REPORT_KINDS } from "../lib/report311.ts";
import { OPEN_IN_HINT, OPEN_IN_LABEL, type AppMode, type OpenIn } from "../lib/appMode.ts";
import { HOME_SIGN_IN, myGoSummary, type MyGo } from "../lib/myGo.ts";
import type { GeoGate, Place } from "../lib/geocode.ts";
import type { IconName } from "../lib/iconPaths.ts";
import { PlaceSearch } from "../PlaceSearch.tsx";
import { Icon } from "../Icon.tsx";
import { ANNOUNCE_HINT, ANNOUNCE_LABEL, type AnnounceLevel } from "../lib/announceLevel.ts";
import type { Status } from "./RoutePanel.tsx";

/** How the sheets go back: to the planner, or to the sheet that opened them (Layers for Legend, Suggest for Review). */
export interface SheetNav {
  view: PanelView;
  back: () => void;
  /** The words of each sheet's Back button. */
  backLabel: (view: PanelView) => string;
}

export interface LayersSheetProps {
  nav: SheetNav;
  /** Opens the legend (a sheet of its own, back to Layers). */
  openLegend: (opener: HTMLElement) => void;
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
  showTopoLines: boolean;
  topoReady: boolean;
}

/** The Layers sheet: the map's switches, in the mockup's order, with the Legend button at its top. */
export function LayersSheet(props: LayersSheetProps) {
  const { nav, openLegend, massMap, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn, setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus, rail, setRail, showMtbTrails, showTopoLines, topoReady, climbsOn, changeClimbsOn, climbsStatus, climbsAlong } = props;
  return (
    <SheetFrame
      id="sheet-layers"
      title={SHEET_TITLES.layers}
      open={nav.view === "layers"}
      onBack={nav.back}
      backLabel={nav.backLabel("layers")}
      extra={
        <button type="button" className="link icon-button legend-button" onClick={(event) => openLegend(event.currentTarget)}>
          <Icon name="info" />
          <span>Legend</span>
        </button>
      }
    >
      {/* The mockup's order: the stress map, lanes on busy roads, federal land (Mass Ride's alone), water and
          restrooms, Metro and MARC, then trails and terrain. High contrast is in Settings. Each section is one
          row, its name, one switch for the whole section and a disclosure; its layers are inside (lib/layerSection.ts). */}
      <LayerSection
        id="stress"
        title={massMap ? CAPACITY_LEGEND_TITLE : "Traffic stress"}
        headingId="layers-heading"
        switchId="show-stress"
        layers={stress === "available" ? [{ key: "stress", label: massMap ? CAPACITY_LEGEND_TITLE : "Traffic stress", on: stressVisible }] : []}
        onLayers={(next) => setStressVisible(next.stress)}
        status={stress === "checking" ? STRESS_CHECKING : stress === "unavailable" ? STRESS_UNAVAILABLE : ""}
      >
        {/* Not one of the section's layers: shown with or without the stress map, as it also changes the
            route's facility totals and description (the a11y review's SF4). */}
        <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} massMap={massMap} />
      </LayerSection>

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

      {/* The switch and its two filters; the list along the route is the route's fold, the legend and help behind Legend. */}
      <WaterSection prefs={waterPrefs} onChange={changeWaterPrefs} status={waterStatus} />

      {RAIL_STATIONS.length > 0 && <RailStationsSection visibility={rail} onChange={setRail} />}

      {/* OWNER-DECISIONS 454's optional layers, off until turned on, in every ride type. A layer's extra
          control (the Climbs layer's "Show climbs from") sits under its own switch, inside the section. */}
      <LayerSection
        id="terrain"
        title="Trails and terrain"
        headingId="terrain-heading"
        layers={[
          { key: "mtb", label: MTB_TRAILS_LABEL, on: showMtbTrails },
          { key: "climbs", label: CLIMBS_LABEL, on: climbsOn },
          { key: "topo", label: TOPO_LINES_LABEL, on: showTopoLines },
        ]}
        onLayers={(next) => {
          if (next.mtb !== showMtbTrails) setMtbTrails(next.mtb);
          if (next.climbs !== climbsOn) changeClimbsOn(next.climbs);
          if (next.topo !== showTopoLines) setTopoLines(next.topo);
        }}
        // The climbs' own status line is inside; closed, the section says it.
        status={(open) => (open ? "" : climbsStatusText(climbsOn, climbsStatus))}
      >
        <MtbTrailsSwitch on={showMtbTrails} onChange={(on) => setMtbTrails(on)} overlay={stress === "available"} />
        <ClimbsLayerControls on={climbsOn} onChange={changeClimbsOn} status={climbsStatus} items={climbsAlong} along={false} legend={false} />
        <TopoLinesSwitch on={showTopoLines} onChange={(on) => setTopoLines(on)} available={topoReady} />
      </LayerSection>

      {/* Mockup v3's line; the Mass Ride layers sheet itself waits on FOLLOWUP-MASSRIDE-MAP (324-334). */}
      {!federalShown(preset, true) && <p className="hint mass-ride-layers">{MASS_RIDE_LAYERS_NOTE}</p>}
    </SheetFrame>
  );
}

export interface LegendSheetProps {
  nav: SheetNav;
  legendHeadingRef: RefObject<HTMLHeadingElement | null>;
  massMap: boolean;
  stress: StressAvailability;
  stressVisible: boolean;
  preset: PresetId;
  zoom: number | null;
  facilitiesShown: ReadonlySet<string>;
  waterPrefs: WaterPrefs;
  waterStatus: WaterStatus;
  climbsOn: boolean;
  climbsStatus: ClimbsStatus;
  federalOn: boolean;
  federalStatus: FederalStatus;
  rail: RailVisibility;
}

/** The legend, behind Layers' Legend button (the owner's choice 6): what each zoom shows and how stress ratings work. */
export function LegendSheet(props: LegendSheetProps) {
  const { nav, legendHeadingRef, massMap, stress, stressVisible, preset, zoom, facilitiesShown, waterPrefs, waterStatus, climbsOn, climbsStatus, federalOn, federalStatus, rail } = props;
  return (
    <SheetFrame id="sheet-legend" title={SHEET_TITLES.legend} open={nav.view === "legend"} onBack={nav.back} backLabel={nav.backLabel("legend")} headingRef={legendHeadingRef}>
      <section aria-labelledby="sheet-legend-title" className="legend-body">
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
        {/* Moved from Layers (the owner, 2026-10-12: "less wordy"): each layer's how-it-works, by its legend. */}
        <FederalLegendNotes preset={preset} on={federalOn} status={federalStatus} />
        {waterPrefs.on && waterStatus === "ready" && <WaterLegend prefs={waterPrefs} />}
        {waterPrefs.on && <WaterLegendNotes prefs={waterPrefs} />}
        {RAIL_STATIONS.length > 0 && (rail.metro || rail.marc) && <RailStationsLegend />}
        {climbsOn && climbsStatus === "ready" && <ClimbsLegend />}
        {climbsOn && <p className="hint climbs-help">{CLIMBS_HELP}</p>}
      </section>
    </SheetFrame>
  );
}

export interface GpxSheetProps {
  nav: SheetNav;
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

/** The GPX sheet. */
export function GpxSheet(props: GpxSheetProps) {
  const { nav, shown, routedPoints, routedLoop, federalRoute, points, status, imported, openImported, refineImported, getMap } = props;
  return (
    <SheetFrame id="sheet-gpx" title={SHEET_TITLES.gpx} open={nav.view === "gpx"} onBack={nav.back} backLabel={nav.backLabel("gpx")}>
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

export interface MyGoControls {
  myGo: MyGo;
  signedIn: boolean;
  /** Saves the whole of My Go (to the account signed in, else this device). */
  save: (next: MyGo) => void;
  /** What the last save said, politely. */
  said: string;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
}

/** "Open in": By screen size, Go or Plan, as a radio group. */
function OpenInChoice({ value, onChange, idBase, hint }: { value: OpenIn; onChange: (next: OpenIn) => void; idBase: string; hint?: string }) {
  return (
    <fieldset className="ride-choice open-in">
      <legend>Open in</legend>
      {(["", "go", "plan"] as OpenIn[]).map((option) => (
        <label key={option || "screen"} className="radio">
          <input type="radio" name={`${idBase}-open-in`} checked={value === option} onChange={() => onChange(option)} />
          {OPEN_IN_LABEL[option]}
        </label>
      ))}
      {hint && <p className="hint">{hint}</p>}
    </fieldset>
  );
}

/**
 * My Go (the owner's choice 2): where the app opens and Go's ride type, saved to the account when signed
 * in and on this device when not; signed in, the Home that Go's Home chip rides to.
 */
function MyGoSection({ controls }: { controls: MyGoControls }) {
  const { myGo, signedIn, save, said, geoGate, searchBias } = controls;
  return (
    <section aria-labelledby="settings-my-go-heading" className="my-go">
      <h4 id="settings-my-go-heading">
        <Icon name="star" size={18} />
        My Go
        <span className="setting-value">
          <span className="visually-hidden">: </span>
          {myGoSummary(myGo)}
        </span>
      </h4>
      <p className="hint">{signedIn ? "Kept with your Discord account, on every device you sign in on." : "Kept on this device. Sign in to keep it with your account, with a Home."}</p>
      <OpenInChoice value={myGo.openIn} onChange={(openIn) => save({ ...myGo, openIn })} idBase="my-go" hint={OPEN_IN_HINT} />
      <label className="select-setting">
        Go's ride type
        <select value={myGo.ride ?? "default"} onChange={(event) => save({ ...myGo, ride: event.target.value === "default" ? null : (event.target.value as PresetId) })}>
          {PRESETS.filter((p) => p.id !== "mass-ride").map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      {signedIn ? (
        <div className="my-go-home">
          <p>
            <strong>Home: </strong>
            {myGo.home ? myGo.home.label || "set" : "not set"}
          </p>
          <PlaceSearch variant="home" pointCount={0} full={false} gate={geoGate} bias={searchBias} onPick={(place: Place) => save({ ...myGo, home: { point: [place.lon, place.lat], label: place.name } })} />
          {myGo.home && (
            <button type="button" className="secondary" onClick={() => save({ ...myGo, home: null })}>
              Clear Home
            </button>
          )}
        </div>
      ) : (
        <p className="hint">{HOME_SIGN_IN}</p>
      )}
      <p className="hint my-go-said" role="status">
        {said}
      </p>
    </section>
  );
}

export interface SettingsSheetProps {
  nav: SheetNav;
  settingsHeadingRef: RefObject<HTMLHeadingElement | null>;
  ridePrefs: RidePrefs;
  changeRidePrefs: (next: RidePrefs) => void;
  keepShown: boolean;
  keptVersion: number;
  openKept: (kept: KeptRoute) => void;
  announce: (text: string) => void;
  linkNote: string;
  accessMode: boolean;
  toggleAccessMode: (focusTools: boolean) => void;
  myGo: MyGoControls;
  /** Announcements, Brief or Full (lib/announceLevel.ts): the level in force, and the rider's choice. */
  announcements: { level: AnnounceLevel; choose: (level: AnnounceLevel) => void };
  /** Go shows this sheet as its Menu: Plan, Suggest, GPX and (an admin's) Review above the settings. */
  mode: AppMode;
  menu: { onPlan: () => void; onSuggest: (opener: HTMLElement) => void; onGpx: (opener: HTMLElement) => void; onReview: ((opener: HTMLElement) => void) | null };
}

/** The Settings sheet (Go's Menu): Display, Ride mode, This device and Account, as the mockup groups them. */
export function SettingsSheet(props: SettingsSheetProps) {
  const { nav, settingsHeadingRef, ridePrefs, changeRidePrefs, keepShown, keptVersion, openKept, announce, linkNote, accessMode, toggleAccessMode, myGo, mode, menu, announcements } = props;
  const go = mode === "go";
  return (
    <SheetFrame
      id="sheet-settings"
      title={go ? MENU_TITLE : SHEET_TITLES.settings}
      open={nav.view === "settings"}
      onBack={nav.back}
      backLabel={nav.backLabel("settings")}
      headingRef={settingsHeadingRef}
    >
      {go && (
        <nav className="menu-pages" aria-label="Pages">
          <button type="button" className="secondary menu-page" onClick={menu.onPlan}>
            <Icon name="list" />
            Plan
          </button>
          <button type="button" className="secondary menu-page" onClick={(event) => menu.onSuggest(event.currentTarget)}>
            <Icon name="flag" />
            Suggest
          </button>
          <button type="button" className="secondary menu-page" onClick={(event) => menu.onGpx(event.currentTarget)}>
            <Icon name="file" />
            GPX
          </button>
          {menu.onReview && (
            <button type="button" className="secondary menu-page" onClick={(event) => menu.onReview?.(event.currentTarget)}>
              <Icon name="shield" />
              Review
            </button>
          )}
        </nav>
      )}
      <section aria-labelledby="settings-display-heading" className="settings-group">
        <h3 id="settings-display-heading">Display</h3>
        <AccessibilitySwitch
          idBase="settings-contrast"
          on={accessibilityOn()}
          source={accessibilitySource()}
          paletteFromAddress={paletteSetByAddress()}
          onChange={(on) => setAccessibility(on)}
        />
        {/* Accessibility mode (OWNER-DECISIONS 455) as a switch here too (the mockup), the same state as the page's first button. */}
        <div className="a11y-setting">
          <button
            type="button"
            role="switch"
            id="settings-access-switch"
            className="switch"
            aria-checked={accessMode}
            aria-labelledby="settings-access-label"
            aria-describedby="settings-access-hint"
            onClick={() => toggleAccessMode(false)}
          >
            <span id="settings-access-label" className="switch-label">
              {ACCESS_LABEL}
            </span>
            <span className="switch-state" aria-hidden="true">
              {accessMode ? "On" : "Off"}
            </span>
          </button>
          <p className="hint" id="settings-access-hint">
            {ACCESS_HELP}
          </p>
        </div>
        {/* How much screen readers are told (the owner, 2026-10-11 20:23 UTC): Brief or Full; unset, Go is brief. */}
        <fieldset className="ride-choice announce-level">
          <legend>Announcements</legend>
          {(["brief", "full"] as const).map((level) => (
            <label key={level} className="radio">
              <input type="radio" name="settings-announce" checked={announcements.level === level} onChange={() => announcements.choose(level)} />
              {ANNOUNCE_LABEL[level]}
            </label>
          ))}
          <p className="hint">{ANNOUNCE_HINT}</p>
        </fieldset>
        {/* Open in Go or Plan: this device's, signed out; signed in it is My Go's, under Account. */}
        {!myGo.signedIn && (
          <OpenInChoice value={myGo.myGo.openIn} onChange={(openIn) => myGo.save({ ...myGo.myGo, openIn })} idBase="display" hint={`${OPEN_IN_HINT} Kept on this device.`} />
        )}
      </section>
      {/* Ride mode's choices (WEB-NAV-plan.md section 3): the same ones the first Start ride asks, kept on this device. */}
      <section aria-labelledby="settings-ride-heading" className="settings-group">
        <h3 id="settings-ride-heading">Ride mode</h3>
        <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="settings-ride" />
      </section>
      {/* The installable app (WEB-NAV-plan.md section 8, P3 and P4): the routes kept on this device, and the install offer. */}
      <section aria-labelledby="settings-device-heading" className="settings-group">
        <h3 id="settings-device-heading">This device</h3>
        {keepShown || anyKept() ? <KeptRoutes version={keptVersion} onOpen={openKept} onSay={announce} /> : <p className="hint">Offline routes: none kept yet.</p>}
        <InstallOffer idBase="settings-install" onSay={announce} />
      </section>
      <section aria-labelledby="settings-signin-heading" className="settings-group">
        <h3 id="settings-signin-heading">Account</h3>
        {myGo.signedIn ? (
          <p className="hint signed-in">
            <Icon name="user" size={16} /> Signed in with Discord.
          </p>
        ) : (
          <p className="hint">
            Planning works without signing in, and a plan made signed out is not saved; the link in the address bar reopens it. Saving routes and
            peer review are coming for riders who{" "}
            <a href="/auth/login" onClick={(e) => isPlainClick(e) && rememberPlanForSignIn(tabSession(), window.location.hash, linkNote !== "")}>
              sign in with Discord
            </a>
            ; your current plan is kept across the sign-in.
          </p>
        )}
        <MyGoSection controls={myGo} />
      </section>
    </SheetFrame>
  );
}

export interface SuggestSheetProps {
  nav: SheetNav;
  /** Opens the road panel at the map's centre (Map tools' Road info). */
  roadInfoAtCentre: () => void;
  /** An instance admin's review, or null for everyone else. */
  onReview: ((opener: HTMLElement) => void) | null;
}

/**
 * Suggest (the owner's choice 6): the one way in to the suggest tools. Each starts from a road on the map
 * (the road panel's "Suggest a change…": a road's level, a junction, a Mass Ride hazard), so this says how
 * to get there and opens the panel at the map's centre; DC 311 is reported from Ride mode's 311 button.
 */
export function SuggestSheet({ nav, roadInfoAtCentre, onReview }: SuggestSheetProps) {
  return (
    <SheetFrame id="sheet-suggest" title={SHEET_TITLES.suggest} open={nav.view === "suggest"} onBack={nav.back} backLabel={nav.backLabel("suggest")}>
      <section aria-labelledby="suggest-map-heading" className="settings-group">
        <h3 id="suggest-map-heading">A road or a junction</h3>
        <p className="hint">
          Right-click a road, or press and hold it, then choose Suggest a change: a road's traffic stress, a junction, or a hazard on a Mass Ride.
          Suggestions go to the map's admins; nothing changes until one of them reviews it.
        </p>
        <button type="button" className="secondary suggest-at-centre" onClick={roadInfoAtCentre}>
          <Icon name="road" />
          The road at the map's center
        </button>
      </section>
      <section aria-labelledby="suggest-311-heading" className="settings-group">
        <h3 id="suggest-311-heading">Report a problem to DC 311</h3>
        <p className="hint">
          While you ride inside DC, the round 311 button on the map's right edge reports a problem where you are ({REPORT_KINDS.map((k) => k.label.toLowerCase()).join(", ")}),
          with your place taken from the route's street names.
        </p>
        <a className="action-link secondary" href={DC_311_ONLINE} target="_blank" rel="noopener noreferrer">
          Open DC 311 online (new tab)
        </a>
      </section>
      {onReview && (
        <section aria-labelledby="suggest-review-heading" className="settings-group">
          <h3 id="suggest-review-heading">Review</h3>
          <p className="hint">Riders' suggestions and Mass Ride hazard reports waiting for an admin.</p>
          <button type="button" className="secondary open-review" onClick={(event) => onReview(event.currentTarget)}>
            <Icon name="shield" />
            Review suggestions
          </button>
        </section>
      )}
    </SheetFrame>
  );
}

export interface ReviewSheetProps {
  nav: SheetNav;
  mapRef: RefObject<MapLibreMap | null>;
  setHazardsAsked: Dispatch<SetStateAction<number>>;
}

/** An instance admin's review of rider suggestions and Mass Ride hazard reports (OWNER-DECISIONS 460.5), moved out of Settings. */
export function ReviewSheet({ nav, mapRef, setHazardsAsked }: ReviewSheetProps) {
  return (
    <SheetFrame id="sheet-review" title={SHEET_TITLES.review} open={nav.view === "review"} onBack={nav.back} backLabel={nav.backLabel("review")}>
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

/** The map's Water chip: the nearest water, restroom or Metro station (the finder that was a fold in Points). */
export function NearestSheet({ nav, children }: { nav: SheetNav; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-nearest" title={SHEET_TITLES.nearest} open={nav.view === "nearest"} onBack={nav.back} backLabel={nav.backLabel("nearest")}>
      {children}
    </SheetFrame>
  );
}

/** The cuisine chips over Find food (the mockup's Food sheet): each one searches for it. */
export const FOOD_CHIPS = ["Crab", "Coffee", "Pizza", "Tacos", "Ice cream"] as const;

/** The map's Food chip: Find food (the panel that was a fold in Points), with the mockup's cuisine chips over it. */
export function FoodSheet({ nav, onChip, children }: { nav: SheetNav; onChip: (food: string) => void; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-food" title={SHEET_TITLES.food} open={nav.view === "food"} onBack={nav.back} backLabel={nav.backLabel("food")}>
      <div className="chip-row food-chips" role="group" aria-label="Quick searches">
        {FOOD_CHIPS.map((food) => (
          <button key={food} type="button" className="chip" onClick={() => onChip(food.toLowerCase())}>
            <Icon name="food" size={16} />
            {food}
          </button>
        ))}
      </div>
      {children}
    </SheetFrame>
  );
}

/** Go's Ride sheet: every ride type as a chip and every dial (the Ride line's controls, which Plan keeps in the panel). */
export function RideSheet({ nav, children }: { nav: SheetNav; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-ride" title={SHEET_TITLES.ride} open={nav.view === "ride"} onBack={nav.back} backLabel={nav.backLabel("ride")}>
      {children}
    </SheetFrame>
  );
}

const RIDE_ICON: Partial<Record<PresetId, IconName>> = {
  cargo: "cargo",
  bikeshare: "bikeshare",
  kids: "kid",
  "mountain-bike": "mtb",
  gravel: "gravel",
  fast: "fast",
  ebike: "bolt",
  "mountain-goat": "mountain",
  "group-ride": "user",
  "mass-ride": "federal",
  trailmaxxing: "trail",
  "bike-transit": "train",
  "bikeshare-transit": "train",
  rebalance: "bikeshare",
};

/**
 * Go's More ride types: every ride type, searchable, under its group's heading
 * (RIDE-TYPE-ORGANISE, lib/rideTypeGroups.ts). The search comes first in the Tab order.
 *
 * The outline: the sheet's h2, then this list under its own h3 (read, not shown: the sheet
 * already says what it is), its groups as h4 under it, so the Ride line's "Ride type" h3 that
 * follows in Go's sheet is a sibling and not a fourth group. Each group is named once, by its
 * heading (the chips' own group is left unnamed). The search is cleared whenever the sheet is
 * left, as Plan's dialog clears it on closing, so the next visit shows every ride type.
 */
export function RideGroupChips({ preset, onPick, open }: { preset: PresetId; onPick: (id: PresetId) => void; open: boolean }) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);
  const groups = filterRideGroups(query);
  return (
    <section className="ride-groups" aria-labelledby="ride-sheet-types">
      <h3 id="ride-sheet-types" className="visually-hidden">
        Every ride type
      </h3>
      <RideTypeSearch id="ride-sheet-search" query={query} onQuery={setQuery} count={rideTypeCount(groups)} />
      {groups.map((group) => (
        <section key={group.id} className="ride-group" aria-labelledby={`ride-sheet-${group.id}`}>
          <h4 id={`ride-sheet-${group.id}`}>{group.label}</h4>
          <RideChips ids={group.ids} preset={preset} onPick={onPick} />
        </section>
      ))}
    </section>
  );
}

/** The ride type chips (Go's quick three and More, or every type in the Ride sheet), each a toggle button. */
export function RideChips({
  ids,
  preset,
  onPick,
  more,
  label,
  ownHint,
}: {
  ids: readonly PresetId[];
  preset: PresetId;
  onPick: (id: PresetId) => void;
  more?: (opener: HTMLElement) => void;
  /** The chips' group name; left out where a heading already names them (Go's More ride types). */
  label?: string;
  /** Go: the first chip is the rider's own ride type (My Go), described as such. */
  ownHint?: string;
}) {
  return (
    <div className="chip-row ride-chips" role={label ? "group" : undefined} aria-label={label}>
      {ids.map((id, index) => (
        <button
          key={id}
          type="button"
          className="chip ride-type-chip"
          aria-pressed={preset === id}
          onClick={() => onPick(id)}
          aria-describedby={ownHint && index === 0 ? "ride-own-hint" : undefined}
        >
          <Icon name={RIDE_ICON[id] ?? "bike"} size={18} />
          {presetLabel(id)}
        </button>
      ))}
      {more && (
        <button type="button" className="chip ride-more" onClick={(event) => more(event.currentTarget)} aria-describedby="ride-more-hint">
          <Icon name="more" size={18} />
          More ride types
        </button>
      )}
      {more && (
        <span id="ride-more-hint" hidden>
          Every ride type and setting.
        </span>
      )}
      {ownHint && (
        <span id="ride-own-hint" hidden>
          {ownHint}
        </span>
      )}
    </div>
  );
}
