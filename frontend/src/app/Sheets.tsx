// The panel's sheets (moved out of App.tsx in UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"),
// arranged as the approved UI mockup of 2026-10-11 has them (reports/v0.5.0/ui-mockup.html): Layers is its
// switches, with the legend behind a Legend button at its top (the owner's choice 6); Suggest is the one way
// in to the suggest tools, and Review is an admin's; Settings is Display, Riding and Account
// with My Go; and the map's Water and Food chips open the nearest finder and Find food. In Go, Settings is
// the Menu, with Plan, Suggest, GPX and Review above it. App.tsx keeps the state and the effects.
import { useEffect, useState, type ReactNode, type RefObject } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { StressAvailability } from "../MapView.tsx";
import type { RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { PRESETS, presetSaid, type PresetId } from "../lib/presets.ts";
import { PresetName } from "../lib/presetName.ts";
import { filterRideGroups, rideSections, rideTypeCount, RideTypeSearch } from "../lib/rideTypeGroups.ts";
import { RideTypeCards } from "../lib/rideTypeCards.ts";
import { DELETE_ACCOUNT_PAGE, isPlainClick, rememberPlanForSignIn, tabSession } from "../lib/signIn.ts";
import { SignOutForm } from "../SignOut.tsx";
import { AssistantKeySetting } from "../AssistantKey.tsx";
import { pointName } from "../lib/summary.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, setMtbTrails } from "../stressStyle.js";
import { HighStressLanesSwitch } from "../lib/highStressLanesSwitch.ts";
import { MtbTrailsSwitch } from "../lib/mtbTrailsSwitch.ts";
import { setTopoLines, TopoLinesSwitch } from "../lib/topoLines.ts";
import { stressShowable, terrainLayers, terrainStatus } from "../lib/terrainSection.ts";
import { LayerSection } from "../lib/layerSection.ts";
import { AccessibilitySwitch } from "../lib/accessibilitySwitch.ts";
import { ACCESS_HELP, ACCESS_LABEL } from "../lib/accessMode.ts";
import { RideSettingsFields } from "../RideMode.tsx";
import { BIG_TEXT_HELP, BIG_TEXT_LABEL } from "../lib/rideOutput.ts";
import type { RidePrefs } from "../lib/rideOutput.ts";
import type { RailVisibility } from "../lib/railStations.ts";
import { RailStationsLegend, RailStationsSection } from "../RailStations.tsx";
import { BikeshareSection } from "../lib/bikeshareSection.ts";
import type { OperatorInfo } from "../lib/bikeshareDocks.ts";
import { RAIL_STATIONS } from "../lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "../lib/federalLand.ts";
import { FederalLandFor, FederalLegendNotes, type FederalStatus } from "../lib/federalLegend.ts";
import { CAPACITY_LEGEND_TITLE, isMassRide } from "../lib/massCapacity.ts";
import { MassLegend, MassZoomNotes } from "../lib/massLegend.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { MtbTrailLegend, StressLegend } from "../lib/stressLegend.ts";
import { GpxPanel, type FileFormat, type GpxPanelProps, type Said } from "../GpxPanel.tsx";
import type { DeviceProfileId } from "../lib/deviceProfiles.ts";
import { JunctionLegend, SheetFrame } from "../Sidebar.tsx";
import { MASS_RIDE_LAYERS_NOTE, MENU_TITLE, SAVE_LOAD, SHEET_TITLES, STRESS_CHECKING, STRESS_UNAVAILABLE, type PanelView } from "../lib/sidebar.ts";
import type { ImportedPlan } from "../lib/gpxPlan.ts";
import type { WaterPrefs, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterLegend, WaterLegendNotes, WaterSection } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbCategory, ClimbsStatus } from "../lib/climbs.ts";
import { CLIMBS_HELP, ClimbsLayerControls, ClimbsLegend } from "../lib/climbsLegend.ts";
import { ScenicLegend, ScenicSection } from "../lib/scenicLayer.ts";
import { PermitsSection } from "../lib/permitLayer.ts";
import { InstallOffer } from "../InstallableApp.tsx";
import type { Split, StoredWeight } from "../lib/weight.ts";
import { WeightSetting } from "../lib/weightDialog.ts";
import { DC_311_ONLINE, REPORT_KINDS } from "../lib/report311.ts";
import { OPEN_IN_HINT, OPEN_IN_LABEL, type AppMode, type OpenIn } from "../lib/appMode.ts";
import { myGoSummary, type Home, type MyGo } from "../lib/myGo.ts";
import { homeFromPlace } from "../lib/homeSet.ts";
import { HomeSetter } from "./Go.tsx";
import { SIGN_IN_LINE } from "../lib/accountSettings.ts";
import type { GeoGate, Place } from "../lib/geocode.ts";
import type { IconName } from "../lib/iconPaths.ts";
import { Icon } from "../Icon.tsx";
import { InfoButton, SettingRow, SettingSelect } from "../SettingRow.tsx";
import { shortLabel } from "../lib/shortLabel.ts";
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
  /** The Climbs layer (lib/climbs.ts): the switch, its data's status and the climbs the route rides. */
  climbsOn: boolean;
  changeClimbsOn: (on: boolean) => void;
  climbsFrom: ClimbCategory;
  changeClimbsFrom: (from: ClimbCategory) => void;
  climbsStatus: ClimbsStatus;
  climbsAlong: ClimbAlong[] | null;
  rail: RailVisibility;
  setRail: (next: RailVisibility) => void;
  showMtbTrails: boolean;
  showTopoLines: boolean;
  topoReady: boolean;
  /** The Places to see layer (v0.7.0; lib/places.ts): one switch, off by default; its status line. */
  placesOn: boolean;
  changePlacesOn: (on: boolean) => void;
  placesStatus: string;
  /** Bikeshare docks and free e-bikes (v0.7.0; BikeshareDocks.tsx): Capital Bikeshare's switch. */
  bikeshare: { operators: readonly OperatorInfo[]; choices: Record<string, boolean>; onChange: (next: Record<string, boolean>) => void; status: string };
  /** The Scenic layer (v0.8.0; lib/scenicLayer.ts): one switch, off by default; null in Go, which leaves it out. */
  scenic: { on: boolean; onChange: (on: boolean) => void; status: string } | null;
  /** DC permits (v0.9.1; lib/permitLayer.ts): one switch, off by default; null in Go, which leaves it out. */
  permits: { on: boolean; onChange: (on: boolean) => void } | null;
}

