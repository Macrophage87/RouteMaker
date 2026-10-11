import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
import { RoadInfoDialog } from "./RoadInfoDialog.tsx";
import { MapTools } from "./MapTools.tsx";
import { ACCESS_LABEL, accessModeToggle, readAccessMode, writeAccessMode } from "./lib/accessMode.ts";
import { placeAtSpot, requestAfterClose, type InfoRequest } from "./lib/roadInfo.ts";
import { stationNearSpot } from "./lib/stationLinks.ts";
import { canDragLine, dropStillValid, insertIntoRide, legEnds, legPoints } from "./lib/lineEdit.ts";
import { EditHistory, isRedoKey, isUndoKey, typesText } from "./lib/editHistory.ts";
import { requestRoute, type RouteResponse, type RouteResult } from "./lib/api.ts";
import { COVERAGE_BBOX, MAX_POINTS, addPoint, insideCoverage, type LonLat } from "./lib/geo.ts";
import { formatSeconds } from "./lib/format.ts";
import { presetLabel, type PresetId } from "./lib/presets.ts";
import { atFromHash, decodePlan, encodePlan } from "./lib/planHash.ts";
import { RouteScheduler, type SchedulerState } from "./lib/routeScheduler.ts";
import { confirmedUpTo, sendsConfirmation, spanKm } from "./lib/longRide.ts";
import { forgetPlan, planToOpen, tabSession } from "./lib/signIn.ts";
import { STILL_PLANNING_AFTER_MS, announceRoute, stillPlanningSaid } from "./lib/summary.ts";
import { focusesPlanButton, opensSheet, sheetOrder, type SheetSection } from "./lib/sheet.ts";
import { neutralPaletteSearch, setMtbTrails, setRoutableMtb } from "./stressStyle.js";
import { setTopoLines, topoAvailable, useTopoLines } from "./lib/topoLines.ts";
import { isMtb, mtbChosen, mtbLevelOf } from "./lib/mtbMode.ts";
import { choose as chooseRideType } from "./lib/rideTypeDialog.ts";
import { useHighStressLanes, useMtbTrails } from "./useStressStyle.ts";
import { useStressStyle } from "./useStressStyle.ts";
import { ANNOUNCE_SETTLE_MS } from "./lib/settle.ts";
import { skipToPlanner, SKIP_LINK_TEXT, SKIP_TO_RIDE_TEXT } from "./lib/skipLink.ts";
import { BetaBanner, betaReportUrl, isBetaBuild } from "./lib/betaBanner.ts";
import { announceHow } from "./lib/candidates.ts";
import { canReverse, loopStops, loopView, reversedPoints } from "./lib/loop.ts";
import { FINDING_ORDER_SAID, STILL_FINDING_ORDER_SAID, applyAnswer, requestStopOrder, stopsThatMove } from "./lib/stopOrder.ts";
import { addedSaid, insertedSaid, loopChangeSaid, removedSaid, reversedSaid, reverseUnavailableHint, stationSaid } from "./lib/pointText.ts";
import { avoidNearSpot, shownRoute } from "./lib/avoidJunctions.ts";
import { shownNear } from "./lib/junctionSuggest.ts";
import { RideMode, startRideGesture, type RideView } from "./RideMode.tsx";
import { readRidePrefs, writeRidePrefs, type RidePrefs } from "./lib/rideOutput.ts";
import { activePins, chosenSaid, withStations, type NearbyStation, type Pins, type StationAction } from "./lib/stations.ts";
import { bikeshareOf } from "./lib/bikeshare.ts";
import { carries, startDials, trailsAreOff, type Dials } from "./lib/dials.ts";
import { WeightStore, withWeight, type StoredWeight } from "./lib/weight.ts";
import { stationEdit, type RailVisibility, type StationRole } from "./lib/railStations.ts";
import { RAIL_STATIONS, WMATA_SLUGS, stationEntranceForPlace } from "./lib/railData.ts";
import { federalShown, type FederalData } from "./lib/federalLand.ts";
import { FEDERAL_POINTS_NONE, type FederalStatus } from "./lib/federalLegend.ts";
import { federalAreaAt, federalRouteLines, pointAreas, stopWarningShort } from "./lib/federalStops.ts";
import { addCoverageMask, fetchCoverage, watchForCapacity, watchForFacilities, watchZoom } from "./lib/mapGlue.ts";
import { isMassRide, massBandsChangeSaid, massBandsSaid } from "./lib/massCapacity.ts";
import { movePoint, planEdits, travelSaid, type Snapshot as PlanSnapshot } from "./lib/planEdits.ts";
import { mapWhen } from "./lib/rideTime.ts";
import { registerStressProtocol } from "./lib/stressProtocol.ts";
import { corridorStress } from "./lib/corridorStore.ts";
import { refreshStressTiles } from "./lib/mapStyle.ts";
import * as maplibregl from "maplibre-gl";
import {
  FINDING_LOCATION,
  LOCATE_MESSAGES,
  LOCATION_OUTSIDE,
  browserEnv,
  linkLocationNote,
  locate,
  locateSupport,
  maxPointsNotice,
  locateGate,
  movedFromHere,
  placeFix,
  type Fix,
  type LocateResult,
} from "./lib/geolocation.ts";
import { usePlaceNames } from "./usePlaceNames.ts";
import { pickIntoPlan, placeFromSearch, type Place, type PlaceChoice } from "./lib/geocode.ts";
import { BottomBar } from "./Sidebar.tsx";
import {
  copyText,
  PLANNER_TITLE,
  focusOnViewChange,
  linkSaidFor,
  linkSpokenFor,
  linkToCopy,
  noticeSaidElsewhere,
  rescueCompactFocus,
  selectionCopy,
  type BarItem,
  type PanelView,
  type ViewCause,
} from "./lib/sidebar.ts";
import { canShareLink, shareContent, shareLink, shareSaidFor } from "./lib/share.ts";
import type { ImportedPlan } from "./lib/gpxPlan.ts";
import { loadWaterRestrooms, readWaterPrefs, saveWaterPrefs, waterAlongRoute, waterTitle, waterVisible, type WaterAlong, type WaterPoint, type WaterPrefs, type WaterStatus } from "./lib/waterRestrooms.ts";
import waterRestroomsUrl from "./amenity-data/water-restrooms.json?url";
import { climbsAlongRoute, loadClimbs, readClimbsOn, saveClimbsOn, type Climb, type ClimbsStatus } from "./lib/climbs.ts";
// `no-inline`: the file is small until the build host fills it, and an inlined data: URL is refused by
// the edge's connect-src 'self' (Caddyfile), so it stays its own hashed file under /assets/.
import climbsUrl from "./climb-data/climbs.json?url&no-inline";
import {
  FOOD_EMPTY_QUERY,
  FOOD_NOT_LOADED,
  FOOD_PAGE,
  NO_FOOD_DATA,
  foodFoundSaid,
  loadFood,
  foodMoreSaid,
  foodTerms,
  routeForDetour,
  searchFood,
  type Bounds,
  type FoodPlace,
  type FoodResult,
  type FoodScope,
} from "./lib/food.ts";
import { FoodFinder } from "./lib/foodFinder.ts";
// `no-inline`, as climbs.json: the committed file is a few bytes until the build host fills it, and
// an inlined data: URL is refused by the edge's connect-src 'self'. Its own hashed file under
// /assets/ also lets the service worker leave it out of the precache (swCore.mjs LAZY_ASSET).
import foodUrl from "./amenity-data/food.json?url&no-inline";
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
import { AppStatusBar, useAppStatus } from "./InstallableApp.tsx";
import { isStandalone } from "./lib/installOffer.ts";
import { keepLastRide, keepRoute, keptAnswerFor, sweepKept } from "./lib/offlineKeep.ts";
import { KEEPING_SAID, keepOffered, keepSaid, keptPlanKey, offlineRouteNotice, routeTitle, type KeptRoute } from "./lib/offlineRoutes.ts";
import { askPersist } from "./lib/offlineRouteStore.ts";
import { namesToKeep, rideAfterImport, type Ride } from "./lib/gpxEdit.ts";
import { fetchHazards, type HazardCollection } from "./lib/massHazards.ts";
import { NARROW, useLongerThan, useNarrow, useSettled } from "./app/hooks.ts";
import { PointsSection, RideSection } from "./app/Planner.tsx";
import { RouteSection, type Status } from "./app/RoutePanel.tsx";
import { FoodSheet, GpxSheet, LayersSheet, LegendSheet, NearestSheet, ReviewSheet, RideChips, RideSheet, SettingsSheet, SuggestSheet, type SheetNav } from "./app/Sheets.tsx";
import { GoSheet, GoTopBar, ModeSwitch, PlanMapChips } from "./app/Go.tsx";
import { NearestFinder } from "./lib/nearestFinder.ts";
import { NearbyStations } from "./NearbyStations.tsx";
import { Fold } from "./Sidebar.tsx";
import { BACK_LABEL, SHEET_TITLES, backFrom, openOnto, type Opened } from "./lib/sidebar.ts";
import { announceLevel, readAnnounceChoice, saysExtra, writeAnnounceChoice, type AnnounceChoice, type AnnounceLevel } from "./lib/announceLevel.ts";
import { letterKeyIndex, letterPlaces, placeLetter } from "./lib/letteredPlaces.ts";
import { keepOptions, optionName, optionPins, optionSaid, optionsKey, pickedOption, type KeptOptions } from "./lib/bikeshareOptions.ts";
import { GO_START_SAID, GO_START_UNAVAILABLE, goDestinationLocating, goDestinationNeedsStart, goPickAction, goStartLine, hasPlanLink, laterMyGoApplies, modeSaid, openingMode, readTabMode, shouldAskGoStart, writeTabMode, type AppMode, type GoStart } from "./lib/appMode.ts";
import { MY_GO_NOT_SAVED, MY_GO_SAVED, MY_GO_SAVED_DEVICE, fetchMyGo, goRideChips, readStartMyGo, saveAccountCopy, saveDeviceMyGo, saveMyGo, type MyGo } from "./lib/myGo.ts";
import { fetchMe, NO_ME, type Me } from "./lib/stressEditor.ts";
import { PRESETS } from "./lib/presets.ts";

