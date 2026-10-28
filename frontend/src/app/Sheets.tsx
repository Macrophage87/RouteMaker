// The panel's sheets (moved out of App.tsx in UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"),
// arranged as the approved UI mockup of 2026-10-11 has them (reports/v0.5.0/ui-mockup.html): Layers is its
// switches, each section with its own key (the owner, 2026-10-19); Suggest is the one way
// in to the suggest tools, and Review is an admin's; Settings is three tabs, Riding (My Go first), Display and
// Account (the owner, 2026-10-28); and the
// map's Water and Food chips open the nearest finder and Find food. In Go, Settings is the Menu, with Plan,
// Suggest, GPX and Review above it. App.tsx keeps the state and the effects.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { StressAvailability } from "../MapView.tsx";
import type { RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { PRESETS, presetSaid, type PresetId } from "../lib/presets.ts";
import { PresetName } from "../lib/presetName.ts";
import { filterRideGroups, rideSections, rideTypeCount, rideTypeSections, RideTypeSearch } from "../lib/rideTypeGroups.ts";
import { RideTypeCards } from "../lib/rideTypeCards.ts";
import { toggleFromPicker, useFavoriteRides } from "../lib/favoriteRides.ts";
import { DELETE_ACCOUNT_PAGE, PRIVACY_PAGE, isPlainClick, rememberPlanForPage, rememberPlanForSignIn, tabSession } from "../lib/signIn.ts";
import { SignOutForm } from "../SignOut.tsx";
import { AssistantAppsSetting } from "../AssistantApps.tsx";
import { GarminSetting, WahooSetting } from "../ConnectionSetting.tsx";
import { pointName } from "../lib/summary.ts";
import { accessibilityOn, accessibilitySource, paletteSetByAddress, setAccessibility, setHighStressLanes, setMtbTrails } from "../stressStyle.js";
import { HighStressLanesSwitch } from "../lib/highStressLanesSwitch.ts";
import { MtbTrailsSwitch } from "../lib/mtbTrailsSwitch.ts";
import { setTopoLines, TopoLinesSwitch } from "../lib/topoLines.ts";
import { stressShowable, terrainLayers, terrainStatus } from "../lib/terrainSection.ts";
import { LayerSection } from "../lib/layerSection.ts";
import { AccessibilitySwitch } from "../lib/accessibilitySwitch.ts";
import { ACCESS_FINE_TUNE, ACCESS_HELP, ACCESS_LABEL } from "../lib/accessMode.ts";
import { RideSettingsFields } from "../RideMode.tsx";
import { RIDE_TEXT_HELP, RIDE_TEXT_LABEL, type RideTextSize } from "../lib/rideOutput.ts";
import type { RidePrefs } from "../lib/rideOutput.ts";
import type { RailVisibility } from "../lib/railStations.ts";
import { RailStationsSection } from "../RailStations.tsx";
import { BikeshareSection } from "../lib/bikeshareSection.ts";
import type { OperatorInfo } from "../lib/bikeshareDocks.ts";
import { RAIL_STATIONS } from "../lib/railData.ts";
import { federalPoints, federalShown, type FederalData } from "../lib/federalLand.ts";
import { FederalLandFor, type FederalStatus } from "../lib/federalLegend.ts";
import { CAPACITY_LEGEND_TITLE, isMassRide } from "../lib/massCapacity.ts";
import { MassLegend, MassZoomNotes } from "../lib/massLegend.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY } from "../lib/dcBoundary.ts";
import { DocsPageLink, MtbTrailLegend, StressLegend } from "../lib/stressLegend.ts";
import { GpxPanel, type FileFormat, type GpxPanelProps, type Said } from "../GpxPanel.tsx";
import type { DeviceProfileId } from "../lib/deviceProfiles.ts";
import { JunctionLegend, SheetFrame } from "../Sidebar.tsx";
import { MASS_RIDE_LAYERS_NOTE, MENU_TITLE, SAVE_LOAD, SHEET_TITLES, STRESS_CHECKING, STRESS_UNAVAILABLE, suggestHint, type PanelView } from "../lib/sidebar.ts";
import { looksLikePhone } from "../lib/startOnComputer.ts";
import type { ImportedPlan } from "../lib/gpxPlan.ts";
import type { WaterPrefs, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterSection } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbCategory, ClimbsStatus } from "../lib/climbs.ts";
import { ClimbsLayerControls } from "../lib/climbsLegend.ts";
import { ScenicSection } from "../lib/scenicLayer.ts";
import { RouteHazardKey } from "../lib/routeHazards.ts";
import { SteepGradeKey, steepGradesFor } from "../lib/steepGrades.ts";
import { PermitsSection } from "../lib/permitLayer.ts";
import { InstallOffer } from "../InstallableApp.tsx";
import type { Split, StoredWeight } from "../lib/weight.ts";
import { WeightSetting } from "../lib/weightDialog.ts";
import { Report311Log } from "../Report311Log.tsx";
import type { AppMode } from "../lib/appMode.ts";
import type { Home, MyGo } from "../lib/myGo.ts";
import { homeFromPlace, homeName } from "../lib/homeSet.ts";
import { HomeSetter } from "./Go.tsx";
import { SIGN_IN_LINE } from "../lib/accountSettings.ts";
import type { GeoGate, Place } from "../lib/geocode.ts";
import type { IconName } from "../lib/iconPaths.ts";
import { Icon } from "../Icon.tsx";
import { InfoButton, SettingRow, SettingSelect } from "../SettingRow.tsx";
import { shortLabel } from "../lib/shortLabel.ts";
import { ANNOUNCE_HINT, ANNOUNCE_LABEL, type AnnounceLevel } from "../lib/announceLevel.ts";
import type { Status } from "./RoutePanel.tsx";
import { APP_VERSION, versionSaid } from "../lib/appVersion.ts";
import { LANGUAGES, LANGUAGE_NAME, chooseLanguage, readLanguageChoice, t, type LanguageChoice } from "../lib/i18n.ts";