export const PLACES_LAYER_TITLE = "Places to see";
export const PLACES_LAYER_HINT = "Museums, gardens, viewpoints and more. Places to see lists them.";

/** The Layers sheet: the map's switches, in the mockup's order, with the Legend button at its top. */
export function LayersSheet(props: LayersSheetProps) {
  const { nav, openLegend, massMap, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn, setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus, rail, setRail, showMtbTrails, showTopoLines, topoReady, climbsOn, changeClimbsOn, climbsFrom, changeClimbsFrom, climbsStatus, climbsAlong, placesOn, changePlacesOn, placesStatus, bikeshare, scenic, permits } = props;
  // The Trails and terrain section's layers that can show, and its row's words (lib/terrainSection.ts).
  const terrain = { mtb: showMtbTrails, climbs: climbsOn, topo: showTopoLines, stressAvailable: stressShowable(stress), topoReady, climbsStatus };
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

      <BikeshareSection {...bikeshare} />

      {/* v0.7.0: the places to see, one switch for the whole layer (the categories are Plan's Places to see filter). */}
      <LayerSection
        id="places"
        title={PLACES_LAYER_TITLE}
        headingId="places-heading"
        layers={[{ key: "places", label: PLACES_LAYER_TITLE, on: placesOn }]}
        onLayers={(next) => changePlacesOn(next.places)}
        status={placesStatus}
      >
        <p className="hint">{PLACES_LAYER_HINT}</p>
      </LayerSection>

      {/* OWNER-DECISIONS 454's optional layers, off until turned on, in every ride type. A layer's extra
          control (the Climbs layer's "Show climbs from") sits under its own switch, inside the section. */}
      <LayerSection
        id="terrain"
        title="Trails and terrain"
        headingId="terrain-heading"
        layers={terrainLayers(terrain)}
        onLayers={(next) => {
          if ("mtb" in next && next.mtb !== showMtbTrails) setMtbTrails(next.mtb);
          if ("climbs" in next && next.climbs !== climbsOn) changeClimbsOn(next.climbs);
          if ("topo" in next && next.topo !== showTopoLines) setTopoLines(next.topo);
        }}
        // Each layer's own status or hint line is inside; closed, the section says it.
        status={(open) => terrainStatus(open, terrain)}
      >
        <MtbTrailsSwitch on={showMtbTrails} onChange={(on) => setMtbTrails(on)} overlay={stressShowable(stress)} />
        <ClimbsLayerControls on={climbsOn} onChange={changeClimbsOn} from={climbsFrom} onFromChange={changeClimbsFrom} status={climbsStatus} items={climbsAlong} along={false} legend={false} />
        <TopoLinesSwitch on={showTopoLines} onChange={(on) => setTopoLines(on)} available={topoReady} />
      </LayerSection>

      {/* v0.8.0: the Scenic layer, one switch, off by default, after Trails and terrain; Plan's alone. */}
      {scenic && <ScenicSection {...scenic} />}
      {/* v0.9.1: DDOT's permits, flagged only, one switch, off by default; Plan's alone. */}
      {permits && <PermitsSection {...permits} />}

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
  /** Whether the Scenic layer is drawn (its switch, in Plan, off the Mass Ride map): its one legend entry. */
  scenicOn: boolean;
}