// Before the map adds the stress source (MapView, after its first probe).
// With Ride mode's kept tiles behind the network, for dead spots (lib/corridorStore.ts).
registerStressProtocol(maplibregl, undefined, corridorStress);

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

const initialPlan = decodePlan(planToOpen(tabSession(), window.location.hash));

// Go or Plan (lib/appMode.ts; the owner's choices 1 and 2 of 2026-10-11): the tab's own view, else Plan for a
// link with a plan in it, else My Go's Open in (the account's copy or this device's), else by screen size.
const START_MY_GO = readStartMyGo();
/** A Go sheet's way back: to the map and the Go sheet, not a planner it does not show. */
const GO_CLOSE_LABEL = "Close";
const PLAN_LINK = hasPlanLink(window.location.hash) || initialPlan.points.length > 0;
const OPENING = openingMode({ tab: readTabMode(), planLink: PLAN_LINK, openIn: START_MY_GO.myGo.openIn, wide: !window.matchMedia(NARROW).matches });
// Go with nothing linked starts on My Go's ride type (the rider's saved settings, used as they are).
const GO_START_RIDE = OPENING.mode === "go" && !PLAN_LINK && START_MY_GO.myGo.ride ? START_MY_GO.myGo.ride : null;
// A spot link (`#at=lon,lat`, a rider suggestion's Discord post): the map opens there.
const OPEN_AT = atFromHash(window.location.hash);

/** The points notice for a point outside the map, from a click, a station, or the rider's location. */
/** During a ride the map takes no edits and shows no plan pins (plan Q2: the plan stays as started). */
const NO_POINTS: LonLat[] = [];
const ignore = () => undefined;

const OUTSIDE_NOTICE = "That point is outside the area this map covers (the DC region to Baltimore).";