/** The Language setting's (i) words. Street names and notices from agencies stay as they are written. */
const LANGUAGE_HINT = "The app's words and the voice. Street names and agency notices stay as written. Changing it reloads the page.";

/** Settings > Display > Language: the choice is held here too, so a pick that needs no reload still shows. */
function LanguageSetting() {
  const [choice, setChoice] = useState<LanguageChoice>(() => readLanguageChoice());
  return (
    <SettingRow infoId="settings-language-info" about={t("Language")} info={t(LANGUAGE_HINT)}>
      <SettingSelect<LanguageChoice>
        label={t("Language")}
        value={choice}
        options={[["", t("Phone default")] as const, ...LANGUAGES.map((lang) => [lang, LANGUAGE_NAME[lang]] as const)]}
        onChange={(next) => {
          setChoice(next);
          chooseLanguage(next);
        }}
        describedBy="settings-language-info"
        optionLang={{ en: "en", es: "es" }}
      />
    </SettingRow>
  );
}

/** How the sheets go back: to the planner, or to the sheet that opened them (Suggest for Review). */
export interface SheetNav {
  view: PanelView;
  back: () => void;
  /** The words of each sheet's Back button. */
  backLabel: (view: PanelView) => string;
}

export interface LayersSheetProps {
  nav: SheetNav;
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
  /** What the stress section's key needs: the map's zoom and the bike facilities the route rides. */
  zoom: number | null;
  facilitiesShown: ReadonlySet<string>;
  /** Whether the Scenic layer is drawn (its switch, in Plan, off the Mass Ride map), for its key. */
  scenicDrawn: boolean;
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
  /** Go's stress bar tapped (the owner's P1): each new number opens the Traffic stress section, its colour key. */
  stressKeyAsk?: number;
}

export const PLACES_LAYER_TITLE = t("Places to see");
export const PLACES_LAYER_HINT = t("Museums, gardens, viewpoints and more. Places to see lists them.");

/** The Layers sheet: the map's switches, in the mockup's order, each section with its own key. */
export function LayersSheet(props: LayersSheetProps) {
  const { nav, massMap, zoom, facilitiesShown, scenicDrawn, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn, setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus, rail, setRail, showMtbTrails, showTopoLines, topoReady, climbsOn, changeClimbsOn, climbsFrom, changeClimbsFrom, climbsStatus, climbsAlong, placesOn, changePlacesOn, placesStatus, bikeshare, scenic, permits, stressKeyAsk } = props;
  // The Trails and terrain section's layers that can show, and its row's words (lib/terrainSection.ts).
  const terrain = { mtb: showMtbTrails, climbs: climbsOn, topo: showTopoLines, stressAvailable: stressShowable(stress), topoReady, climbsStatus };
  return (
    <SheetFrame
      id="sheet-layers"
      title={SHEET_TITLES.layers}
      open={nav.view === "layers"}
      onBack={nav.back}
      backLabel={nav.backLabel("layers")}
      popup
    >
      {/* The mockup's order: the stress map, lanes on busy roads, federal land (Mass Ride's alone), water and
          restrooms, Metro and MARC, then trails and terrain. High contrast is in Settings. Each section is one
          row, its name, one switch for the whole section and a disclosure; its layers are inside (lib/layerSection.ts). */}
      <LayerSection
        id="stress"
        title={massMap ? CAPACITY_LEGEND_TITLE : t("Traffic stress")}
        headingId="layers-heading"
        switchId="show-stress"
        layers={stress === "available" ? [{ key: "stress", label: massMap ? CAPACITY_LEGEND_TITLE : t("Traffic stress"), on: stressVisible }] : []}
        onLayers={(next) => setStressVisible(next.stress)}
        openAsk={stressKeyAsk}
        status={stress === "checking" ? STRESS_CHECKING : stress === "unavailable" ? STRESS_UNAVAILABLE : ""}
      >
        {/* Not one of the section's layers: shown with or without the stress map, as it also changes the
            route's facility totals and description (the a11y review's SF4). */}
        <HighStressLanesSwitch on={showHighLanes} onChange={(on) => setHighStressLanes(on)} overlay={stress === "available"} massMap={massMap} />
        {/* The owner, 2026-10-19: "include the legend within the accordion settings in layers". The map's key
            is in its own section. */}
        <StressSectionKey massMap={massMap} stress={stress} stressVisible={stressVisible} preset={preset} zoom={zoom} facilitiesShown={facilitiesShown} />
        {/* The junction markers are drawn with or without the stress map (spec review SF1). */}
        <JunctionLegend />
        {/* v0.12.5: steep grades, marked on a Mass Ride's or a Novice ride's route only, so keyed on those alone. */}
        {steepGradesFor(preset) && <SteepGradeKey />}
        {/* v0.10.0: the route's hazard marks, drawn on a route only, with or without the stress map. Last in the
            section (the owner, 2026-10-20: "put it at the bottom"). */}
        <RouteHazardKey />
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

      {/* The switch and its two filters, its key and help; the list along the route is the route's fold. */}
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
        title={t("Trails and terrain")}
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
        {/* The owner, 2026-10-19: "include the legend within the accordion settings in layers". Each layer's key
            sits under its own switch while it is on, as the climbs' does (ClimbsLayerControls). */}
        <MtbTrailLegend />
        <ClimbsLayerControls on={climbsOn} onChange={changeClimbsOn} from={climbsFrom} onFromChange={changeClimbsFrom} status={climbsStatus} items={climbsAlong} along={false} />
        <TopoLinesSwitch on={showTopoLines} onChange={(on) => setTopoLines(on)} available={topoReady} />
      </LayerSection>

      {/* v0.8.0: the Scenic layer, one switch, off by default, after Trails and terrain; Plan's alone. */}
      {scenic && <ScenicSection {...scenic} drawn={scenicDrawn} />}
      {/* v0.9.1: DDOT's permits, flagged only, one switch, off by default; Plan's alone. */}
      {permits && <PermitsSection {...permits} />}

      {/* Mockup v3's line; the Mass Ride layers sheet itself waits on FOLLOWUP-MASSRIDE-MAP (324-334). */}
      {!federalShown(preset, true) && <p className="hint mass-ride-layers">{MASS_RIDE_LAYERS_NOTE}</p>}
    </SheetFrame>
  );
}