/** The legend, behind Layers' Legend button (the owner's choice 6): what each zoom shows and how stress ratings work. */
export function LegendSheet(props: LegendSheetProps) {
  const { nav, legendHeadingRef, massMap, stress, stressVisible, preset, zoom, facilitiesShown, waterPrefs, waterStatus, climbsOn, climbsStatus, federalOn, federalStatus, rail, scenicOn } = props;
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
        {scenicOn && <ScenicLegend />}
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
  /** Download GPX: the page checks closures first, and an unedited opened file downloads as it came. */
  downloadRoute: (said?: (line: string) => void) => void;
  /** Plan only: download a FIT or TCX course or a PDF cue sheet (GpxPanel); absent in Go, which offers GPX alone. */
  downloadCourse?: (format: FileFormat, profile: DeviceProfileId, said: Said) => void;
  /** Send to Garmin: the route shown as a FIT course, handed to the phone for Garmin Connect (GpxPanel). */
  sendToGarmin?: (said: Said) => void;
  /** Plan only: snap an opened track to the map's ways (GpxPanel, lib/gpxMatch.ts); absent in Go. */
  match?: GpxPanelProps["match"];
  /** Save route (signed in) and Share, for the route shown or the file opened (RoutePanel.tsx ShareControls); null with neither. */
  shareControls: ReactNode;
  /** Your routes: the saved ones and the ones kept for offline, with a search (YourRoutes.tsx); null with neither. */
  routes: ReactNode;
}

/** The GPX sheet. */
export function GpxSheet(props: GpxSheetProps) {
  const { nav, shown, routedPoints, routedLoop, federalRoute, points, status, imported, openImported, refineImported, getMap, downloadRoute, downloadCourse, sendToGarmin, match, shareControls, routes } = props;
  return (
    <SheetFrame id="sheet-gpx" title={SHEET_TITLES.gpx} open={nav.view === "gpx"} onBack={nav.back} backLabel={nav.backLabel("gpx")}>
      {/* Save and Share first, then your routes to load (in Go, the way to start a saved route), then the files. */}
      {shareControls}
      {routes}
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
        onDownload={downloadRoute}
        onDownloadCourse={downloadCourse}
        onSendToGarmin={sendToGarmin}
        match={match}
      />
    </SheetFrame>
  );
}

export interface MyGoControls {
  myGo: MyGo;
  signedIn: boolean;
  /** Saves the whole of My Go (to the account signed in, else this device). */
  save: (next: MyGo) => void;
  /** Sets (or with null clears) Home alone, and says so (lib/homeSet.ts). */
  setHome: (home: Home | null) => void;
  /** What the last save said, politely. */
  said: string;
  geoGate: GeoGate;
  searchBias: () => LonLat | undefined;
}