export function App() {
  const [points, setPoints] = useState<LonLat[]>(initialPlan.points);
  const [preset, setPreset] = useState<PresetId>(GO_START_RIDE ?? initialPlan.preset);
  const [dials, setDials] = useState<Dials>(() => (GO_START_RIDE ? startDials(GO_START_RIDE) : initialPlan.dials));
  // Go or Plan (lib/appMode.ts), and why it opened so (a later account My Go may still move it).
  const [mode, setModeState] = useState<AppMode>(OPENING.mode);
  const modeSwitched = useRef(false);
  // The rider's own My Go (lib/myGo.ts): the account's when signed in, this device's when not.
  const [myGo, setMyGo] = useState<MyGo>(START_MY_GO.myGo);
  const [myGoSaid, setMyGoSaid] = useState("");
  // /api/me's flags: signed in (My Go to the account, the Home chip) and an instance admin (Review).
  const [me, setMe] = useState<Me>(NO_ME);
  // Go's sheet on a phone: its smallest (peek: the map gets the screen), half, or all of it.
  const [goSheet, setGoSheet] = useState<"peek" | "half" | "full">("half");
  // The rider and bike weight (OWNER-DECISIONS 313-318): kept apart from `dials`, which
  // the link carries, and added only to the request (planDials).
  const weightStore = useRef<WeightStore | null>(null);
  if (weightStore.current === null) weightStore.current = new WeightStore();
  const [weight, setWeight] = useState<StoredWeight | null>(() => weightStore.current?.load() ?? null);
  const [weightRemembered, setWeightRemembered] = useState(() => weightStore.current?.remembered() ?? false);
  // The stations the rider chose from the nearest-stations lists (OWNER-DECISIONS 466a), each
  // forgotten when its point moves; added to the request only, never to the link.
  const [stationPins, setStationPins] = useState<Pins>({});
  const stationChoice = useMemo(() => activePins(preset, points, stationPins), [preset, points, stationPins]);
  // Mass Ride's ride size (PLAN items 128, 139) only redraws the corker load: it is never sent, so moving it
  // must not plan again. The dials the request is made from leave it out, keyed on what is left.
  const { rideSize, ...routeDials } = dials;
  const routeKey = JSON.stringify(routeDials);
  const planDials = useMemo(
    () => withStations(withWeight(routeDials, weight), stationChoice),
    [routeKey, weight, stationChoice],
  );
  // "Make it a loop" chosen (OWNER-DECISIONS 374): the first point is the start and finish, every later one a stop.
  const loopVias = loopStops(preset, dials.loop);
  // What the planner answered, and which of its routes to choose from is shown
  // (OWNER-DECISIONS 265): 0 is the answer, the others its candidates.
  const [answer, setRoute] = useState<RouteResponse | null>(null);
  const [choice, setChoice] = useState(0);
  // Whether the rider chose the route shown (it is then said as chosen, not as planned: the a11y review's N4).
  const [chosen, setChosen] = useState(false);
  // The way round an Avoid-rated junction shown in place of the planned route (OWNER-DECISIONS 335).
  const [aroundAvoid, setAroundAvoid] = useState(false);
  useEffect(() => {
    setChoice(0);
    setChosen(false);
    setAroundAvoid(false);
  }, [answer]);
  const choose = useCallback((index: number) => {
    setChoice(index);
    setChosen(true);
    setAroundAvoid(false);
  }, []);
  const route = shownRoute(answer, choice, aroundAvoid);
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
  // Topo lines (lib/topoLines.ts; 454): the switch's state is shared with the map; whether the server
  // has the archive is asked once, the first time the layer is on.
  const showTopoLines = useTopoLines();
  const [topoReady, setTopoReady] = useState(true);
  const topoAsked = useRef(false);
  useEffect(() => {
    if (!showTopoLines || topoAsked.current) return;
    topoAsked.current = true;
    void topoAvailable().then(setTopoReady);
  }, [showTopoLines]);
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
  // The Climbs layer (lib/climbs.ts; 454): off until turned on, kept on this device; the data is
  // fetched the first time it is shown. An empty file (before the build host has measured any) is
  // "empty", not "unavailable".
  const [climbsOn, setClimbsOnState] = useState<boolean>(() => readClimbsOn());
  const changeClimbsOn = (on: boolean) => {
    setClimbsOnState(on);
    saveClimbsOn(on);
  };
  const [climbsStatus, setClimbsStatus] = useState<ClimbsStatus>("loading");
  const [climbsData, setClimbsData] = useState<Climb[] | null>(null);
  const climbsLoad = useRef<Promise<Climb[] | null> | null>(null);
  useEffect(() => {
    if (!climbsOn || climbsLoad.current) return;
    setClimbsStatus("loading");
    climbsLoad.current = loadClimbs(climbsUrl).then((data) => {
      if (!data) climbsLoad.current = null;
      setClimbsData(data);
      setClimbsStatus(data === null ? "unavailable" : data.length === 0 ? "empty" : "ready");
      return data;
    });
  }, [climbsOn]);
  // Whether the grey coverage mask is on the map, and whether the stress tiles
  // carry bike-facility data; each legend line is shown only when it is true.
  const [coverageShown, setCoverageShown] = useState(false);
  const [facilitiesShown, setFacilitiesShown] = useState<ReadonlySet<string>>(new Set());
  // The stress tiles carry the Mass Ride capacity (a table built before the column does not): the Mass Ride
  // map, legend and panel are then about riders per minute, and otherwise as they were (OWNER-DECISIONS 325, 387).
  const [capacityTiles, setCapacityTiles] = useState(false);
  const massMap = isMassRide(preset) && capacityTiles;
  // The approved rider-marked hazards (FOLLOWUP-MASSRIDE-MAP part 3; lib/massHazards.ts): asked for when
  // the Mass Ride map shows, and again after an admin approves one; never shown on another ride type (325).
  const [hazards, setHazards] = useState<HazardCollection | null>(null);
  const [hazardsAsked, setHazardsAsked] = useState(0);
  useEffect(() => {
    if (!massMap) return;
    let live = true;
    // After an approval (hazardsAsked > 0) past the browser's cache, so the admin sees the rail now.
    void fetchHazards(window.location.origin, fetch, hazardsAsked > 0).then((found) => {
      if (live) setHazards(found);
    });
    return () => {
      live = false;
    };
  }, [massMap, hazardsAsked]);
  const massHazards = massMap ? hazards : null;
  const [zoom, setZoom] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  // Which view the panel body shows: the planner, or one of the bottom bar's sheets (Map layers,
  // which Legend opens scrolled to the legend, GPX, Settings). The planner stays in the page, hidden,
  // so nothing it holds is lost (OWNER-DECISIONS 312).
  const [view, setView] = useState<PanelView>("planner");
  // With a route shown the points are two or three lines and "Edit points" (the mockup's route view);
  // this opens the search, Add point and the rest again.
  const [editPoints, setEditPoints] = useState(false);
  const barButtons = useRef<Partial<Record<BarItem["id"], HTMLButtonElement | null>>>({});
  // The way back through the sheets (lib/sidebar.ts openOnto, backFrom): each step is the view that was
  // showing and what opened the next sheet (a bar button, a map chip, Go's Menu, Layers' Legend button).
  const opened = useRef<Opened<HTMLElement>[]>([]);
  // Where Back from the top sheet gives the focus: what opened it.
  const backTo = useRef<HTMLElement | null>(null);
  const prevView = useRef<PanelView>("planner");
  // Why the view last changed (lib/sidebar.ts focusOnViewChange): a bar button, Back, or an error or
  // the long-ride question bringing the planner back.
  const viewCause = useRef<ViewCause>("bar");
  const errorRef = useRef<HTMLDivElement>(null);
  const pointsSearchRef = useRef<HTMLDivElement>(null);
  const pointsEditRef = useRef<HTMLDivElement>(null);
  const editPointsRef = useRef<HTMLButtonElement>(null);
  const wasCompact = useRef(false);
  const legendHeadingRef = useRef<HTMLHeadingElement>(null);
  const plannerHeadingRef = useRef<HTMLHeadingElement>(null);
  const settingsHeadingRef = useRef<HTMLHeadingElement>(null);
  // What "Copy link" answered: said politely, and again for a second press. The spoken one adds the
  // location note when the link includes the rider's location (OWNER-DECISIONS 395).
  const [linkSaid, setLinkSaid] = useState("");
  const [linkSpoken, setLinkSpoken] = useState("");
  const linkPresses = useRef(0);
  // Share (owner, 2026-10-10; lib/share.ts): on the page only where the browser has a share sheet.
  const [canShare] = useState(() => canShareLink(navigator, window.location.href));
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
  // Announcements, Brief or Full (Settings > Display): the rider's choice, kept on this device.
  const [announceChoice, setAnnounceChoice] = useState<AnnounceChoice>(() => readAnnounceChoice());
  // Go's start (the owner, 2026-10-11): the rider's location, asked for once when Go opens, never in Plan.
  const [goStart, setGoStart] = useState<GoStart>({ kind: "idle" });
  const goStartRef = useRef(goStart);
  goStartRef.current = goStart;
  const goStartAsked = useRef(false);
  // A destination picked in Go before it has a start (the location still being found, or not available): kept
  // and routed once the start comes, from the location or the start box (lib/appMode.ts goPickAction).
  const goPending = useRef<{ dest: LonLat; name: string } | null>(null);
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
  // A route kept for offline (WEB-NAV-plan.md section 8, P3) answers when the planner cannot be reached
  // and the plan is one the rider kept; the planner's notice says so, and the next real answer clears it.
  const keptShown = useRef<KeptRoute<RouteResponse> | null>(null);
  const keptNotice = useRef<string | null>(null);
  // The plan the route on screen answers, as a kept route's key (keptPlanKey): set with the route, so a
  // keep during a re-plan in flight files the route shown under its own plan, never the next one's.
  const routedKey = useRef<string | null>(null);
  if (scheduler.current === null) {
    scheduler.current = new RouteScheduler<Plan>({
      send: async (plan) => {
        const result = await requestRoute(plan.points, plan.preset, { confirmLong: plan.confirmLong, dials: plan.dials });
        keptShown.current = null;
        if (result.ok || result.error.kind !== "network") return result;
        const kept = await keptAnswerFor<RouteResponse>(keptPlanKey(plan.points, plan.preset, plan.dials)).catch(() => undefined);
        if (!kept) return result;
        keptShown.current = kept;
        return { ok: true, route: kept.answer };
      },
      onState: (state: SchedulerState) => {
        if (state.kind === "in-flight" || state.kind === "pending") setStatus({ kind: "loading" });
        else if (state.kind === "waiting") setStatus({ kind: "waiting", seconds: state.seconds });
      },
      onResult: (plan: Plan, result: RouteResult) => {
        if (result.ok) {
          setRoute(result.route);
          setRoutedPoints(plan.points);
          setRoutedLoop(loopStops(plan.preset, plan.dials.loop));
          routedKey.current = keptPlanKey(plan.points, plan.preset, plan.dials);
          setStatus({ kind: "ok" });
          const kept = keptShown.current;
          const was = keptNotice.current;
          keptNotice.current = kept ? offlineRouteNotice(kept) : null;
          if (kept) setNotice(keptNotice.current);
          else if (was) setNotice((n) => (n === was ? null : n));
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
    const target = focusOnViewChange({ was, view, cause: viewCause.current });
    if (target === null) return;
    if (target.kind === "opener") {
      const opener = backTo.current;
      if (opener?.isConnected && opener.offsetParent !== null) opener.focus();
      else plannerHeadingRef.current?.focus();
    } else if (target.kind === "error") errorRef.current?.focus();
    else if (target.kind === "plan") planButtonRef.current?.focus();
    else if (target.kind === "planner") {
      // The Plan button (OWNER-DECISIONS 392): the planner's heading, at the top of the panel.
      plannerHeadingRef.current?.focus();
      panelBodyRef.current?.scrollTo?.({ top: 0 });
    }
    else {
      const heading = document.getElementById(`sheet-${target.view}-title`);
      heading?.focus();
      heading?.scrollIntoView?.({ block: "start" });
    }
  }, [view]);

  // The long-ride question takes the focus when it comes, so a keyboard rider lands on it (once the
  // sheet is open: a hidden button cannot take it). Not again on the way back from a bar sheet while
  // it is pending: Back goes to the bar button (the correctness review's N8); a question that came
  // while a sheet was open takes the focus through the effect above.
  const focusPlan = focusesPlanButton(status.kind, panelOpen);
  const viewNow = useRef(view);
  viewNow.current = view;
  const goSheetNow = useRef(goSheet);
  goSheetNow.current = goSheet;
  const myGoRef = useRef(myGo);
  myGoRef.current = myGo;
  const meRef = useRef(me);
  meRef.current = me;
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
  // Extra narration (lib/announceLevel.ts): said only at Full; Brief, Go's default, keeps to the essentials.
  const announceLevelNow = useRef<AnnounceLevel>("full");
  const announceExtra = useCallback((text: string) => {
    if (saysExtra(announceLevelNow.current)) announce(text);
  }, [announce]);

  // My Go (lib/myGo.ts; the owner's choice 2): signed in it is the account's (GET /api/me/go, read once
  // the page knows it is signed in), and an account's Open in or ride may still move a view that was only
  // the screen's guess; signed out, the device's. A save goes to the account only once it has been read,
  // so a Home is never overwritten by a save made before the page knew it.
  const accountMyGoRead = useRef(false);
  const rideTouched = useRef(false);
  const myGoSaidTimer = useRef<number | undefined>(undefined);
  const sayMyGo = (text: string) => {
    window.clearTimeout(myGoSaidTimer.current);
    setMyGoSaid("");
    myGoSaidTimer.current = window.setTimeout(() => setMyGoSaid(text), 150);
  };
  const saveMyGoNow = (next: MyGo, speak = true) => {
    setMyGo(next);
    if (meRef.current.signed_in) {
      if (!accountMyGoRead.current) return;
      saveAccountCopy(next);
      void saveMyGo(window.location.origin, next).then((saved) => {
        if (saved) setMyGo(saved);
        if (speak) sayMyGo(saved ? MY_GO_SAVED : MY_GO_NOT_SAVED);
      });
    } else {
      saveDeviceMyGo(next);
      if (speak) sayMyGo(MY_GO_SAVED_DEVICE);
    }
  };
  useEffect(() => {
    let live = true;
    const origin = window.location.origin;
    void fetchMe(origin).then(async (found) => {
      if (!live) return;
      setMe(found);
      if (!found.signed_in) {
        // Signed out (or the account's copy is from before a sign-out): this device's My Go.
        if (START_MY_GO.account) {
          saveAccountCopy(null);
          setMyGo(readStartMyGo().myGo);
        }
        return;
      }
      const account = await fetchMyGo(origin);
      if (!live || !account) return;
      accountMyGoRead.current = true;
      setMyGo(account);
      saveAccountCopy(account);
      if (laterMyGoApplies(OPENING.by, modeSwitched.current)) {
        const later = openingMode({ tab: null, planLink: false, openIn: account.openIn, wide: !window.matchMedia(NARROW).matches }).mode;
        setModeState((now) => (now === later ? now : later));
        if (later === "go" && account.ride && !PLAN_LINK && !rideTouched.current && pointsRef.current.length === 0) {
          setPreset(account.ride);
          setDials(startDials(account.ride));
        }
      }
    });
    return () => {
      live = false;
    };
  }, []);
  // The installable app (WEB-NAV-plan.md section 8): a new version ready, and offline, said through the
  // same region; shown at the top of the planner (InstallableApp.tsx).
  const appStatus = useAppStatus(riding, announce);
  // Bumped when a route is kept, so Settings' list reads the store again.
  const [keptVersion, setKeptVersion] = useState(0);
  const [keeping, setKeeping] = useState(false);
  const [keepSpoken, setKeepSpoken] = useState({ text: "", count: 0 });
  const keepAbort = useRef<AbortController | null>(null);
  // Keep for offline: the installed app's (465a) and, by the owner's choice of 2026-10-10, a tab's too (keepOffered is the one switch).
  const keepShown = keepOffered(isStandalone());
  // Once a while after load (not at it: the store's first open takes about a second), what a keep or a
  // removal cut short left unnamed is deleted (offlineKeep.ts sweepKept).
  useEffect(() => {
    const timer = window.setTimeout(() => void sweepKept(), 20_000);
    return () => window.clearTimeout(timer);
  }, []);
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
  // Go's sheet has no Points section: its notice is said through the app's region there too.
  plannerShownNow.current = view === "planner" && panelOpen && mode === "plan";
  useEffect(() => {
    if (noticeSaidElsewhere(notice, plannerShownNow.current)) announce(notice as string);
  }, [notice, announce]);

  // Which bands the Mass Ride map shows changes with the zoom (OWNER-DECISIONS 421). The legend's status
  // line says it; while the Legend sheet (UI-CLEANUP: behind Layers' Legend button) is not on screen it is
  // said through the app-level region instead, and only when the set of bands changes (not at every zoom
  // step, nor on coming to the map).
  const massBands = massMap && stressVisible ? massBandsSaid(zoom) : null;
  const massBandsBefore = useRef<string | null>(null);
  const legendShownNow = useRef(false);
  legendShownNow.current = view === "legend" && panelOpen;
  // Only for a zoom the rider made: after the first fit to a route, or a place search's fly-to, the
  // route's or the place's own sentence is what matters (accessibility review S4).
  const zoomByRider = useRef(false);
  useEffect(() => {
    const said = massBandsChangeSaid(massBandsBefore.current, massBands, legendShownNow.current);
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
  const placeStation = useCallback((role: StationRole, point: LonLat, place: { name: string; label: string }) => {
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
    // Named for the station, not the street its bike entrance is on (PLAN.md, the stationBikeEntrance naming).
    namer.remember(point, place.name, place.label);
    commit(edit.next);
    announce(stationSaid(edit.index, edit.next.length, loopVias));
  }, [commit, announce, loopVias, namer]);

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
    // Its own status line is in the Water sheet; out of it, the app's region says it.
    if (!(viewNow.current === "nearest" && panelOpen)) announce(text);
  };
  // A list is for the ride and the spot it was found for: a new ride type or slider (other distances),
  // a new "Search from", or a start that moved under a "start" search put it away.
  // Not the loop: Ride here turns it off in its own edit, and the list stays for a second pick. A search
  // under way when one changes is thrown away when it answers (the epoch).
  const nearestKey = JSON.stringify([preset, { ...routeDials, loop: false }, nearestFrom]);
  const nearestEpoch = useRef(0);
  useEffect(() => {
    nearestEpoch.current += 1;
    setNearestList(null);
  }, [nearestKey]);
  useEffect(() => {
    if (nearestList?.from === "start" && String(points[0]) !== String(nearestList.origin)) setNearestList(null);
  }, [points, nearestList]);
  // Go's Water and Restroom chips search from the rider's location: the "Search from" is set first, and the
  // search runs once it has (a change of it puts away a list found for the old one: nearestKey).
  const nearestPending = useRef<NearestKind | null>(null);
  useEffect(() => {
    const kind = nearestPending.current;
    if (kind === null || nearestFrom !== "location") return;
    nearestPending.current = null;
    void findNearest(kind);
  });
  const findNearestHere = (kind: NearestKind) => {
    if (nearestFrom === "location" || !nearestFromOptions.includes("location")) void findNearest(kind);
    else {
      nearestPending.current = kind;
      setNearestFrom("location");
    }
  };
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
      entrance: stationEntranceForPlace,
    });
    if (point === null) return;
    setNotice(null);
    const map = mapRef.current;
    map?.flyTo({ center: point, zoom: Math.max(map.getZoom(), 14) });
  };
  // Go (the owner's commute view): the place picked is the destination and the start is the rider's
  // location, in one edit (Undo puts the plan back). Without a location the destination stands alone and
  // the notice says why; Plan sets a start by hand.
  // Go's one look-up (Where to?, the Home chip and Locate), through Use my location's gate: null when
  // another look-up is under way or a later one replaced it. The fix is kept only as Use my location's is.
  const locateForGo = async (): Promise<LocateResult | null> => {
    const press = gate.begin();
    announceExtra(FINDING_LOCATION);
    if (press === null) return null;
    setLocating(true);
    const result = await locate(geoEnv);
    if (!gate.finish(press)) return null;
    setLocating(false);
    return result;
  };
  // Go's start, when Go opens with an empty plan: the location becomes the start (not yet a point, so the
  // link holds no position until a destination is picked). A start from the link, or one typed or tapped
  // first, wins. Denied, unavailable or timed out: the start stays empty and that is said politely.
  useEffect(() => {
    if (!shouldAskGoStart({ mode, asked: goStartAsked.current, pointCount: pointsRef.current.length })) return;
    goStartAsked.current = true;
    setGoStart({ kind: "locating" });
    void (async () => {
      const result = await locateForGo();
      if (result === null) {
        setGoStart({ kind: "idle" });
        return;
      }
      const pending = goPending.current;
      if (!result.ok || !insideCoverage(result.fix.point)) {
        setGoStart({ kind: "none" });
        if (pointsRef.current.length === 0) setNotice(pending ? goDestinationNeedsStart(pending.name) : GO_START_UNAVAILABLE);
        return;
      }
      setHere(result.fix);
      setGoStart({ kind: "here", point: result.fix.point });
      if (pointsRef.current.length > 0) return;
      // A destination picked while the location was being found: routed now, not dropped.
      if (pending) {
        goPending.current = null;
        routeGoRef.current(result.fix.point, true, pending.dest, pending.name);
      } else announce(GO_START_SAID);
    })();
    // Once per page, when Go is first shown (locateForGo reads only refs and stable setters).
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps
  // A start typed into Go's start box: the plan's first point, in place of the location.
  const goStartPick = (found: Place) => {
    const point = placeFromSearch(found, (p, name, label) => namer.remember(p, name, label), stationEntranceForPlace);
    if (point === null) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    setNotice(null);
    // A destination picked before there was a start: the start typed here, then that destination.
    const pending = goPending.current;
    if (pending) {
      goPending.current = null;
      routeGo(point, false, pending.dest, pending.name);
      return;
    }
    commit([point]);
    announce(`Start: ${found.name}.`);
  };
  // A Go route from `start` to `dest`, in one edit, with a loop the rider had on turned off (to a place and no further).
  const routeGo = (start: LonLat, located: boolean, dest: LonLat, name: string) => {
    const ride = rideRef.current;
    setNotice(null);
    commit([start, dest], ride.dials.loop ? { ...ride, dials: { ...ride.dials, loop: false } } : undefined);
    if (located) setFromHere((prior) => [...prior, start]);
    announceExtra(`Planning a route to ${name} from ${located ? "your location" : "your start"}.`);
    if (goSheetNow.current === "peek") setGoSheet("half");
    mapRef.current?.flyTo({ center: dest, zoom: Math.max(mapRef.current.getZoom(), 13) });
  };
  // The opening look-up answers after later renders: it routes through the current one.
  const routeGoRef = useRef(routeGo);
  routeGoRef.current = routeGo;
  const goTo = async (dest: LonLat, name: string) => {
    cancelLocateNotice();
    setNotice(null);
    if (!insideCoverage(dest)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    // The start Go already has: the plan's first point (typed, tapped or from the link), else the location
    // found when Go opened. While the location is still being found, the destination waits for it.
    const action = goPickAction(pointsRef.current, goStartRef.current);
    if (action.kind === "route") {
      goPending.current = null;
      routeGo(action.point, action.located, dest, name);
      return;
    }
    goPending.current = { dest, name };
    if (action.kind === "wait") {
      setNotice(goDestinationLocating(name));
      return;
    }
    // No location yet: one more look-up (the rider may have allowed it since); failing that the destination is
    // kept and the start box asks for a start. The destination is never made the start.
    setGoStart({ kind: "locating" });
    const result = await locateForGo();
    if (result === null) {
      // Another look-up is under way: its answer routes the destination, as Go's opening one does.
      return;
    }
    if (!result.ok || !insideCoverage(result.fix.point)) {
      setGoStart({ kind: "none" });
      setNotice(goDestinationNeedsStart(name));
      return;
    }
    setHere(result.fix);
    setGoStart({ kind: "here", point: result.fix.point });
    const pending = goPending.current;
    goPending.current = null;
    if (pending && pointsRef.current.length === 0) routeGo(result.fix.point, true, pending.dest, pending.name);
  };
  const goToPlace = (found: Place) => {
    const point = placeFromSearch(found, (p, name, label) => namer.remember(p, name, label), stationEntranceForPlace);
    if (point === null) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    void goTo(point, found.name);
  };
  // Go's Home chip (the owner's choice 3): signed in with a Home, ride there; else My Go, under Settings.
  const goHome = (chip: HTMLElement) => {
    const home = myGoRef.current.home;
    if (meRef.current.signed_in && home) {
      namer.remember(home.point, home.label || "Home", home.label || "Home");
      void goTo(home.point, home.label || "Home");
      return;
    }
    openView("settings", chip);
    window.setTimeout(() => document.getElementById("settings-my-go-heading")?.scrollIntoView?.({ block: "start" }), 50);
  };
  // Go's Locate (the top bar): the map goes to the rider, and nothing is added to the plan.
  const goLocate = async () => {
    const result = await locateForGo();
    if (result === null) return;
    if (!result.ok) {
      setNotice(LOCATE_MESSAGES[result.reason]);
      return;
    }
    setHere(result.fix);
    if (!insideCoverage(result.fix.point)) setNotice(LOCATION_OUTSIDE);
    else announceExtra("The map is at your location.");
    mapRef.current?.flyTo({ center: result.fix.point, zoom: Math.max(mapRef.current.getZoom(), 15) });
  };
  // A ride type chip (Go's quick three, or the Ride sheet's): as the ride type dialog picks one.
  const pickRide = (id: PresetId) => {
    if (id === preset) return;
    choosePreset(id, mtbChosen(preset, id, chooseRideType(id, carries(id) ? "cargo" : null, dials)));
    announceExtra(`${presetLabel(id)}.`);
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
  // The Mountain Bike ride type's level (slice 6): the map draws the trails up to it as routable.
  // Every other ride type, and a Mountain Bike ride with trails off, draws them as not for routes.
  const routableLevel = isMtb(preset) && !trailsAreOff(preset, dials) ? mtbLevelOf(dials) : null;
  useEffect(() => {
    setRoutableMtb(routableLevel);
  }, [routableLevel]);
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
    rideTouched.current = true;
    // Mountain Bike (slice 6) turns the mountain-bike and contour layers on (the owner's defaults of
    // 2026-10-11), not remembered as the rider's own choice; its loop is on in `next` (mtbChosen).
    if (isMtb(id) && !isMtb(preset)) {
      setMtbTrails(true, { remember: false });
      setTopoLines(true, { remember: false });
    }
    setPreset(id);
    setDials(next);
    // A station chosen on Bikeshare is not carried to the next ride type, or back (OWNER-DECISIONS 466a).
    setStationPins({});
  };
  const chooseStation = (action: StationAction, station: NearbyStation | null, point: LonLat) => {
    setStationPins((pins) => ({
      ...pins,
      [action]: station ? { id: station.station_id, name: station.name, at: point } : undefined,
    }));
    announce(chosenSaid(action, station));
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
    opened.current = [];
    if (viewNow.current === "planner") {
      if (focusHeading) {
        plannerHeadingRef.current?.focus();
        panelBodyRef.current?.scrollTo?.({ top: 0 });
      }
    } else setView("planner");
  };
  // A sheet: from the bar, a map chip or Go's Menu (a new way back), or from inside a sheet (Layers' Legend,
  // Suggest's Review, the Menu's pages: one more step back). The focus goes to its heading.
  const openView = (next: PanelView, opener: HTMLElement | null, nested = false) => {
    if (next === "planner") {
      showPlanner();
      return;
    }
    opened.current = openOnto(opened.current, viewNow.current, opener, nested);
    viewCause.current = "bar";
    setPanelOpen(true);
    if (goSheetNow.current === "peek") setGoSheet("half");
    setView(next);
  };
  const openSheet = (item: BarItem, button: HTMLButtonElement) => openView(item.opens, button);
  // Back (or Escape): to the sheet this one was opened from, or the planner, and the focus to what opened it.
  const backToPlanner = () => {
    const step = backFrom(opened.current);
    opened.current = step.stack;
    backTo.current = step.opener;
    viewCause.current = "back";
    setView(step.view);
  };
  const backLabel = (of: PanelView): string => {
    const step = opened.current[opened.current.length - 1];
    // Go's Menu, Layers and chips' sheets close back to the map and its sheet (the mockup's "Menu Close").
    if (!step || viewNow.current !== of || step.from === "planner") return mode === "go" ? GO_CLOSE_LABEL : BACK_LABEL;
    return `Back to ${step.from === "settings" && mode === "go" ? "Menu" : SHEET_TITLES[step.from as Exclude<PanelView, "planner">]}`;
  };
  const sheetNav: SheetNav = { view, back: backToPlanner, backLabel };

  // Go and Plan (lib/appMode.ts): the switch changes the view, keeps the route, and is remembered as My Go's
  // Open in (the account's signed in, this device's not) and for this tab.
  const changeMode = (next: AppMode) => {
    if (next === mode) return;
    modeSwitched.current = true;
    writeTabMode(next);
    opened.current = [];
    setView("planner");
    setPanelOpen(true);
    setGoSheet("half");
    setModeState(next);
    announceExtra(modeSaid(next));
    saveMyGoNow({ ...myGoRef.current, openIn: next }, false);
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
  // "Share": the same link as Copy link, to the phone's share sheet. The location line describes the button,
  // so it is read before the sheet opens. Nothing is said when the sheet opened or the rider closed it;
  // a failure is said, offering Copy link. It shares the said lines with Copy link, so the last press speaks.
  // A press while the sheet is open is skipped. shareLink is called before any await, so the press's user
  // activation still holds. The distance is the route shown, so it is left out while a re-plan is pending
  // (the link carries the current points).
  const sharing = useRef(false);
  const shareRoute = async () => {
    if (!shown || sharing.current) return;
    sharing.current = true;
    const press = ++linkPresses.current;
    setLinkSaid("");
    setLinkSpoken("");
    const distanceM = !stale && routedPoints === points ? shown.distance_m : null;
    const content = shareContent(linkToCopy(window.location, points, preset, dials), distanceM, presetLabel(preset));
    const outcome = shareLink(navigator, content);
    let said: string;
    try {
      said = shareSaidFor(await outcome);
    } finally {
      sharing.current = false;
    }
    if (!said) return;
    window.setTimeout(() => {
      if (press === linkPresses.current) setLinkSaid(said);
      if (press === linkPresses.current) setLinkSpoken(said);
    }, 150);
  };

  // Start ride (plan Q1, Q3): the first ride asks how to say the cues; later rides start at once. The
  // voice is unlocked inside this press (iOS speaks only after a gesture).
  const beginRide = (prefs: RidePrefs) => {
    if (!shown) return;
    startRideGesture(prefs);
    setRideStart({ route: shown, points: routedPoints, loop: routedLoop, dials: planDials });
    // The installed app keeps the ride's route as the last ride (OWNER-DECISIONS 465a); End ride gives it
    // the map the ride kept. A browser tab keeps nothing unless the rider presses Keep for offline.
    // A Keep for offline still fetching stops: the ride keeps its own corridor, and two walks would share the page's queue.
    keepAbort.current?.abort();
    if (isStandalone() && routedKey.current) {
      void keepLastRide({ plan: routedKey.current, title: keptTitle(), distanceM: shown.distance_m, answer: shown })
        .then(() => setKeptVersion((v) => v + 1))
        .catch(() => undefined);
    }
    setRideAsk(false);
    setFollow(true);
    setBigText(false);
    setRideView(null);
    setRiding(true);
  };
  // Keep for offline (P3): the plan, its answer and the map along it; the press asks the browser to
  // keep the site's storage (navigator.storage.persist), and what it did is said politely.
  const keptTitle = () => {
    const first = routedPoints[0];
    const last = routedPoints[routedPoints.length - 1];
    return routeTitle(first && namer.name(first)?.name, last && namer.name(last)?.name, routedLoop);
  };
  const keepForOffline = async () => {
    const plan = routedKey.current;
    if (!shown || keeping || !plan) return;
    setKeeping(true);
    const controller = new AbortController();
    keepAbort.current = controller;
    setKeepSpoken((s) => ({ text: KEEPING_SAID, count: s.count + 1 }));
    void askPersist();
    const title = keptTitle();
    const { outcome, removed } = await keepRoute({ plan, title, distanceM: shown.distance_m, answer: shown, line: shown.geometry.coordinates }, controller.signal).catch(() => ({ outcome: "failed" as const, removed: false }));
    if (keepAbort.current === controller) keepAbort.current = null;
    setKeeping(false);
    setKeptVersion((v) => v + 1);
    // Stopped by Remove of this route in Settings: Remove has said what happened; the keep says nothing.
    if (removed) setKeepSpoken({ text: "", count: 0 });
    else setKeepSpoken((s) => ({ text: keepSaid(outcome, title), count: s.count + 1 }));
  };
  // Settings' Open: the kept plan, into the planner (with no signal, the scheduler answers from the kept route).
  const openKept = (kept: KeptRoute) => {
    showPlanner(true);
    // The kept key leaves Mass Ride's ride size out (keptPlanKey); the size set now stays.
    const plan = decodePlan(kept.plan);
    const hash = dials.rideSize && plan.preset === preset ? encodePlan(plan.points, plan.preset, { ...plan.dials, rideSize: dials.rideSize }) : kept.plan;
    if (window.location.hash !== hash) window.location.hash = hash;
    announce(`Opening ${kept.title}.`);
  };
  const startRide = () => {
    const opener = document.activeElement;
    rideOpener.current = opener instanceof HTMLElement && opener.closest(".start-ride, .description-actions") ? opener : startRideRef.current;
    // Go goes straight to the ride (the owner, 2026-10-11 20:23 UTC: "just ... find a destination and go"):
    // no first-ride question; the cues are Settings > Ride mode's (the defaults until changed there). Plan asks once.
    if (!ridePrefs.chosen && mode !== "go") {
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
  // Go's Bikeshare options (lib/bikeshareOptions.ts): the first answer's list, kept for the trip, since a
  // re-plan of one option answers with that pair only.
  const [keptOptions, setKeptOptions] = useState<KeptOptions | null>(null);
  useEffect(() => {
    setKeptOptions((kept) => keepOptions(kept, bikeshareOf(route), optionsKey(routedPoints)));
  }, [route, routedPoints]);
  const goOptions =
    mode === "go" && preset === "bikeshare" && shown && keptOptions && keptOptions.key === optionsKey(points) && keptOptions.options.length > 1
      ? keptOptions.options
      : null;
  const pickOption = (index: number) => {
    const option = goOptions?.[index];
    // The one already planned: nothing to re-plan.
    if (!option || index === pickedOption(goOptions, bikeshareOf(shown))) return;
    setStationPins(optionPins(option, points));
    setDials((d) => ({ ...d, ending: option.ending }));
    announce(optionSaid(placeLetter(index), option));
  };
  // A new answer: the Keep button's line was about the route before it.
  useEffect(() => setKeepSpoken({ text: "", count: 0 }), [answer]);
  // The layer in words: the points along the route shown, in riding order.
  const waterAlong = useMemo(
    () =>
      waterOn && waterData && shown
        ? waterAlongRoute(shown.geometry.coordinates, waterData.filter((p) => waterVisible(p, waterPrefs)))
        : null,
    [waterOn, waterData, waterPrefs, shown],
  );
  // The Climbs layer in words: the climbs the route rides, in riding order.
  const climbsAlong = useMemo(
    () => (climbsOn && climbsData && shown ? climbsAlongRoute(shown.geometry.coordinates, climbsData) : null),
    [climbsOn, climbsData, shown],
  );
  // Find food (lib/food.ts; FOOD-SEARCH, owner 2026-10-11): a map search by cuisine or name, in the
  // map's view or the whole area. The places file is fetched on the first search. The results are
  // worked out again when the route changes, so each detour is off the route shown (and the list is
  // sorted by it); without a route, by distance from the map's center where the search was made.
  const [foodQuery, setFoodQuery] = useState("");
  const [foodScope, setFoodScope] = useState<FoodScope>("view");
  const [foodAsked, setFoodAsked] = useState<{ query: string; scope: FoodScope; bounds: Bounds | null; centre: LonLat } | null>(null);
  const [foodPlaces, setFoodPlaces] = useState<FoodPlace[] | null>(null);
  const [foodCount, setFoodCount] = useState(FOOD_PAGE);
  const [foodBusy, setFoodBusy] = useState(false);
  const [foodStatus, setFoodStatus] = useState("");
  const foodLoad = useRef<Promise<FoodPlace[] | null> | null>(null);
  const foodTimer = useRef<number | undefined>(undefined);
  // Cleared and set again a moment later, so the same words twice are said twice (as sayNearest).
  const sayFood = (text: string) => {
    window.clearTimeout(foodTimer.current);
    setFoodStatus("");
    foodTimer.current = window.setTimeout(() => setFoodStatus(text), 150);
    // Its own status line is in the Food sheet; out of it, the app's region says it.
    if (!(viewNow.current === "food" && panelOpen)) announce(text);
  };
  const foodRoute = useMemo(() => routeForDetour(shown), [shown]);
  const foodAll = useMemo(
    () => (foodAsked && foodPlaces ? searchFood(foodPlaces, { ...foodAsked, route: foodRoute }) : null),
    [foodAsked, foodPlaces, foodRoute],
  );
  const foodResults = useMemo(() => foodAll?.slice(0, foodCount) ?? null, [foodAll, foodCount]);
  useEffect(() => {
    if (foodAll && foodAsked) sayFood(foodFoundSaid(foodAsked.query, foodAsked.scope, foodAll.length, Math.min(foodCount, foodAll.length), foodRoute !== null));
    // Said for a new search or a new route, not for Show more (which says its own words).
  }, [foodAll]);
  const searchFoodNow = async (asked?: string) => {
    if (foodBusy) return;
    const query = asked ?? foodQuery;
    if (!foodTerms(query)) {
      setFoodAsked(null);
      sayFood(FOOD_EMPTY_QUERY);
      return;
    }
    if (!foodLoad.current) {
      foodLoad.current = loadFood(foodUrl).then((data) => {
        if (!data) foodLoad.current = null;
        return data;
      });
    }
    setFoodBusy(true);
    const places = await foodLoad.current;
    setFoodBusy(false);
    if (!places) {
      sayFood(FOOD_NOT_LOADED);
      return;
    }
    if (places.length === 0) {
      sayFood(NO_FOOD_DATA);
      return;
    }
    const map = mapRef.current;
    const b = map?.getBounds();
    const c = map?.getCenter();
    setFoodPlaces(places);
    setFoodCount(FOOD_PAGE);
    setFoodAsked({
      query,
      scope: foodScope,
      bounds: b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null,
      centre: c ? [c.lng, c.lat] : [(COVERAGE_BBOX[0] + COVERAGE_BBOX[2]) / 2, (COVERAGE_BBOX[1] + COVERAGE_BBOX[3]) / 2],
    });
  };
  const showFood = (result: FoodResult) => {
    const map = mapRef.current;
    const n = foodResults?.indexOf(result) ?? -1;
    map?.flyTo({ center: [result.place.lon, result.place.lat], zoom: Math.max(map.getZoom(), 15) });
    announce(`Showing ${result.place.name} on the map${n >= 0 ? `, marker ${placeLetter(n)}` : ""}.`);
  };
  const addFoodStop = (result: FoodResult) => {
    const point: LonLat = [result.place.lon, result.place.lat];
    namer.remember(point, result.place.name);
    placeSpot("via", point);
  };
  // The nearest finder (Plan's Water chip, Go's Water and Restroom chips): its own sheet now.
  const nearestProps = {
    from: nearestFrom,
    fromOptions: nearestFromOptions,
    onFrom: setNearestFrom,
    onFind: (kind: NearestKind) => void findNearest(kind),
    busy: nearestBusy,
    status: nearestStatus,
    list: nearestList,
    canAddStop: points.length >= 2,
    onRide: (item: Nearby) => (mode === "go" ? goToLettered(item.place.point, item.place.title) : rideToNearest(item)),
    onAddStop: addNearestStop,
  };
  // An instance admin's review (rider suggestions, Mass Ride hazard reports): from Suggest, or Go's Menu.
  const reviewOpener = me.can_change_lts ? (opener: HTMLElement) => openView("review", opener, true) : null;
  const myGoControls = { myGo, signedIn: me.signed_in, save: saveMyGoNow, said: myGoSaid, geoGate, searchBias };
  // Go's Menu (the Settings sheet in Go): Plan, Suggest, GPX and an admin's Review, each one step in.
  const menu = {
    onPlan: () => changeMode("plan"),
    onSuggest: (opener: HTMLElement) => openView("suggest", opener, true),
    onGpx: (opener: HTMLElement) => openView("gpx", opener, true),
    onReview: reviewOpener,
  };
  // The lettered places (the owner, 2026-10-11 21:04 UTC; lib/letteredPlaces.ts): the list on the sheet open,
  // the nearest water, restrooms or Metro, or the food found, lettered on the map as in the list. A pick (its
  // marker, Ride here in Go, or its letter's key) is the destination in Go, straight to the route options;
  // in Plan, the nearest's Ride here, and food's Show on map.
  const letteredOf: "nearest" | "food" | "bikeshare" | null =
    view === "nearest" && nearestList && nearestList.items.length > 0
      ? "nearest"
      : view === "food" && foodResults && foodResults.length > 0
        ? "food"
        : goOptions && !(panelOpen && view !== "planner")
          ? "bikeshare"
          : null;
  const lettered = useMemo(
    () =>
      letteredOf === "nearest" && nearestList
        ? letterPlaces(nearestList.items, (item) => ({ point: item.place.point, title: item.place.title, metres: item.distanceM }))
        : letteredOf === "food" && foodResults
          ? letterPlaces(foodResults, (r) => ({ point: [r.place.lon, r.place.lat] as LonLat, title: r.place.name, metres: r.detour ? null : r.fromCentreM }))
          : letteredOf === "bikeshare" && goOptions
            ? // Each option at its pick-up station, named as its button is.
              goOptions.map((o, i) => ({ letter: placeLetter(i), point: [o.pickup.lon, o.pickup.lat] as LonLat, name: optionName(placeLetter(i), o) }))
            : null,
    [letteredOf, nearestList, foodResults, goOptions],
  );
  const goToLettered = (point: LonLat, title: string) => {
    namer.remember(point, title);
    showPlanner(true);
    void goTo(point, title);
  };
  const pickLettered = (index: number) => {
    if (letteredOf === "nearest" && nearestList) {
      const item = nearestList.items[index];
      if (!item) return;
      if (mode === "go") goToLettered(item.place.point, item.place.title);
      else rideToNearest(item);
    } else if (letteredOf === "food" && foodResults) {
      const r = foodResults[index];
      if (!r) return;
      if (mode === "go") goToLettered([r.place.lon, r.place.lat], r.place.name);
      else showFood(r);
    } else if (letteredOf === "bikeshare") {
      pickOption(index);
    }
  };
  const pickLetteredRef = useRef(pickLettered);
  pickLetteredRef.current = pickLettered;
  // A letter's key picks that option while its list's sheet is open (not while typing, nor on the map).
  useEffect(() => {
    if (!lettered) return;
    const onKey = (event: KeyboardEvent) => {
      const index = letterKeyIndex(event, Math.min(lettered.length, 26));
      if (index === null) return;
      event.preventDefault();
      pickLetteredRef.current(index);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lettered]);
  const foodFinder = (
    <FoodFinder
      folded={false}
      onRide={mode === "go" ? (r) => goToLettered([r.place.lon, r.place.lat], r.place.name) : undefined}
      query={foodQuery}
      onQuery={setFoodQuery}
      scope={foodScope}
      onScope={setFoodScope}
      onSearch={() => void searchFoodNow()}
      busy={foodBusy}
      status={foodStatus}
      results={foodResults}
      total={foodAll?.length ?? 0}
      onMore={() => {
        if (!foodAll) return;
        const next = Math.min(foodCount + FOOD_PAGE, foodAll.length);
        setFoodCount(next);
        sayFood(foodMoreSaid(next, foodAll.length));
      }}
      canAddStop={points.length >= 2}
      onShow={showFood}
      onAddStop={addFoodStop}
    />
  );
  // A Mass Ride's federal-land lines for the description and the GPX file (item 239; lib/federalStops.ts):
  // the stops on federal land and the parkway stretches, from the route as planned, or one line saying
  // federal land could not be checked while the data is loading or unavailable.
  const federalRoute = useMemo(
    () => (shown ? federalRouteLines(shown, routedPoints, federalData) : []),
    [shown, routedPoints, federalData],
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
    // A bikeshare ride runs dock to dock, not between the points: its line is not theirs to drag.
    if (bikeshareOf(shown)) return null;
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
  // Mass Ride's points on federal land (item 239; lib/federalStops.ts): each one's warning, on its row in
  // the points list and on its marker. The planner says so when none is (the correctness review's S3);
  // the Map layers sheet keeps its own list.
  const federalAreas = useMemo(() => pointAreas(points, federalData, federalShown(preset, true)), [points, federalData, preset]);
  const pointWarnings = federalAreas.map((area) => (area ? stopWarningShort(area) : null));
  const federalPlanner = federalShown(preset, true) && federalData && points.length > 0 && federalAreas.every((area) => area === null) && (
    <p className="hint federal-points">{FEDERAL_POINTS_NONE}</p>
  );
  const loop = loopView(preset, dials.loop, points);
  const loopHintId = useId();
  const [tips, setTips] = useState(false);
  const tipsId = useId();
  const pointsSection = (
    <PointsSection key="points"
      {...{
        pointsHeadingRef, zoom, stressVisible, stress, pointsSearchRef, compactPoints, points, loopVias, geoGate,
        searchBias, pickPlace, locateReady, locating, hereInPlan, here, useMyLocation, loop, loopHintId, commitDials,
        dials, accessMode, namer, removeAt, pointWarnings, removeRefs, preset, stationChoice, chooseStation,
        routeShownForPoints, editPointsRef, setEditPoints, federalPlanner,
        pointsEditRef, reverseButton, reverse, reverseHint, orderShown, bestOrder, orderFocused, ordering, narrow,
        undo, can, redo, clearAll, coverageShown, toggleAccessMode, announce, notice, tips, setTips, tipsId,
      }}
    />
  );
  const goMode = mode === "go";
  announceLevelNow.current = announceLevel(announceChoice, mode);
  const chooseAnnounce = (level: AnnounceLevel) => {
    setAnnounceChoice(level);
    writeAnnounceChoice(level);
    announce(level === "brief" ? "Announcements: brief." : "Announcements: full.");
  };
  // A bikeshare ride's station choice (the Points section's, before): under Route, closed, as the mockup has it.
  const stations =
    preset === "bikeshare" && points.length > 0 ? (
      <Fold title="Choose a station" icon="bikeshare" className="stations-fold">
        <NearbyStations points={points} pins={stationChoice} onChoose={chooseStation} />
      </Fold>
    ) : null;
  const actions = {
    routedLoop, copyLink, linkNote, canShare, shareRoute, linkSpoken, keepShown, keepForOffline, keeping, keepSpoken, linkSaid,
  };
  const go = {
    onRide: () => openView("ride", document.activeElement instanceof HTMLElement ? document.activeElement : null),
    onPlan: () => changeMode("plan"),
    peek: goSheet === "peek",
    options: goOptions ? { list: goOptions, picked: pickedOption(goOptions, bikeshareOf(shown)), busy: stale, onPick: pickOption } : null,
  };
  const routeSection = (
    <RouteSection key="route"
      {...{
        mode, actions, stations, go,
        stale, routeHeadingRef, status, announcement, slow, preset, dials, points, cancelLong, planButtonRef,
        confirmLong, errorRef, retry, shown, answer, choice, aroundAvoid, setAroundAvoid, routedPoints, federalRoute,
        narrow, setJunctionFocus, setScrubPoint, choose, startRide, startRideRef, rideSize, setDials, waterOn,
        waterStatus, waterAlong, addWaterStop, rideAsk, setRideAsk, backToRideOpener, ridePrefs, changeRidePrefs,
        rideStartFirstRef, beginRide, climbsOn, climbsStatus, climbsAlong,
      }}
    />
  );

  const sections: Record<SheetSection, ReactElement> = {
    presets: (
      <RideSection key="presets"
        {...{
          preset, dials, choosePreset, commitDials, weight, weightRemembered, weightStore, setWeightRemembered,
          setWeight, route,
        }}
      />
    ),
    points: pointsSection,
    route: routeSection,
  };

  return (
    <div className={`app${riding ? " riding" : ""}${riding && bigText ? " riding-big" : ""}${goMode && !riding ? " go-mode" : ""}`}>
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
      {/* Go's bar over the map, first in the reading order as it is at the top of the screen. */}
      {!riding && goMode && (
        <GoTopBar
          mode={mode}
          onMode={changeMode}
          onMenu={(button) => openView("settings", button)}
          onLayers={(button) => openView("layers", button)}
          onLocate={() => void goLocate()}
          locating={locating}
          destination={shown && points.length >= 2 ? (namer.name(points[points.length - 1])?.name ?? "Destination") : null}
          onClear={clearAll}
        />
      )}
      <MapView
        points={riding ? NO_POINTS : points}
        loopVias={loopVias}
        openAt={OPEN_AT}
        pointWarnings={riding ? undefined : pointWarnings}
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
        lettered={riding ? null : lettered}
        onLettered={pickLettered}
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
        massHazards={massHazards}
        water={waterData}
        waterPrefs={waterPrefs}
        climbs={climbsData}
        climbsOn={climbsOn}
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
        hazards={massHazards}
        station={roadInfo ? stationNearSpot(RAIL_STATIONS, rail, roadInfo.point, WMATA_SLUGS)?.station ?? null : null}
        avoid={roadInfo ? avoidNearSpot(route, roadInfo.point) : null}
        junctionShown={roadInfo ? shownNear(route, roadInfo.point) : null}
        federal={roadInfo && federalShown(preset, true) ? federalAreaAt(roadInfo.point, federalData) : null}
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
      {!riding && !goMode && <PlanMapChips onFood={(chip) => openView("food", chip)} onWater={(chip) => openView("nearest", chip)} />}
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
          keepLastRide={isStandalone()}
        />
      )}
      {/* Hidden, not removed, during a ride: the planner keeps its state, and Sign in is out of reach (plan section 7). */}
      <aside
        ref={panelRef}
        id="route-planner"
        tabIndex={-1}
        className={`panel ${panelOpen ? "open" : "closed"}${goMode ? ` go-panel go-${goSheet}` : ""}`}
        aria-label="Route planner"
        hidden={riding}
      >
        <header className="panel-header">
          <h1 ref={plannerHeadingRef} tabIndex={-1} className={goMode ? "visually-hidden" : undefined}>
            {PLANNER_TITLE}
          </h1>
          {!goMode && <ModeSwitch mode={mode} onChange={changeMode} className="panel-mode" />}
          <button
            type="button"
            hidden={goMode}
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
          <AppStatusBar status={appStatus} />
          <div ref={panelBodyRef} className="panel-scroll">
            <div className="planner-view" hidden={view !== "planner"}>
              {goMode ? (
                <GoSheet
                  size={goSheet}
                  onSize={setGoSheet}
                  pointCount={points.length}
                  geoGate={geoGate}
                  searchBias={searchBias}
                  onPick={goToPlace}
                  places={{
                    homeReady: me.signed_in && myGo.home !== null,
                    signedIn: me.signed_in,
                    onHome: goHome,
                    onFood: (chip) => openView("food", chip),
                    onWater: (chip) => {
                      openView("nearest", chip);
                      findNearestHere("water");
                    },
                    onRestroom: (chip) => {
                      openView("nearest", chip);
                      findNearestHere("restroom");
                    },
                  }}
                  rides={<RideChips ids={goRideChips(myGo.ride)} preset={preset} onPick={pickRide} more={(opener) => openView("ride", opener)} label="Ride type" />}
                  notice={notice}
                  route={points.length > 1 || status.kind !== "idle" ? routeSection : null}
                  startLine={goStartLine(goStart, points.length > 0 ? (namer.name(points[0])?.name ?? "the point on the map") : null)}
                  startMissing={goStart.kind === "none" && points.length === 0}
                  onStartPick={goStartPick}
                />
              ) : (
                order.map((id) => sections[id])
              )}
            </div>

            {/* The sheets stay in the page while hidden, so the opened GPX file and the switches keep their state. */}
            <LayersSheet
              {...{
                nav: sheetNav, massMap, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn,
                setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus, waterAlong,
                addWaterStop, rail, setRail, showMtbTrails, showTopoLines, topoReady, climbsOn, changeClimbsOn,
                climbsStatus, climbsAlong, openLegend: (opener: HTMLElement) => openView("legend", opener, true),
              }}
            />
            <LegendSheet
              {...{
                nav: sheetNav, legendHeadingRef, massMap, stress, stressVisible, preset, zoom, facilitiesShown, waterPrefs,
                waterStatus, climbsOn, climbsStatus,
              }}
            />
            <SuggestSheet nav={sheetNav} roadInfoAtCentre={roadInfoAtCentre} onReview={reviewOpener} />
            <ReviewSheet nav={sheetNav} mapRef={mapRef} setHazardsAsked={setHazardsAsked} />
            <GpxSheet
              {...{
                nav: sheetNav, shown, routedPoints, routedLoop, federalRoute, points, status, imported, openImported,
                refineImported, getMap,
              }}
            />
            <SettingsSheet
              {...{
                nav: sheetNav, settingsHeadingRef, ridePrefs, changeRidePrefs, keepShown, keptVersion, openKept, announce,
                linkNote, accessMode, toggleAccessMode, mode, myGo: myGoControls, menu,
                announcements: { level: announceLevel(announceChoice, mode), choose: chooseAnnounce },
              }}
            />
            <NearestSheet nav={sheetNav}>
              <NearestFinder {...nearestProps} folded={false} />
            </NearestSheet>
            <FoodSheet
              nav={sheetNav}
              onChip={(food) => {
                setFoodQuery(food);
                void searchFoodNow(food);
              }}
            >
              {foodFinder}
            </FoodSheet>
            <RideSheet nav={sheetNav}>
              <RideChips ids={PRESETS.map((p) => p.id)} preset={preset} onPick={pickRide} label="Every ride type" />
              {/* Go's Ride sheet holds the Ride line and its dials; in Plan they are in the panel (one copy in the page). */}
              {goMode && sections.presets}
            </RideSheet>
          </div>

          {!goMode && <BottomBar view={view} onOpen={openSheet} buttonRef={(id, button) => (barButtons.current[id] = button)} />}
        </div>
      </aside>
    </div>
  );
}