/** The stress section's key: Mass Ride's capacity bands, or the stress levels and what each zoom shows. */
function StressSectionKey(props: { massMap: boolean; stress: StressAvailability; stressVisible: boolean; preset: PresetId; zoom: number | null; facilitiesShown: ReadonlySet<string> }) {
  const { massMap, stress, stressVisible, preset, zoom, facilitiesShown } = props;
  if (stress !== "available") return null;
  return massMap ? (
    <>
      <MassLegend />
      <MassZoomNotes zoom={zoom} shown={stressVisible} />
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
  /** Load route's popup opens the panel's file picker (GpxPanel); a file it cannot open opens this sheet to say why. */
  fileInput?: (input: HTMLInputElement | null) => void;
  onOpenFailed?: () => void;
  onPick?: () => void;
  refineImported: (next: LonLat[]) => void;
  getMap: () => MapLibreMap | null;
  /** Download GPX: the page checks closures first, and an unedited opened file downloads as it came. */
  downloadRoute: (said?: (line: string) => void) => void;
  /** Plan only: download a FIT or TCX course or a PDF cue sheet (GpxPanel); absent in Go, which offers GPX alone. */
  downloadCourse?: (format: FileFormat, profile: DeviceProfileId, said: Said) => void;
  /** Send to Garmin: the route shown as a FIT course, handed to the phone for Garmin Connect (GpxPanel). */
  sendToGarmin?: (said: Said) => void;
  /** Send to Wahoo: the route shown as a FIT course, added to the rider's Wahoo app (GpxPanel; once connected). */
  sendToWahoo?: (said: Said) => void;
  /** Plan only: snap an opened track to the map's ways (GpxPanel, lib/gpxMatch.ts); absent in Go. */
  match?: GpxPanelProps["match"];
  /** Save route (signed in) and Share, for the route shown or the file opened (RoutePanel.tsx ShareControls); null with neither. */
  shareControls: ReactNode;
  /** Your routes: the saved ones and the ones kept for offline, with a search (YourRoutes.tsx); null with neither. */
  routes: ReactNode;
}

/** The GPX sheet. */
export function GpxSheet(props: GpxSheetProps) {
  const { nav, shown, routedPoints, routedLoop, federalRoute, points, status, imported, openImported, fileInput, onOpenFailed, onPick, refineImported, getMap, downloadRoute, downloadCourse, sendToGarmin, sendToWahoo, match, shareControls, routes } = props;
  return (
    <SheetFrame id="sheet-gpx" title={SHEET_TITLES.gpx} open={nav.view === "gpx"} onBack={nav.back} backLabel={nav.backLabel("gpx")} popup>
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
        fileInput={fileInput}
        onOpenFailed={onOpenFailed}
        onPick={onPick}
        onRefine={refineImported}
        getMap={getMap}
        onDownload={downloadRoute}
        onDownloadCourse={downloadCourse}
        onSendToGarmin={sendToGarmin}
        onSendToWahoo={sendToWahoo}
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

/**
 * My Go (the owner's choice 2): the Home that Go's Home chip rides to and Go's ride type, saved to the account
 * when signed in and on this device when not. First
 * in Settings: Home is what a rider comes here to set (Settings tidy, Stephen 2026-10-19: "still very clunky").
 */
function MyGoSection({ controls, open }: { controls: MyGoControls; open: boolean }) {
  const { myGo, signedIn, save, setHome, said, geoGate, searchBias } = controls;
  const [infoOpen, setInfoOpen] = useState(false);
  // A Home set is one line with Change (Settings scrolling, Stephen 2026-10-22: "still a lot of scrolling"); the search
  // and Clear Home open under Change, and stay open while no Home is set.
  const [changing, setChanging] = useState(false);
  const changeRef = useRef<HTMLButtonElement>(null);
  const homeBox = useRef<HTMLDivElement>(null);
  // The Home's place and name, not the object: an account's answer to any save brings a new copy of the same Home.
  const homeKey = myGo.home ? `${myGo.home.point[0]},${myGo.home.point[1]},${myGo.home.label}` : "";
  const homeWas = useRef(homeKey);
  useEffect(() => {
    if (homeWas.current === homeKey) return;
    homeWas.current = homeKey;
    if (!homeKey) return;
    // A Home picked (the first, or under Change): back to its line. The search the focus was in is gone, so the
    // focus goes to Change; a Home that arrives (the account's) while the focus is elsewhere leaves it there.
    const active = document.activeElement;
    const lost = !active || active === document.body || !!homeBox.current?.contains(active);
    setChanging(false);
    if (lost) requestAnimationFrame(() => changeRef.current?.focus());
  }, [homeKey]);
  // Leaving Settings closes an open Change (the sheet stays mounted), so the next visit opens on the Home's line.
  useEffect(() => {
    if (!open) setChanging(false);
  }, [open]);
  const openChange = () => {
    setChanging(true);
    requestAnimationFrame(() => homeBox.current?.querySelector<HTMLInputElement>("input")?.focus());
  };
  const keepHome = () => {
    setChanging(false);
    requestAnimationFrame(() => changeRef.current?.focus());
  };
  return (
    <section aria-labelledby="settings-my-go-heading" className="settings-group my-go">
      <div className="setting-line">
        <h3 id="settings-my-go-heading">{t("My Go")}</h3>
        <InfoButton open={infoOpen} onToggle={() => setInfoOpen((was) => !was)} controls="settings-my-go-info" about={t("My Go")} />
      </div>
      <p className="hint setting-info" id="settings-my-go-info" hidden={!infoOpen}>
        {signedIn ? t("Kept with your Discord account, on every device you sign in on.") : t("Kept on this device. Sign in to keep it with your account.")}
      </p>
      {/* The same Home sheet as Go's (lib/homeSet.ts), without the map way: the map is behind Settings. */}
      <div className="my-go-home" ref={homeBox}>
        {myGo.home && !changing ? (
          <div className="setting-line home-line">
            <p className="home-now" id="settings-home-now">
              <strong>{t("Home:")} </strong>
              {homeName(myGo.home)}
            </p>
            <button type="button" ref={changeRef} className="secondary" aria-label={t("Change Home")} aria-describedby="settings-home-now" onClick={openChange}>
              {t("Change")}
            </button>
            <span className="info-spacer" aria-hidden="true" />
          </div>
        ) : (
          <>
            {!myGo.home && (
              <p>
                <strong>{t("Home:")} </strong>{t("not set")}
              </p>
            )}
            <HomeSetter home={myGo.home} geoGate={geoGate} searchBias={searchBias} onPlace={(place: Place) => setHome(homeFromPlace(place))} onClear={() => setHome(null)} />
            {/* Change pressed by mistake: Cancel keeps the Home and goes back to its line. */}
            {myGo.home && (
              <button type="button" className="secondary home-cancel" onClick={keepHome}>
                {t("Cancel")}
              </button>
            )}
          </>
        )}
      </div>
      <SettingRow infoId="settings-go-ride-info" about="Default ride type">
        {/* Named for what it is, and grouped as Go's Ride sheet and Plan's dialog group the ride types (P3). */}
        <SettingSelect
          label={t("Default ride type")}
          value={myGo.ride ?? "default"}
          options={PRESETS.filter((p) => p.id !== "mass-ride").map((p) => [p.id, presetSaid(p.id)] as const)}
          groups={rideTypeSections()}
          onChange={(ride) => save({ ...myGo, ride: ride === "default" ? null : ride })}
        />
      </SettingRow>
      <p className="hint my-go-said" role="status">
        {said}
      </p>
    </section>
  );
}

export interface SettingsSheetProps {
  nav: SheetNav;
  /** What Garmin's return said (lib/garminLink.ts garminReturnFrom), once, or null. */
  garminReturned?: string | null;
  /** What Wahoo's return said (lib/wahooLink.ts wahooReturnFrom), once, or null. */
  wahooReturned?: string | null;
  settingsHeadingRef: RefObject<HTMLHeadingElement | null>;
  ridePrefs: RidePrefs;
  changeRidePrefs: (next: RidePrefs) => void;
  /** The ride's text size: here, and on the ride's own button (the owner, 2026-10-20), the one kept choice. */
  rideText: { size: RideTextSize; onChange: (size: RideTextSize) => void };
  /** The rider and bike weight: its line and Change, never the number (lib/weightDialog.ts). */
  weight: { saved: StoredWeight | null; split: Split; onSave: (weight: StoredWeight) => void; onClear: () => void };
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

/** Settings' tabs (the owner, 2026-10-28: "Settings = display, riding, account"; routes stay in Save & load). */
export const SETTINGS_TABS = ["riding", "display", "account"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
const SETTINGS_TAB_LABEL: Record<SettingsTab, string> = { riding: t("Riding"), display: t("Display"), account: t("Account") };

/**
 * The tab row: a tablist of three, the one shown selected (its underline and weight, not colour alone). The arrow
 * keys, Home and End move between them and show the one they reach; Tab goes on into the tab shown.
 */
function SettingsTabs({ tab, onTab, label }: { tab: SettingsTab; onTab: (tab: SettingsTab) => void; label: string }) {
  const row = useRef<HTMLDivElement>(null);
  const move = (next: SettingsTab) => {
    onTab(next);
    row.current?.querySelector<HTMLButtonElement>(`#settings-tab-${next}`)?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = SETTINGS_TABS.indexOf(tab);
    const to =
      event.key === "ArrowRight" ? (at + 1) % SETTINGS_TABS.length
      : event.key === "ArrowLeft" ? (at + SETTINGS_TABS.length - 1) % SETTINGS_TABS.length
      : event.key === "Home" ? 0
      : event.key === "End" ? SETTINGS_TABS.length - 1
      : null;
    if (to === null) return;
    event.preventDefault();
    move(SETTINGS_TABS[to]);
  };
  return (
    <div ref={row} role="tablist" aria-label={label} className="settings-tabs" onKeyDown={onKeyDown}>
      {SETTINGS_TABS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          id={`settings-tab-${id}`}
          className="settings-tab"
          aria-selected={tab === id}
          aria-controls={`settings-panel-${id}`}
          tabIndex={tab === id ? 0 : -1}
          onClick={() => onTab(id)}
        >
          {SETTINGS_TAB_LABEL[id]}
        </button>
      ))}
    </div>
  );
}

/** The Settings sheet (Go's Menu): Riding (My Go first), Display and Account, each a tab, most used first. */
export function SettingsSheet(props: SettingsSheetProps) {
  const { nav, settingsHeadingRef, ridePrefs, changeRidePrefs, announce, linkNote, accessMode, toggleAccessMode, myGo, mode, menu, announcements, signInAvailable, garminReturned, wahooReturned } = props;
  const go = mode === "go";
  // Back from Garmin or Wahoo, Settings opens on Account, where its line says what happened; otherwise on Riding,
  // and then on the tab last shown.
  const [tab, setTab] = useState<SettingsTab>(() => (garminReturned || wahooReturned ? "account" : "riding"));
  return (
    <SheetFrame
      id="sheet-settings"
      title={go ? MENU_TITLE : SHEET_TITLES.settings}
      open={nav.view === "settings"}
      onBack={nav.back}
      backLabel={nav.backLabel("settings")}
      popup
      headingRef={settingsHeadingRef}
    >
      {go && (
        <nav className="menu-pages" aria-label={t("Pages")}>
          <button type="button" className="secondary menu-page" onClick={menu.onPlan}>
            <Icon name="list" />
            {t("Plan")}
          </button>
          <button type="button" className="secondary menu-page" onClick={(event) => menu.onSuggest(event.currentTarget)}>
            <Icon name="flag" />
            {t("Reports")}
          </button>
          <button type="button" className="secondary menu-page" onClick={(event) => menu.onGpx(event.currentTarget)}>
            <Icon name="file" />
            {SAVE_LOAD}
          </button>
          {menu.onReview && (
            <button type="button" className="secondary menu-page" onClick={(event) => menu.onReview?.(event.currentTarget)}>
              <Icon name="shield" />
              {t("Review")}
            </button>
          )}
        </nav>
      )}
      {/* Three tabs, each about one screen (the owner, 2026-10-28: "A lot of destinations require endless scrolling"):
          Riding (My Go with Home, then the ride's voice and weight), Display, and Account with the app and About. */}
      <SettingsTabs tab={tab} onTab={setTab} label={go ? MENU_TITLE : SHEET_TITLES.settings} />
      <div role="tabpanel" id="settings-panel-riding" aria-labelledby="settings-tab-riding" className="settings-panel" hidden={tab !== "riding"}>
      {/* Most used first (Settings tidy, Stephen 2026-10-19): My Go with Home, then Riding. */}
      <MyGoSection controls={myGo} open={nav.view === "settings"} />
      {/* Ride mode's choices (WEB-NAV-plan.md section 3): kept on this device. Its tab names it on screen. */}
      <section aria-labelledby="settings-ride-heading" className="settings-group">
        <h3 id="settings-ride-heading" className="visually-hidden">{t("Riding")}</h3>
        <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="settings-ride" compact />
        {/* Rider and bike weight, for how hard hills feel (the owner, 2026-10-18: "probably belongs in settings"); set once, so last. */}
        <div className="setting-row weight-row">
          <div className="setting-line">
            <WeightSetting {...props.weight} />
            <span className="info-spacer" aria-hidden="true" />
          </div>
        </div>
      </section>
      </div>
      <div role="tabpanel" id="settings-panel-display" aria-labelledby="settings-tab-display" className="settings-panel" hidden={tab !== "display"}>
      <section aria-labelledby="settings-display-heading" className="settings-group">
        <h3 id="settings-display-heading" className="visually-hidden">{t("Display")}</h3>
        {/* Accessibility mode (OWNER-DECISIONS 455) first, the same state as the page's first button: the one shared mode
            (the owner: "Accessibility = one shared mode"), which turns High contrast and Large text during a ride on or
            off with it. Those two follow under it, indented, to set apart. */}
        <SettingRow infoId="settings-access-hint" about="accessibility mode" info={`${t(ACCESS_HELP)} ${t(ACCESS_FINE_TUNE)}`} className="a11y-setting">
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
              {t(ACCESS_LABEL)}
            </span>
            <span className="switch-state" aria-hidden="true">
              {accessMode ? t("On") : t("Off")}
            </span>
          </button>
        </SettingRow>
        <div className="access-parts" role="group" aria-labelledby="settings-access-label">
          <ContrastRow />
          {/* Large text in a ride (it replaced Big text): here, and on the ride's own button, the same choice. */}
          <SettingRow infoId="settings-big-text-info" about="large text" info={RIDE_TEXT_HELP} className="big-text-row">
            <button
              type="button"
              role="switch"
              className="switch"
              aria-checked={props.rideText.size === "large"}
              aria-labelledby="settings-big-text-label"
              aria-describedby="settings-big-text-info"
              onClick={() => props.rideText.onChange(props.rideText.size === "large" ? "normal" : "large")}
            >
              <span id="settings-big-text-label" className="switch-label">
                {RIDE_TEXT_LABEL}
              </span>
              <span className="switch-state" aria-hidden="true">
                {props.rideText.size === "large" ? t("On") : t("Off")}
              </span>
            </button>
          </SettingRow>
        </div>
        {/* How much screen readers are told (the owner, 2026-10-11 20:23 UTC): Brief or Full; unset, Go is brief. Named
            Screen-reader detail (it was Announcements), so it is not taken for the ride's How much to say. */}
        <SettingRow
          infoId="settings-announce-info"
          about="screen-reader detail"
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
            label={t("Screen-reader detail")}
            value={announcements.level}
            options={(["brief", "full"] as const).map((level) => [level, shortLabel(ANNOUNCE_LABEL[level])] as const)}
            onChange={(level) => announcements.choose(level)}
            describedBy="settings-announce-info"
          />
        </SettingRow>
        {/* The app's language (the owner, 2026-10-27: "compatible with multiple languages"): unset, the phone's own. */}
        <LanguageSetting />
      </section>
      </div>
      <div role="tabpanel" id="settings-panel-account" aria-labelledby="settings-tab-account" className="settings-panel" hidden={tab !== "account"}>
      {/* Account: never an empty heading (signed out on a server that cannot sign anyone in, it has nothing to hold).
          Its tab names it on screen; the installable app and About follow it in the tab. */}
      {(myGo.signedIn || signInAvailable) && (
        <section aria-labelledby="settings-signin-heading" className="settings-group">
          <h3 id="settings-signin-heading" className="visually-hidden">{t("Account")}</h3>
          {myGo.signedIn ? (
            <div className="account-line">
              <p className="hint signed-in">
                <Icon name="user" size={16} /> {t("Signed in with Discord.")}
              </p>
              <SignOutForm />
              <span className="info-spacer" aria-hidden="true" />
            </div>
          ) : signInAvailable ? (
            // The plan's one line (item 4); the link is its first words. The plan in hand is kept across the round trip.
            <p className="hint sign-in-line">
              <a href="/auth/login" onClick={(e) => isPlainClick(e) && rememberPlanForSignIn(tabSession(), window.location.hash, linkNote !== "")}>
                {t("Sign in with Discord")}
              </a>
              {t(SIGN_IN_LINE.slice("Sign in with Discord".length))}
            </p>
          ) : null}
          {/* Assistant apps connected through the site's MCP connector, and how to connect one (the owner, 2026-10-25). */}
          {myGo.signedIn && <AssistantAppsSetting />}
          {/* Send to Garmin straight into Garmin Connect (the owner, 2026-10-23); shown only where the server can. */}
          {myGo.signedIn && <GarminSetting returned={garminReturned ?? null} />}
          {/* Send to Wahoo straight into the Wahoo app (the owner, 2026-10-23); shown only where the server can. */}
          {myGo.signedIn && <WahooSetting returned={wahooReturned ?? null} />}
          {/* A page of its own (core.account_deletion), the same one the web offers without the app: it says what goes
              and what is kept, and asks once. Last: nobody needs it often. */}
          {myGo.signedIn && (
            <p className="delete-account">
              <a href={DELETE_ACCOUNT_PAGE}>{t("Delete account")}</a>
            </p>
          )}
        </section>
      )}
      {/* The installable app (WEB-NAV-plan.md section 8, P4), under its own heading when the browser offers it. The
          routes saved and kept for offline are in Save and load (YourRoutes.tsx; the owner, 2026-10-18). */}
      <InstallOffer idBase="settings-install" onSay={announce} />
      {/* The documentation (the owner, 2026-10-19): one link, last, under its own heading. */}
      <section aria-labelledby="settings-about-heading" className="settings-group">
        <h3 id="settings-about-heading">{t("About")}</h3>
        {/* Side by side when they fit: two short links, one line. */}
        <div className="about-links">
          <DocsPageLink />
          {/* The privacy policy (core.privacy_policy): here, where it shows signed in or out and on any server. */}
          <p className="privacy-link">
            <a href={PRIVACY_PAGE} onClick={(e) => isPlainClick(e) && rememberPlanForPage(tabSession(), window.location.hash)}>
              {t("Privacy policy")}
            </a>
          </p>
        </div>
        {/* The version (lib/appVersion.ts): here and in the map's Help, since Plan's phone sheet has no title row (P10). */}
        {APP_VERSION && <p className="hint settings-version">{versionSaid()}</p>}
      </section>
      </div>
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
 * Reports (Suggest until 2026-10-21; the owner's choice 6): the one way in to the suggest tools. Each starts from a road on the map
 * (the road panel's "Suggest a change…": a road's level, a junction, a Mass Ride hazard), so this says how
 * to get there and opens the panel at the map's centre. The 311 checklist (Report311Log.tsx) lists the problems
 * logged from a ride's 311 button or the road panel's Log for 311, by the website that takes them.
 */
export function SuggestSheet({ nav, roadInfoAtCentre, onReview }: SuggestSheetProps) {
  return (
    <SheetFrame id="sheet-suggest" title={SHEET_TITLES.suggest} open={nav.view === "suggest"} onBack={nav.back} backLabel={nav.backLabel("suggest")} popup>
      {/* The 311 checklist first: the sheet is Reports (Stephen, 2026-10-21), and the ride summary's Open Reports lands here. */}
      <Report311Log />
      <section aria-labelledby="suggest-map-heading" className="settings-group">
        <h3 id="suggest-map-heading">{t("A road or a junction")}</h3>
        <p className="hint">
          {suggestHint(looksLikePhone())}
        </p>
        <button type="button" className="secondary suggest-at-centre" onClick={roadInfoAtCentre}>
          <Icon name="road" />
          {t("The road at the map's center")}
        </button>
      </section>
      {onReview && (
        <section aria-labelledby="suggest-review-heading" className="settings-group">
          <h3 id="suggest-review-heading">{t("Review")}</h3>
          <p className="hint">{t("Riders' suggestions, Mass Ride hazard reports and closure reports are in Review, beside Go and Plan.")}</p>
          <button type="button" className="secondary open-review" onClick={(event) => onReview(event.currentTarget)}>
            <Icon name="shield" />
            {t("Review suggestions")}
          </button>
        </section>
      )}
    </SheetFrame>
  );
}

/** The map's Water chip: the nearest water, restroom or Metro station (the finder that was a fold in Points). */
export function NearestSheet({ nav, children }: { nav: SheetNav; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-nearest" title={SHEET_TITLES.nearest} open={nav.view === "nearest"} onBack={nav.back} backLabel={nav.backLabel("nearest")} popup>
      {children}
    </SheetFrame>
  );
}

/** The cuisine chips over Find food (the mockup's Food sheet): each one searches for it. */
// Farm stands (v0.7.0, the owner 2026-10-14: "Lots of places are selling apples in the fall"), with the apple.
// Grocery (the owner, 2026-10-28): grocery stores and supermarkets nearest the start, from the geocoder (lib/grocery.ts).
export const FOOD_CHIPS = ["Crab", "Coffee", "Pizza", "Tacos", "Ice cream", "Farm stands", "Grocery"] as const;
const FOOD_CHIP_ICON: Partial<Record<(typeof FOOD_CHIPS)[number], IconName>> = { "Farm stands": "apple", Grocery: "shop" };

/** The cuisine chips, under Find food's search box: one row that scrolls sideways (the 2026-10-28 audit, P7: results first). */
export function FoodChips({ onChip }: { onChip: (food: string) => void }) {
  return (
    <div className="chip-row food-chips" role="group" aria-label={t("Quick searches")}>
      {FOOD_CHIPS.map((food) => (
        <button key={food} type="button" className="chip" onClick={() => onChip(food.toLowerCase())}>
          <Icon name={FOOD_CHIP_ICON[food] ?? "food"} size={16} />
          {t(food)}
        </button>
      ))}
    </div>
  );
}

/** The map's Food chip: Find food (the panel that was a fold in Points), its cuisine chips (FoodChips) under its search box. */
export function FoodSheet({ nav, children }: { nav: SheetNav; children: ReactNode }) {
  return (
    <SheetFrame id="sheet-food" title={SHEET_TITLES.food} open={nav.view === "food"} onBack={nav.back} backLabel={nav.backLabel("food")} popup>
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
    <SheetFrame id="sheet-ride" title={SHEET_TITLES.ride} open={nav.view === "ride"} onBack={nav.back} backLabel={nav.backLabel("ride")} popup>
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
  const scopeRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);
  // Review F9: the common types first, the rest in their groups, folded (the one in use opens its group); a search
  // shows every match flat. The class is ride-sheet-group: .ride-group is the group ride's overlay (RideGroup.tsx).
  // Favorites (Stephen 2026-10-19) come before Common, each card with its star (lib/favoriteRides.ts).
  const favorites = useFavoriteRides();
  const { favorites: favs, common, groups, folded } = rideSections(query, undefined, favorites);
  const star = { favorites, onFavorite: (id: PresetId) => toggleFromPicker(id, scopeRef.current) };
  return (
    <section ref={scopeRef} className="ride-groups" aria-labelledby="ride-sheet-types">
      <h3 id="ride-sheet-types" className="visually-hidden">
        {t("Every ride type")}
      </h3>
      <RideTypeSearch id="ride-sheet-search" query={query} onQuery={setQuery} count={rideTypeCount(filterRideGroups(query))} />
      {favs.length > 0 && (
        <section className="ride-sheet-group" aria-labelledby="ride-sheet-favorites">
          <h4 id="ride-sheet-favorites">{t("Favorites")}</h4>
          <RideTypeCards ids={favs} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} {...star} />
        </section>
      )}
      {common.length > 0 && (
        <section className="ride-sheet-group" aria-labelledby="ride-sheet-common">
          <h4 id="ride-sheet-common">{t("Common")}</h4>
          <RideTypeCards ids={common} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} {...star} />
        </section>
      )}
      {groups.map((group) =>
        folded ? (
          <details key={group.id} className="fold ride-sheet-fold" open={group.ids.includes(preset) || undefined}>
            <summary>{`${group.label} (${group.ids.length})`}</summary>
            <div className="fold-body">
              <RideTypeCards ids={group.ids} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} {...star} />
            </div>
          </details>
        ) : (
          <section key={group.id} className="ride-sheet-group" aria-labelledby={`ride-sheet-${group.id}`}>
            <h4 id={`ride-sheet-${group.id}`}>{group.label}</h4>
            <RideTypeCards ids={group.ids} preset={preset} onPick={onPick} idPrefix="ride-sheet" icon={rideIcon} {...star} />
          </section>
        ),
      )}
    </section>
  );
}

/**
 * Go's quick ride type chips and the More button, each chip a toggle button. P3: one row that scrolls sideways
 * (styles.css .ride-chips), the ride type in use first and pressed (lib/myGo.ts goRideChips), so it is always in
 * view; the row goes back to its start when the ride type changes. Where the rider has moved the sliders from the
 * ride type's start (`changed`), its chip says so: "(changed)" shown, the whole of it heard.
 */
export function RideChips({
  ids,
  preset,
  onPick,
  more,
  label,
  ownHint,
  own,
  changed = false,
}: {
  ids: readonly PresetId[];
  preset: PresetId;
  onPick: (id: PresetId) => void;
  more?: (opener: HTMLElement) => void;
  /** The chips' group name; leave it out where a heading already names them. */
  label?: string;
  /** Go: the rider's own ride type (My Go) is described as such; `own` is which chip it is (the first, if left out). */
  ownHint?: string;
  own?: PresetId;
  /** The sliders are not where the ride type in use starts them (lib/rideTypeDialog.ts isCustom). */
  changed?: boolean;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    rowRef.current?.scrollTo?.({ left: 0 });
  }, [preset]);
  const ownId = own ?? ids[0];
  return (
    <div ref={rowRef} className="chip-row ride-chips" role={label ? "group" : undefined} aria-label={label}>
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className="chip ride-type-chip"
          aria-pressed={preset === id}
          onClick={() => onPick(id)}
          aria-describedby={ownHint && id === ownId ? "ride-own-hint" : undefined}
        >
          <Icon name={RIDE_ICON[id] ?? "bike"} size={18} />
          <PresetName id={id} />
          {changed && preset === id && (
            <>
              <span className="ride-changed" aria-hidden="true">
                {t("(changed)")}
              </span>
              <span className="visually-hidden">{t(", settings changed from this ride type's start")}</span>
            </>
          )}
        </button>
      ))}
      {more && (
        <button type="button" className="chip ride-more" onClick={(event) => more(event.currentTarget)} aria-describedby="ride-more-hint">
          <Icon name="more" size={18} />
          {t("Ride type & settings")}
        </button>
      )}
      {more && (
        <span id="ride-more-hint" hidden>
          {t("Every ride type and setting.")}
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