/** "Open in": By screen size, Go or Plan, as a picker, with what "By screen size" means behind an (i). */
function OpenInChoice({ value, onChange, idBase, hint }: { value: OpenIn; onChange: (next: OpenIn) => void; idBase: string; hint?: string }) {
  return (
    <SettingRow infoId={`${idBase}-open-in-info`} about="open in" info={hint} className="open-in">
      <SettingSelect
        label="Open in"
        value={value}
        options={(["", "go", "plan"] as OpenIn[]).map((option) => [option, OPEN_IN_LABEL[option]] as const)}
        onChange={onChange}
        describedBy={hint ? `${idBase}-open-in-info` : undefined}
      />
    </SettingRow>
  );
}

/**
 * My Go (the owner's choice 2): where the app opens and Go's ride type, saved to the account when signed
 * in and on this device when not; signed in, the Home that Go's Home chip rides to.
 */
function MyGoSection({ controls }: { controls: MyGoControls }) {
  const { myGo, signedIn, save, setHome, said, geoGate, searchBias } = controls;
  const [infoOpen, setInfoOpen] = useState(false);
  return (
    <section aria-labelledby="settings-my-go-heading" className="my-go">
      <div className="setting-line">
        <h4 id="settings-my-go-heading">
          <Icon name="star" size={18} />
          My Go
          <span className="setting-value">
            <span className="visually-hidden">: </span>
            {myGoSummary(myGo)}
          </span>
        </h4>
        <InfoButton open={infoOpen} onToggle={() => setInfoOpen((was) => !was)} controls="settings-my-go-info" about="My Go" />
      </div>
      <p className="hint setting-info" id="settings-my-go-info" hidden={!infoOpen}>
        {signedIn ? "Kept with your Discord account, on every device you sign in on." : "Kept on this device. Sign in to keep it with your account."}
      </p>
      <OpenInChoice value={myGo.openIn} onChange={(openIn) => save({ ...myGo, openIn })} idBase="my-go" hint={OPEN_IN_HINT} />
      <SettingRow infoId="settings-go-ride-info" about="Go's ride type">
        <SettingSelect
          label="Go's ride type"
          value={myGo.ride ?? "default"}
          options={PRESETS.filter((p) => p.id !== "mass-ride").map((p) => [p.id, presetSaid(p.id)] as const)}
          onChange={(ride) => save({ ...myGo, ride: ride === "default" ? null : ride })}
        />
      </SettingRow>
      {/* The same Home sheet as Go's (lib/homeSet.ts), without the map way: the map is behind Settings. */}
      <div className="my-go-home">
        {!myGo.home && (
          <p>
            <strong>Home: </strong>not set
          </p>
        )}
        <HomeSetter home={myGo.home} geoGate={geoGate} searchBias={searchBias} onPlace={(place: Place) => setHome(homeFromPlace(place))} onClear={() => setHome(null)} />
      </div>
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
  /** Big text in a ride: a setting here, not a ride button (the owner, 2026-10-17). */
  bigText: { on: boolean; onChange: (on: boolean) => void };
  /** The rider and bike weight: its line and Change, never the number (lib/weightDialog.ts). */
  weight: { saved: StoredWeight | null; remembered: boolean; split: Split; onSave: (weight: StoredWeight, remember: boolean) => void; onClear: () => void };
  announce: (text: string) => void;
  linkNote: string;
  accessMode: boolean;
  toggleAccessMode: (focusTools: boolean) => void;
  myGo: MyGoControls;
  /** Announcements, Brief or Full (lib/announceLevel.ts): the level in force, and the rider's choice. */
  announcements: { level: AnnounceLevel; choose: (level: AnnounceLevel) => void };
  /** Go shows this sheet as its Menu: Plan, Suggest, GPX and (an admin's) Review above the settings. */
  mode: AppMode;
  /** Whether this server can sign anyone in (GET /api/me's sign_in): the sign-in line is shown only then. */
  signInAvailable: boolean;
  menu: { onPlan: () => void; onSuggest: (opener: HTMLElement) => void; onGpx: (opener: HTMLElement) => void; onReview: ((opener: HTMLElement) => void) | null };
}

/** High contrast, as the Map layers sheet has it, with its explanation behind an (i). */
function ContrastRow() {
  const [open, setOpen] = useState(false);
  return (
    <div className="setting-row contrast-row">
      <AccessibilitySwitch
        idBase="settings-contrast"
        on={accessibilityOn()}
        source={accessibilitySource()}
        paletteFromAddress={paletteSetByAddress()}
        onChange={(on) => setAccessibility(on)}
        hintHidden={!open}
      />
      <InfoButton open={open} onToggle={() => setOpen((was) => !was)} controls="settings-contrast-hint" about="high contrast" />
    </div>
  );
}

/** The Settings sheet (Go's Menu): Display, Riding and Account, as the mockup groups them. */
export function SettingsSheet(props: SettingsSheetProps) {
  const { nav, settingsHeadingRef, ridePrefs, changeRidePrefs, announce, linkNote, accessMode, toggleAccessMode, myGo, mode, menu, announcements, signInAvailable } = props;
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
            {SAVE_LOAD}
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
        <ContrastRow />
        {/* Accessibility mode (OWNER-DECISIONS 455) as a switch here too (the mockup), the same state as the page's first button. */}
        <SettingRow infoId="settings-access-hint" about="accessibility mode" info={ACCESS_HELP} className="a11y-setting">
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
        </SettingRow>
        {/* How much screen readers are told (the owner, 2026-10-11 20:23 UTC): Brief or Full; unset, Go is brief. */}
        <SettingRow
          infoId="settings-announce-info"
          about="announcements"
          className="announce-level"
          info={
            <>
              <ul className="setting-info-list">
                {(["brief", "full"] as const).map((level) => (
                  <li key={level}>{ANNOUNCE_LABEL[level]}</li>
                ))}
              </ul>
              {ANNOUNCE_HINT}
            </>
          }
        >
          <SettingSelect
            label="Announcements"
            value={announcements.level}
            options={(["brief", "full"] as const).map((level) => [level, shortLabel(ANNOUNCE_LABEL[level])] as const)}
            onChange={(level) => announcements.choose(level)}
            describedBy="settings-announce-info"
          />
        </SettingRow>
        {/* Open in Go or Plan is My Go's, under Account, signed in or out: one control, not two (Plan streamline). */}
      </section>
      {/* Ride mode's choices (WEB-NAV-plan.md section 3): the same ones the first Start ride asks, kept on this device. */}
      <section aria-labelledby="settings-ride-heading" className="settings-group">
        <h3 id="settings-ride-heading">Riding</h3>
        {/* Rider and bike weight, for how hard hills feel (the owner, 2026-10-18: "probably belongs in settings"). */}
        <WeightSetting {...props.weight} />
        <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="settings-ride" compact />
        {/* Big text: a setting here, not a ride button (the owner, 2026-10-17: "not something people will fiddle with mid ride"). */}
        <SettingRow infoId="settings-big-text-info" about="big text" info={BIG_TEXT_HELP} className="big-text-row">
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={props.bigText.on}
            aria-labelledby="settings-big-text-label"
            aria-describedby="settings-big-text-info"
            onClick={() => props.bigText.onChange(!props.bigText.on)}
          >
            <span id="settings-big-text-label" className="switch-label">
              {BIG_TEXT_LABEL}
            </span>
            <span className="switch-state" aria-hidden="true">
              {props.bigText.on ? "On" : "Off"}
            </span>
          </button>
        </SettingRow>
      </section>
      {/* The installable app (WEB-NAV-plan.md section 8, P4), under its own heading when the browser offers it. The
          routes saved and kept for offline are in Save and load (YourRoutes.tsx; the owner, 2026-10-18). */}
      <InstallOffer idBase="settings-install" onSay={announce} />
      <section aria-labelledby="settings-signin-heading" className="settings-group">
        <h3 id="settings-signin-heading">Account</h3>
        {myGo.signedIn ? (
          <>
            <p className="hint signed-in">
              <Icon name="user" size={16} /> Signed in with Discord.
            </p>
            <SignOutForm />
            {/* A page of its own (core.account_deletion), the same one the web offers without the app: it says what goes
                and what is kept, and asks once. */}
            <p className="delete-account">
              <a href={DELETE_ACCOUNT_PAGE}>Delete account</a>
            </p>
          </>
        ) : signInAvailable ? (
          // The plan's one line (item 4); the link is its first words. The plan in hand is kept across the round trip.
          <p className="hint sign-in-line">
            <a href="/auth/login" onClick={(e) => isPlainClick(e) && rememberPlanForSignIn(tabSession(), window.location.hash, linkNote !== "")}>
              Sign in with Discord
            </a>
            {SIGN_IN_LINE.slice("Sign in with Discord".length)}
          </p>
        ) : null}
        <MyGoSection controls={myGo} />
        {/* The save-only key an AI assistant's MCP server saves routes with (the owner, 2026-10-18). */}
        {myGo.signedIn && <AssistantKeySetting />}
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
          <p className="hint">Riders' suggestions, Mass Ride hazard reports and closure reports are in Review, beside Go and Plan.</p>
          <button type="button" className="secondary open-review" onClick={(event) => onReview(event.currentTarget)}>
            <Icon name="shield" />
            Review suggestions
          </button>
        </section>
      )}
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
// Farm stands (v0.7.0, the owner 2026-10-14: "Lots of places are selling apples in the fall"), with the apple.
export const FOOD_CHIPS = ["Crab", "Coffee", "Pizza", "Tacos", "Ice cream", "Farm stands"] as const;

/** The map's Food chip: Find food (the panel that was a fold in Points), with the mockup's cuisine chips over it. */
export function FoodSheet({ nav, onChip, children }: { nav: SheetNav; onChip: (food: string) => void; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-food" title={SHEET_TITLES.food} open={nav.view === "food"} onBack={nav.back} backLabel={nav.backLabel("food")}>
      <div className="chip-row food-chips" role="group" aria-label="Quick searches">
        {FOOD_CHIPS.map((food) => (
          <button key={food} type="button" className="chip" onClick={() => onChip(food.toLowerCase())}>
            <Icon name={food === "Farm stands" ? "apple" : "food"} size={16} />
            {food}
          </button>
        ))}
      </div>
      {children}
    </SheetFrame>
  );
}

/** Go's Edit route sheet (edit-route redesign, Stephen 2026-10-18): Plan's points, opened from Go's route card. */
export function EditRouteSheet({ nav, children }: { nav: SheetNav; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-points" title={SHEET_TITLES.points} open={nav.view === "points"} onBack={nav.back} backLabel={nav.backLabel("points")}>
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
  novice: "kid",
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

const rideIcon = (id: PresetId) => <Icon name={RIDE_ICON[id] ?? "bike"} size={20} />;

/**
 * Go's More ride types: every ride type, searchable, under its group's heading
 * (RIDE-TYPE-ORGANISE, lib/rideTypeGroups.ts). The search comes first in the Tab order.
 * Each type is a card with its name and one short sentence (lib/rideTypeCards.ts).
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
  // Review F9: the common types first, the rest in their groups, folded (the one in use opens its group); a search
  // shows every match flat. The class is ride-sheet-group: .ride-group is the group ride's overlay (RideGroup.tsx).
  const { common, groups, folded } = rideSections(query);
  return (
    <section className="ride-groups" aria-labelledby="ride-sheet-types">
      <h3 id="ride-sheet-types" className="visually-hidden">
        Every ride type
      </h3>
      <RideTypeSearch id="ride-sheet-search" query={query} onQuery={setQuery} count={rideTypeCount(filterRideGroups(query))} />
      {common.length > 0 && (
        <section className="ride-sheet-group" aria-labelledby="ride-sheet-common">
          <h4 id="ride-sheet-common">Common</h4>
          <RideTypeCards ids={common} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} />
        </section>
      )}
      {groups.map((group) =>
        folded ? (
          <details key={group.id} className="fold ride-sheet-fold" open={group.ids.includes(preset) || undefined}>
            <summary>{`${group.label} (${group.ids.length})`}</summary>
            <div className="fold-body">
              <RideTypeCards ids={group.ids} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} />
            </div>
          </details>
        ) : (
          <section key={group.id} className="ride-sheet-group" aria-labelledby={`ride-sheet-${group.id}`}>
            <h4 id={`ride-sheet-${group.id}`}>{group.label}</h4>
            <RideTypeCards ids={group.ids} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} />
          </section>
        ),
      )}
    </section>
  );
}

/** Go's quick ride type chips and the More button, each chip a toggle button. */
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
  /** The chips' group name; leave it out where a heading already names them. */
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
          <PresetName id={id} />
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
