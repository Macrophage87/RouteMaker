import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type Frame, type LineEdit, type StressAvailability } from "./MapView.tsx";
import { RoadInfoDialog } from "./RoadInfoDialog.tsx";
import { MapTools } from "./MapTools.tsx";
import { ACCESS_LABEL, accessModeToggle, readAccessMode, writeAccessMode } from "./lib/accessMode.ts";
import { placeAtSpot, requestAfterClose, type InfoRequest } from "./lib/roadInfo.ts";
import { stationNearSpot } from "./lib/stationLinks.ts";
import { reorder } from "./lib/pointMover.ts";
import { canDragLine, dropStillValid, insertIntoRide, legEnds, legPoints } from "./lib/lineEdit.ts";
import { EditHistory, isRedoKey, isUndoKey, typesText } from "./lib/editHistory.ts";
import { requestNeighbours, requestRoute, routeRequestBody, type NeighbourOption, type NeighboursResult, type RouteResponse, type RouteResult } from "./lib/api.ts";
import { displacedBy, keptNeighbours, neighbourDials, neighboursSaid, offersNeighbours, rideDials, withNeighbours } from "./lib/neighbours.ts";
import { betterRouteSaid, EarlyStart, takesRefined } from "./lib/progressive.ts";
import { RAIL_STATUS_MS, closedReason, matchAlerts, withMetroClosed, matchClosures, requestClosures, type RailStatus } from "./lib/railClosures.ts";
import { COVERAGE_BBOX, MAX_POINTS, addPoint, haversineM, insideCoverage, type LonLat } from "./lib/geo.ts";
import { formatSeconds } from "./lib/format.ts";
import { presetSaid, twoPointsOnly, usesBikeshare, type PresetId } from "./lib/presets.ts";
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
import {
  NOVICE_TRANSIT_CHOICES,
  noviceOfferShown,
  noviceTransitDials,
  noviceTransitSaid,
  noviceTripOf,
  noviceTripPoints,
  type NoviceTrip,
} from "./lib/noviceOffer.ts";
import {
  CANCELLED_SAID,
  PLANNING_SAID,
  RESET_NOTHING,
  RESET_SAID,
  CLEARED_SAID,
  CLEAR_FOCUS_WAIT_MS,
  changeSummary,
  legChanges,
  elapsedText,
  planChanged,
  planSentences,
  CLEAR_LABEL,
  ROUTING_LABEL,
  routeButton,
  routingStep,
  type DrawnPlan,
} from "./lib/planFirst.ts";
import { PlanPanel } from "./app/PlanPanel.tsx";
import { useHighStressLanes, useMtbTrails } from "./useStressStyle.ts";
import { useStressStyle } from "./useStressStyle.ts";
import { ANNOUNCE_SETTLE_MS } from "./lib/settle.ts";
import { skipToPlanner, SKIP_LINK_TEXT, SKIP_TO_RIDE_TEXT } from "./lib/skipLink.ts";
import { BetaChip, betaReportUrl, isBetaBuild } from "./lib/betaBanner.ts";
import { announceHow } from "./lib/candidates.ts";
import { canReverse, loopStops, loopView, reversedPoints } from "./lib/loop.ts";
import { FINDING_ORDER_SAID, STILL_FINDING_ORDER_SAID, applyAnswer, requestStopOrder, stopsThatMove } from "./lib/stopOrder.ts";
import {
  VIA_MARKS,
  drawnLegs,
  MANUAL_LABEL,
  MANUAL_OFF_SAID,
  MANUAL_ON_SAID,
  MANUAL_TITLE,
  DRAWN_SAID,
  VIA_POINT_NAME,
  addStopWhereShortest,
  isMiddle,
  kindSaid,
  kindSwitchedSaid,
  namePoints,
  stopAddedSaid,
  stopsOnly,
  withVias,
  viaIndices,
  viaPointsNamed,
} from "./lib/pointKinds.ts";
import { insertedSaid, loopChangeSaid,reversedSaid, reverseUnavailableHint, stationSaid } from "./lib/pointText.ts";
import { avoidNearSpot, shownRoute } from "./lib/avoidJunctions.ts";
import { shownNear } from "./lib/junctionSuggest.ts";
import { CHECKING_CLOSURES, CLOSURE_SLOW_MS, RIDE_ENDED_FROM_HERE_SAID, RIDE_ENDED_NO_FIX_SAID, RIDE_ENDED_SAID, RideEnded, RideMode, primeRideVoice, startRideGesture, voiceTurnedOn, type EndedPlan, type RideView } from "./RideMode.tsx";
import { Icon } from "./Icon.tsx";
import { readBigText, readHeadingUp, readRidePrefs, writeBigText, writeHeadingUp, writeRidePrefs, type RidePrefs } from "./lib/rideOutput.ts";
import { activePins, chosenSaid, withStations, type NearbyStation, type Pins, type StationAction } from "./lib/stations.ts";
import { bikeshareOf } from "./lib/bikeshare.ts";
import { carries, hillsWords, seeksClimbs, startDials, stressMax, stressWords, trailsAreOff, type Dials } from "./lib/dials.ts";
import { WeightStore, defaultSplit, withWeight, type StoredWeight } from "./lib/weight.ts";
import { stationEdit, type RailVisibility, type Station, type StationRole } from "./lib/railStations.ts";
import { RAIL_STATIONS, WMATA_SLUGS, stationEntranceForPlace } from "./lib/railData.ts";
import { federalShown, type FederalData } from "./lib/federalLand.ts";
import { FEDERAL_POINTS_NONE, type FederalStatus } from "./lib/federalLegend.ts";
import { federalAreaAt, federalRouteLines, pointAreas, stopWarningShort } from "./lib/federalStops.ts";
import { addCoverageMask, fetchCoverage, watchForCapacity, watchForFacilities, watchCentre, watchZoom } from "./lib/mapGlue.ts";
import { STILL_RIDING_SAID, forgetStaleRideEntry, holdBackDuringRide } from "./lib/rideBack.ts";
import { afterHistoryStep } from "./lib/rideFocus.ts";
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
import { fetchPlaces, pickIntoPlan, placeFromSearch, reverseUrl, searchBiasPoint, type Place, type ViewBounds, type PlaceChoice } from "./lib/geocode.ts";
import { HOME_CLEARED, HOME_PICK_CANCELLED, HOME_PICK_LINE, homeAtSpot, homeFromPlace, homeSetSaid, nameWithoutHome } from "./lib/homeSet.ts";
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
import { canShareLink, shareContent, shareLink, shareSaidFor, withGpxFile } from "./lib/share.ts";
import type { ImportedPlan } from "./lib/gpxPlan.ts";
import { loadWaterRestrooms, readWaterPrefs, saveWaterPrefs, waterAlongRoute, waterTitle, waterVisible, type WaterAlong, type WaterPoint, type WaterPrefs, type WaterStatus } from "./lib/waterRestrooms.ts";
import waterRestroomsUrl from "./amenity-data/water-restrooms.json?url";
import { climbShown, climbsAlongRoute, loadClimbs, readClimbsFrom, readClimbsOn, saveClimbsFrom, saveClimbsOn, type Climb, type ClimbCategory, type ClimbsStatus } from "./lib/climbs.ts";
import { climbEndName, climbEnds, climbNearSpot, rideClimbEdit } from "./lib/climbCard.ts";
// A committed snapshot, deliberately (review CH-7): `manage.py build_climbs` on the build host writes it
// after a rebuild, and the file is copied here and committed. `no-inline`: an inlined data: URL is
// refused by the edge's connect-src 'self' (Caddyfile), so it stays its own hashed file under /assets/.
import climbsUrl from "./climb-data/climbs.json?url&no-inline";
import {
  FOOD_NOT_LOADED,
  FOOD_PAGE,
  NO_FOOD_DATA,
  foodFoundSaid,
  loadFood,
  foodMoreSaid,
  routeForDetour,
  type RouteForDetour,
  searchFood,
  type Bounds,
  type FoodPlace,
  type FoodResult,
  type FoodScope,
} from "./lib/food.ts";
import { FoodFinder } from "./lib/foodFinder.ts";
// food.json is a committed snapshot, as climbs.json, refreshed with scripts/build_food.py and committed;
// places.json is a few bytes until scripts/build_places.py fills it. `no-inline`, as climbs.json: an
// inlined data: URL is refused by the edge's connect-src 'self'. Its own hashed file under
// /assets/ also lets the service worker leave it out of the precache (swCore.mjs LAZY_ASSET).
import foodUrl from "./amenity-data/food.json?url&no-inline";
import placesUrl from "./amenity-data/places.json?url&no-inline";
// trail-miles.json too, until scripts/build_trail_miles.py fills it; precached (not LAZY_ASSET), as a ride's
// 311 report and "Where am I?" read it in a dead spot.
import trailMilesUrl from "./amenity-data/trail-miles.json?url&no-inline";
import { loadTrailMiles, MILE_MIN_ZOOM, type TrailMiles } from "./lib/trailMiles.ts";
import { TrailMilesOverlay } from "./app/trailMilesOverlay.ts";
import { loadRepair, nearestRepair, repairFoundSaid, repairTitle, REPAIR_NO_ORIGIN, REPAIR_UNAVAILABLE, type RepairNearby, type RepairPlace } from "./lib/repair.ts";
import { loadPlaces, placesSaid, placesToSee, readPlacesLayer, savePlacesLayer, sightsForGo, PLACES_NONE, PLACES_PAGE, PLACES_UNAVAILABLE, type PlaceFilter, type SightPlace, type SightResult } from "./lib/places.ts";
import { FoodOverlay, PlacesOverlay, PlacesSheet, RepairSheet, RepairStandsOverlay } from "./app/PlacesSheets.tsx";
import { ScenicOverlay } from "./app/ScenicOverlay.tsx";
import { readScenicLayer, saveScenicLayer, scenicShown, scenicStatus } from "./lib/scenicLayer.ts";
import {
  findingSaid,
  requestNearest,
  searchNearest,
  NEAREST_STALE,
  NO_FIX_YET,
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
import { anyKept, askPersist } from "./lib/offlineRouteStore.ts";
import { YourRoutes } from "./YourRoutes.tsx";
import { asKept, namesToKeep, rideAfterImport, type Ride } from "./lib/gpxEdit.ts";
import { followLine } from "./lib/gpxMatch.ts";
import { fetchHazards, type HazardCollection } from "./lib/massHazards.ts";
import { visibleCentreOffset } from "./lib/visibleCentre.ts";
import { NARROW, useLongerThan, useMinute, useNarrow, useSettled } from "./app/hooks.ts";
import { routeLightMarks, sameLightMarks, type LightMark } from "./lib/lightTimes.ts";
import { PointsSection, RideSection } from "./app/Planner.tsx";
import { RouteSection, ShareControls, type Status } from "./app/RoutePanel.tsx";
import { EditRouteSheet, FoodSheet, GpxSheet, LayersSheet, LegendSheet, NearestSheet, RideChips, RideGroupChips, RideSheet, SettingsSheet, SuggestSheet, type SheetNav } from "./app/Sheets.tsx";
import { GoAddStop, GoRouteCard, GoSheet, GoTopBar, ModeSwitch, PlanMapChips } from "./app/Go.tsx";
import { useSharedLaunch } from "./app/sharedLaunch.ts";
import { NearestFinder } from "./lib/nearestFinder.ts";
import { NearbyStations } from "./NearbyStations.tsx";
import { Fold } from "./Sidebar.tsx";
import { BACK_LABEL, SHEET_TITLES, backFrom, openOnto, type Opened } from "./lib/sidebar.ts";
import { announceLevel, readAnnounceChoice, saysExtra, writeAnnounceChoice, type AnnounceChoice, type AnnounceLevel } from "./lib/announceLevel.ts";
import { letterKeyIndex, letterPlaces, placeLetter } from "./lib/letteredPlaces.ts";
import { FIRST_ANSWER_PINS, keepOptions, keepsFirst, optionName, optionPins, optionReplaySaid, optionSaid, optionsKey, pickedOption, replayFor, replaysFirst, sentPlanKey, stationlessUnavailable, type FirstAnswer, type KeptOptions } from "./lib/bikeshareOptions.ts";
import { GO_START_SAID, GO_START_UNAVAILABLE, goHereStart, goStartStale, goDestinationLocating, goDestinationNeedsStart, goPickAction, goPlaceName, goStartLine, YOUR_LOCATION, goTapRoutedSaid, goTapSetsEnd, goPressLocatingSaid, goPressNeedsStartSaid, goDestinationNeedsStartBecause, goPressNeedsStartBecause, GO_PRESS_LOCATING_SAY_MS, hasPlanLink, laterMyGoApplies, modeSaid, openingMode, readLastReview, readTabMode, reopenReview, shouldAskGoStart, switchModes, writeLastReview, writeTabMode, type AppMode, type GoStart } from "./lib/appMode.ts";
import { ReviewMode } from "./ReviewMode.tsx";
import type { ListKey } from "./lib/review.ts";
import { MY_GO_NOT_SAVED, MY_GO_SAVED, MY_GO_SAVED_DEVICE, fetchMyGo, goRideChips, OWN_RIDE_HINT, readStartMyGo, saveAccountCopy, saveDeviceMyGo, saveMyGo, type Home, type MyGo } from "./lib/myGo.ts";
import { optionChosenSaid, transitOf, withTransitOption, type TransitPick } from "./lib/transit.ts";
import { REST_ANYWAY_MS, RIDE_REST_FINDING, fixedRide, restClosedSaid, restRequest, rideLegOf, rideTripOf, rideable as rideableRoute, type RideTrip } from "./lib/rideTrip.ts";
import { RIDE_TOO_LONG } from "./lib/navigate.ts";
import { fetchMe, NO_ME, type Me } from "./lib/stressEditor.ts";
import { ACCOUNT_SETTINGS_USED, applyToDevice, deviceSettings, fetchSettings, onSignIn, planFromSetting, sameSettings, saveSettings, SAVE_SETTLE_MS, type SettingsDoc } from "./lib/accountSettings.ts";
import { HOME_KEPT, HOME_MOVED, answerHomeOffer, deviceHome, homeOffer, type HomeOffer } from "./lib/homeMove.ts";
import { OPENED_SAID, SAVED_SAID, SAVE_FAILED, UNCHANGED_SAID, UPDATE_ROUTE, VERSION_SAID, defaultRouteName, differenceLine, differsTooMuch, gpxSave, afterDelete, afterRename, planSave, saveAsVersion, savedAnswer, versionOf, type OpenSaved, type SavedRoute } from "./lib/savedRoutes.ts";
import { checkClosures, closedStretches, reroutedSaid, spliceDetours, type Closure, type CheckFor } from "./lib/closureCheck.ts";
import { downloadText, trackGpx, verbatimDownload, verbatimFileName } from "./lib/gpxVerbatim.ts";
import { readGpx } from "./lib/gpxImport.ts";
import { GPX_SAID_OPENED, GPX_SAID_ROUTE, GPX_SAID_TRACK, downloadCourse, downloadGpx, routeGpxFile, sendCourseToGarmin, type FileFormat, type Said } from "./GpxPanel.tsx";
import type { DeviceProfileId } from "./lib/deviceProfiles.ts";
import { SHARED_GONE, SHARED_INPUTS_ONLY, SHARED_OPENED, SHARED_PATH, SHARED_REVOKED, SHARED_REVOKED_ERROR, SHARE_KEEP_DEFAULT, SHARE_RIDE_WAIT, asRideLink, gpxShareFile, keepFields, newSharedId, previewImageOk, readShared, rideLinkFrom, sharedBody, sharedIdFrom, storeShared, withSharedId, type ShareKeep } from "./lib/sharedRoutes.ts";
import { ClosureDialog, type ClosureAsk } from "./ClosureDialog.tsx";
import { ShareCardDialog, type ShareCardSource } from "./ShareCardDialog.tsx";
import { usableProfile } from "./lib/profileChart.ts";
import { bypassFor, bypassPlanKey, bypassSaid, toggleBypass, type Bypass } from "./lib/closureMap.ts";
import { permitsShown, readPermitsLayer, savePermitsLayer } from "./lib/permitLayer.ts";
import { RideGroup } from "./RideGroup.tsx";
import { BikeshareDocksOverlay, type DocksReport } from "./BikeshareDocks.tsx";
import { KNOWN_OPERATORS, docksStatus, mergeOperators, operatorsToAsk, readOperatorChoices, saveOperatorChoices, type OperatorInfo } from "./lib/bikeshareDocks.ts";
import { SaveRoute } from "./SaveRoute.tsx";
import { SAVE_ROUTE } from "./lib/savedRoutes.ts";
import { isRideLink, type RideLinkType } from "./lib/rideGroup.ts";

// Before the map adds the stress source (MapView, after its first probe).
// With Ride mode's kept tiles behind the network, for dead spots (lib/corridorStore.ts).
registerStressProtocol(maplibregl, undefined, corridorStress);

/**
 * One entry of the undo history: the points as they were, and, for an edit
 * that also changed the ride type or the opened file (a GPX import, or Clear
 * of an imported plan), those too, so undo takes the whole edit back.
 */
type Snapshot = PlanSnapshot<LonLat[], Ride>;

/** The plan the drawn route answers, for Plan mode's Reset, its change summary and its per-leg details (v0.7.0). */
type Drawn = DrawnPlan<Ride> & { route: RouteResponse; loop: boolean; pins: Pins; transitPick: TransitPick | null };

interface Plan {
  points: LonLat[];
  preset: PresetId;
  confirmLong: boolean;
  dials: Dials;
  /** The ride as the rider set it, and its dials' key (App's routeKey): what Plan mode's Reset goes back to. */
  ride?: Ride;
  dialsKey?: string;
  /** Plan mode's Route button asked for it (v0.7.0): its answer says what changed. */
  pressed?: boolean;
  /** The stations and the transit option chosen with it: Reset puts them back too. */
  pins?: Pins;
  transitPick?: TransitPick | null;
  /** Go (v0.7.0, "Faster routing"): the first good route at once, then its full plan (lib/progressive.ts). */
  quick?: boolean;
}

const initialPlan = decodePlan(planToOpen(tabSession(), window.location.hash));
// The link's via points (v0.7.0, lib/pointKinds.ts): an older link has none, so every point is a stop.
VIA_MARKS.markAt(initialPlan.points, initialPlan.vias);
// And its legs drawn in Plan's manual mode (v0.9.1); an older link has none.
VIA_MARKS.markDrawn(initialPlan.points, initialPlan.drawn);

// Go or Plan (lib/appMode.ts; the owner's choices 1 and 2 of 2026-10-11): the tab's own view, else Plan for a
// link with a plan in it, else My Go's Open in (the account's copy or this device's), else by screen size.
const START_MY_GO = readStartMyGo();
/** A Go sheet's way back: to the map and the Go sheet, not a planner it does not show. */
const GO_CLOSE_LABEL = "Close";
/** Go's early start (v0.7.0, "Faster routing" step 4) asks only for trips up to this straight-line length (25 mi). */
const GO_EARLY_MAX_KM = 40;
/** A fresh location this far (about 80 ft) from the last one lists the places near you again from it. */
const MOVED_M = 25;
const PLAN_LINK = hasPlanLink(window.location.hash) || initialPlan.points.length > 0;
const OPENING = openingMode({ tab: readTabMode(), planLink: PLAN_LINK, openIn: START_MY_GO.myGo.openIn, wide: !window.matchMedia(NARROW).matches });
// Go with nothing linked starts on My Go's ride type (the rider's saved settings, used as they are).
const GO_START_RIDE = OPENING.mode === "go" && !PLAN_LINK && START_MY_GO.myGo.ride ? START_MY_GO.myGo.ride : null;
// A spot link (`#at=lon,lat`, a rider suggestion's Discord post): the map opens there.
const OPEN_AT = atFromHash(window.location.hash);
// A shared route's link (v0.7.0, "share the identical route"; lib/sharedRoutes.ts): the exact line it names is
// read before the link's first plan is answered, so the line opens unchanged rather than planned again.
// A link opened at its preview path (`/s/<id>`) or sent on from it (`/?route=<id>`) names the id there; the address
// then becomes the page's own, so a link copied later is the plan's, not the old shared one.
const SHARED_ID = sharedIdFrom(window.location.hash, window.location.search, window.location.pathname);
// Shared as a ride (Share ride; lib/sharedRoutes.ts RIDE_PARAM), not only as a route.
const SHARED_RIDE = SHARED_ID !== null && rideLinkFrom(window.location.hash, window.location.search);
if (SHARED_ID && (window.location.pathname.startsWith(SHARED_PATH) || new URLSearchParams(window.location.search).has("route"))) {
  const query = new URLSearchParams(window.location.search);
  query.delete("route");
  window.history.replaceState(window.history.state, "", `/${query.size ? `?${query}` : ""}${window.location.hash}`);
}
let sharedArrived: () => void = () => {};
// Its owner turned the link off: the plan it carries is not planned (the first plan after the wait, and that plan
// again on Try again); the page says so plainly (SHARED_REVOKED).
let sharedRevoked = false;
let revokedPlan: string | null = null;
const SHARED_WAIT: Promise<void> | null = SHARED_ID
  ? new Promise<void>((resolve) => {
      sharedArrived = resolve;
    })
  : null;

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
  // The view now, for callbacks kept across renders (a map tap: lib/appMode.ts goTapSetsEnd).
  const modeRef = useRef(mode);
  modeRef.current = mode;
  // The rider's own My Go (lib/myGo.ts): the account's when signed in, this device's when not.
  const [myGo, setMyGo] = useState<MyGo>(START_MY_GO.myGo);
  const [myGoSaid, setMyGoSaid] = useState("");
  // Go's Home sheet, "Pick on the map": the next tap on the map is Home (lib/homeSet.ts).
  const [homePick, setHomePick] = useState(false);
  const homePickRef = useRef(homePick);
  homePickRef.current = homePick;
  // /api/me's flags: signed in (My Go to the account, the Home chip) and an instance admin (Review).
  const [me, setMe] = useState<Me>(NO_ME);
  // Review, the third view (lib/appMode.ts switchModes): an instance admin's, or a closures reviewer's.
  // Review (the third mode) is an instance admin's alone: a closures reviewer who is not one marks closures in the road
  // panel, as before, and never sees the mode.
  const canReview = me.can_change_lts;
  // The list Review shows: Suggest's Review button opens the riders' suggestions.
  const [reviewList, setReviewList] = useState<ListKey | undefined>(undefined);
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
  // The transit option the rider chose from the list (lib/transit.ts), for this trip only: a new
  // start or end, or another ride type, starts from the quickest again. Request only, never the link.
  const [transitPick, setTransitPick] = useState<TransitPick | null>(null);
  const trip = optionsKey(points, preset);
  // "Route through anyway" (v0.7.0, lib/closureMap.ts): the closures the rider chose to route through, for this plan
  // (its start and end) only; request only, never the link. Undo takes one back out.
  const [closureBypass, setClosureBypass] = useState<Bypass | null>(null);
  const bypassPlan = bypassPlanKey(points);
  const bypassIds = bypassFor(closureBypass, bypassPlan);
  const bypassKey = bypassIds.join(",");
  // Go routes round only the closures known to be on, not DDOT's permits, which say a road may be closed (v0.9.1,
  // lib/dials.ts closuresNow); Plan keeps them, for planning a later ride. Start ride and a ride's re-plans set it too.
  const goNow = mode === "go";
  const planDials = useMemo(() => {
    const made = withTransitOption(withStations(withWeight(routeDials, weight), stationChoice), preset, transitPick, trip);
    const now = goNow ? { ...made, closuresNow: true } : made;
    return bypassIds.length ? { ...now, closureBypass: bypassIds } : now;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the ids' text, not the array
  }, [routeKey, weight, stationChoice, preset, transitPick, trip, bypassKey, goNow]);
  // Everything the request is made from, as a key (v0.7.0): in Plan a station or a transit option chosen, a
  // weight or a slider moved, all mark the plan changed until Route or Update route.
  // The key leaves closuresNow out: switching between Go and Plan keeps the route (changeMode), not marked changed.
  const planKey = useMemo(() => {
    const { closuresNow: _now, ...keyed } = planDials;
    return JSON.stringify(keyed);
  }, [planDials]);
  // The dials as they are, for Go's early start (v0.7.0, "Faster routing" step 4), which asks before the tap.
  const planDialsNow = useRef(planDials);
  planDialsNow.current = planDials;
  // "Make it a loop" chosen (OWNER-DECISIONS 374): the first point is the start and finish, every later one a stop.
  const loopVias = loopStops(preset, dials.loop);
  // Plan's manual mode (v0.9.1, Stephen 2026-10-19: "a 'manual mode' where you can just route directly"): while
  // on, each point tapped on the map is joined to the one before by a straight line, not a route. Not on a loop or
  // a two-point ride type, where the API plans every leg (core/routing.py `_drawn`).
  const [manualOn, setManualOn] = useState(false);
  const manualOffered = mode === "plan" && !loopVias && !twoPointsOnly(preset);
  const manual = manualOn && manualOffered;
  const manualRef = useRef(manual);
  manualRef.current = manual;
  // Off whenever it is not offered (Go, a loop, a two-point ride type), so it never comes back on unseen.
  useEffect(() => {
    if (!manualOffered) setManualOn(false);
  }, [manualOffered]);
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
  // Go's More direct and Calmer (lib/neighbours.ts): asked for once the route shown is final, kept with the answer they
  // are for, and offered after its own routes to choose from, in place of its last ones where the choice is full. The
  // answer itself never changes for them, so its route is not said again and the choice is not reset when they come.
  // `keepRouter`: the routes to choose from the rider had already chosen among when they came, which stay in place.
  const [neighbours, setNeighbours] = useState<{
    answer: RouteResponse;
    preset: PresetId;
    dials: Dials;
    options: NeighbourOption[];
    keepRouter: number;
  } | null>(null);
  const kept = useMemo(
    () =>
      neighbours && answer && neighbours.answer === answer
        ? keptNeighbours(answer, neighbours.options, neighbours.preset, neighbours.dials, neighbours.keepRouter)
        : [],
    [neighbours, answer],
  );
  const picked = useMemo(() => withNeighbours(answer, kept), [answer, kept]);
  // The rider's own route stays the same object when the options come, so nothing keyed on it (the map's fit, its
  // sentence) runs again for them.
  const route = choice === 0 ? shownRoute(answer, 0, aroundAvoid) : shownRoute(picked, choice, aroundAvoid);
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
  // The rail stations with no service all day (railClosures.ts): struck through and greyed on the
  // map, and "closed" in their cards and lists; with WMATA's live closures and its badges (a station an
  // alert names, an elevator out). Asked every few minutes while the page is in view, since WMATA's
  // change within the day, and as soon as it is back in view.
  const [railStatus, setRailStatus] = useState<RailStatus>({ stations: [], alerts: [] });
  useEffect(() => {
    const controller = new AbortController();
    let asking = false;
    let askedAt = 0;
    const check = () => {
      if (asking || document.visibilityState === "hidden" || Date.now() - askedAt < RAIL_STATUS_MS - 1000) return;
      asking = true;
      void requestClosures({ signal: controller.signal }).then((status) => {
        asking = false;
        if (controller.signal.aborted) return;
        // Only an answer counts: a failure is asked again at the next check, the last answer kept.
        if (status === null) return;
        askedAt = Date.now();
        setRailStatus(status);
      });
    };
    check();
    const timer = window.setInterval(check, 60 * 1000);
    document.addEventListener("visibilitychange", check);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
  const railClosures = useMemo(() => matchClosures(RAIL_STATIONS, railStatus.stations), [railStatus]);
  const railBadges = useMemo(() => matchAlerts(RAIL_STATIONS, railStatus.alerts), [railStatus]);
  const railClosedReason = useCallback((station: Station) => closedReason(station, rail, railClosures), [rail, railClosures]);
  const railBadgesOf = useCallback(
    (station: Station) => withMetroClosed(railBadges.get(station.id) ?? null, station, rail, railClosures),
    [railBadges, rail, railClosures],
  );
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
  // v0.7.0: repair stands and bike shops (the same file; the stands are drawn with the water layer's switch),
  // and the places to see (their own layer, off by default, kept on this device). Each loaded when first needed;
  // a load that failed is asked again next time.
  const [repairData, setRepairData] = useState<RepairPlace[] | "unavailable" | null>(null);
  const repairLoad = useRef(false);
  const ensureRepair = useCallback(() => {
    if (repairLoad.current) return;
    repairLoad.current = true;
    void loadRepair(waterRestroomsUrl).then((data) => {
      if (!data) repairLoad.current = false;
      setRepairData(data ?? "unavailable");
    });
  }, []);
  useEffect(() => {
    if (waterOn) ensureRepair();
  }, [waterOn, ensureRepair]);
  // Bikeshare docks and free e-bikes (v0.7.0; BikeshareDocks.tsx): shown while Capital Bikeshare's switch in
  // Layers is on. It is on by default in the bikeshare ride types and off in the others (the owner, 2026-10-17),
  // each choice kept on this device apart.
  const bikeshareRide = usesBikeshare(preset) || preset === "bikeshare-transit";
  const [docksOperators, setDocksOperators] = useState<OperatorInfo[]>(() => [...KNOWN_OPERATORS]);
  const [docksChoicesByRide, setDocksChoicesByRide] = useState(() => ({
    bikeshare: readOperatorChoices(KNOWN_OPERATORS, undefined, true),
    other: readOperatorChoices(KNOWN_OPERATORS, undefined, false),
  }));
  const docksChoices = bikeshareRide ? docksChoicesByRide.bikeshare : docksChoicesByRide.other;
  const [docksReport, setDocksReport] = useState<DocksReport>({ answer: null, asked: false, zoom: 0 });
  const changeDocksChoices = (next: Record<string, boolean>) => {
    setDocksChoicesByRide((all) => (bikeshareRide ? { ...all, bikeshare: next } : { ...all, other: next }));
    saveOperatorChoices(next, undefined, bikeshareRide);
  };
  const onDocksReport = useCallback((report: DocksReport) => {
    setDocksReport(report);
    if (report.answer) setDocksOperators((known) => mergeOperators(known, report.answer!.operators));
  }, []);
  const docksAsk = useMemo(() => operatorsToAsk(docksChoices, docksOperators), [docksChoices, docksOperators]);
  const docksActive = docksAsk.length > 0;
  const [placesOn, setPlacesOnState] = useState<boolean>(() => readPlacesLayer());
  const changePlacesOn = (on: boolean) => {
    setPlacesOnState(on);
    savePlacesLayer(on);
  };
  const [placesData, setPlacesData] = useState<SightPlace[] | "unavailable" | null>(null);
  const placesLoad = useRef(false);
  const ensurePlaces = useCallback(() => {
    if (placesLoad.current) return;
    placesLoad.current = true;
    void loadPlaces(placesUrl).then((data) => {
      if (!data) placesLoad.current = false;
      setPlacesData(data ?? "unavailable");
    });
  }, []);
  // The Scenic layer (v0.8.0; lib/scenicLayer.ts): one switch in Plan's Layers, off by default, kept on this
  // device. Its covered bridges and viewpoints are Places to see's file, fetched the first time it is shown.
  const [scenicOn, setScenicOnState] = useState<boolean>(() => readScenicLayer());
  // DC permits (v0.9.1; lib/permitLayer.ts): one switch in Plan's Layers, off by default, kept on this device. A permit
  // is never routed round; on, Plan's map draws the ones near the route, dashed.
  const [permitsOn, setPermitsOnState] = useState<boolean>(() => readPermitsLayer());
  const changePermitsOn = (on: boolean) => {
    setPermitsOnState(on);
    savePermitsLayer(on);
  };
  const changeScenicOn = (on: boolean) => {
    setScenicOnState(on);
    saveScenicLayer(on);
  };
  useEffect(() => {
    if (placesOn || scenicOn) ensurePlaces();
  }, [placesOn, scenicOn, ensurePlaces]);
  const [placesFilter, setPlacesFilter] = useState<PlaceFilter>("all");
  const [placesCount, setPlacesCount] = useState(PLACES_PAGE);
  // Bumped by each Repair, Sights or Places to see press, so the list is from where the rider is then.
  const [placesAsked, setPlacesAsked] = useState(0);
  // The Climbs layer (lib/climbs.ts; 454): off until turned on, kept on this device; the data is
  // fetched the first time it is shown. An empty file (before the build host has measured any) is
  // "empty", not "unavailable".
  const [climbsOn, setClimbsOnState] = useState<boolean>(() => readClimbsOn());
  const changeClimbsOn = (on: boolean) => {
    setClimbsOnState(on);
    saveClimbsOn(on);
  };
  // "Show climbs from" (the owner, 2026-10-12): the smallest category shown, kept on this device as the switch is.
  const [climbsFrom, setClimbsFromState] = useState<ClimbCategory>(() => readClimbsFrom());
  const changeClimbsFrom = (from: ClimbCategory) => {
    setClimbsFromState(from);
    saveClimbsFrom(from);
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
  const [, setEditPoints] = useState(false);
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
  // `pressed`: set by a press on the map (said "Destination set" with what it waits for); `said`: that was said already.
  const goPending = useRef<{ dest: LonLat; name: string; vias?: LonLat[]; pressed?: boolean; said?: boolean } | null>(null);
  // Set when a Go destination found Use my location's gate busy: the look-up under way answers for it (settleGoWaiting).
  const goAwaiting = useRef(false);
  // A Go destination just picked (v0.7.0, "Faster routing" step 4): its route is asked for at once, not after the
  // debounce that folds a burst of edits into one request.
  const goPickedNow = useRef(false);
  // Nothing waits any more: the destination routed, or dropped (leaving Go).
  const clearGoPending = () => {
    goPending.current = null;
    goAwaiting.current = false;
  };
  // Leaving Go (the switch, or the account's Open in once read): Plan does not route a destination Go was keeping
  // for a start, and its notice ("To <spot>: finding your location…") goes with it.
  const leaveGo = () => {
    if (goPending.current) setNotice(null);
    clearGoPending();
  };
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
  // On a Bikeshare or transit plan, the points, loop and ride type are the riding leg's (lib/rideTrip.ts
  // rideLegOf), with what is said around it (`trip`); `n` counts the rides, so Ride the rest starts afresh.
  const [rideStart, setRideStart] = useState<{
    route: RouteResponse;
    points: LonLat[];
    loop: boolean;
    dials: Dials;
    preset: PresetId;
    trip: RideTrip | null;
    /** The route everyone shares: never re-planned on its own during the ride (RideMode `fixed`). */
    fixed: boolean;
    n: number;
  } | null>(null);
  const [rideAsk, setRideAsk] = useState(false);
  const [rideView, setRideView] = useState<RideView | null>(null);
  const [follow, setFollow] = useState(true);
  // Track-up by default in a ride (v0.7.0, "Go riding fixes" item 1); the ride settings' switch is the
  // option, kept on this device. Turning the map never moves the keyboard focus.
  const [headingUp, setHeadingUpState] = useState(() => readHeadingUp());
  const setHeadingUp = useCallback((on: boolean) => {
    writeHeadingUp(on);
    setHeadingUpState(on);
  }, []);
  // Big text is a setting kept on this device, not a ride button (the owner, 2026-10-17: "not something people will fiddle with mid ride").
  const [bigText, setBigTextState] = useState(() => readBigText());
  const setBigText = useCallback((on: boolean) => {
    writeBigText(on);
    setBigTextState(on);
  }, []);
  const startRideRef = useRef<HTMLButtonElement>(null);
  const rideStartFirstRef = useRef<HTMLButtonElement>(null);
  // The Start ride button pressed (under the figures or in Directions): where the focus goes back to.
  const rideOpener = useRef<HTMLElement | null>(null);
  const rideCircle = rideView?.rider ? { centre: rideView.rider.point, radiusM: rideView.rider.accuracyM } : null;
  const ridePrefsNow = useRef(ridePrefs);
  ridePrefsNow.current = ridePrefs;
  const ridingNow = useRef(riding);
  ridingNow.current = riding;
  // Trail mile markers (lib/trailMiles.ts; OWNER-DECISIONS 465): fetched once the map is at the trail zooms,
  // a ride starts or the road panel opens, and kept; a load that failed is asked again next time. No switch.
  const [trailMiles, setTrailMiles] = useState<TrailMiles | null>(null);
  const milesLoad = useRef(false);
  const milesWanted = riding || roadInfo !== null || (zoom !== null && zoom >= MILE_MIN_ZOOM);
  useEffect(() => {
    if (!milesWanted || milesLoad.current) return;
    milesLoad.current = true;
    void loadTrailMiles(trailMilesUrl).then((data) => {
      if (!data) milesLoad.current = false;
      setTrailMiles(data);
    });
  }, [milesWanted]);
  const changeRidePrefs = useCallback((next: RidePrefs) => {
    // Voice turned on mid-ride: unlocked in this change's own gesture, as Start does (review RIDE-9).
    // Before a ride, Start unlocks it; nothing is said then.
    if (ridingNow.current) voiceTurnedOn(ridePrefsNow.current, next);
    writeRidePrefs(next);
    setRidePrefs(next);
  }, []);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Where the map's centre is drawn while the crosshair shows (review UI-2): after a padded move it
  // is not the middle of the map, and Map tools' actions use the centre.
  const crosshairShown = crosshair.button || crosshair.canvas;
  const [crosshairAt, setCrosshairAt] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!crosshairShown || !map) return;
    return watchCentre(map, setCrosshairAt);
  }, [crosshairShown]);
  const panelRef = useRef<HTMLElement>(null);
  const panelBodyRef = useRef<HTMLDivElement>(null);
  const removeRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const planButtonRef = useRef<HTMLButtonElement>(null);
  const routeHeadingRef = useRef<HTMLHeadingElement>(null);
  const pointsHeadingRef = useRef<HTMLHeadingElement>(null);
  const focusAfterRemove = useRef<number | null>(null);
  const writtenHash = useRef<string>("");
  const { gate: geoGate, namer } = usePlaceNames(points);
  // A route's own name (a save, a shared line, a GPX file) never carries the Home's label (review privacy-2).
  const fileNamed = nameWithoutHome((point) => namer.name(point)?.name, myGo.home?.point ?? null);

  // One scheduler for the page: one request in flight, the latest plan only,
  // Retry-After waited out (routeScheduler.ts).
  const scheduler = useRef<RouteScheduler<Plan, NeighboursResult> | null>(null);
  // A route kept for offline (WEB-NAV-plan.md section 8, P3) answers when the planner cannot be reached
  // and the plan is one the rider kept; the planner's notice says so, and the next real answer clears it.
  const keptShown = useRef<KeptRoute<RouteResponse> | null>(null);
  // A saved route reopened (v0.7.0, saved routes): its line as saved answers its plan, unchanged, until the
  // plan changes or the rider presses Update route.
  const savedShown = useRef<{ key: string; answer: RouteResponse } | null>(null);
  const keptNotice = useRef<string | null>(null);
  // The plan the route on screen answers, as a kept route's key (keptPlanKey): set with the route, so a
  // keep during a re-plan in flight files the route shown under its own plan, never the next one's.
  const routedKey = useRef<string | null>(null);
  // Go's Bikeshare options: the answer that listed them, and a free e-bike's option asking for it again
  // (lib/bikeshareOptions.ts replaysFirst: that option has no station id to re-plan with).
  const firstAnswer = useRef<FirstAnswer<RouteResponse> | null>(null);
  const replayAsked = useRef<string | null>(null);
  // Go's first route, then a better one (v0.7.0, "Faster routing"; lib/progressive.ts): what the full plan reads when
  // it comes (the route shown, and whether the rider has pressed Start), and the route sentence held while a full
  // plan replaces its first route, so the swap is said once, by its own line.
  const shownNow = useRef<{ answer: RouteResponse | null; riding: boolean; startAsked: boolean; choice: number }>({
    answer: null,
    riding: false,
    startAsked: false,
    choice: 0,
  });
  shownNow.current = { answer, riding, startAsked: rideAsk, choice };
  const routeSaidNow = useRef("");
  const [refinedHeld, setRefinedHeld] = useState<{ route: RouteResponse; said: string } | null>(null);
  // Go's early start (step 4): a request made before the tap, kept for the tap that makes the same request.
  const earlyStart = useRef<EarlyStart | null>(null);
  if (earlyStart.current === null) {
    earlyStart.current = new EarlyStart({ allowed: () => modeRef.current === "go" && !shownNow.current.riding && !scheduler.current?.busy() });
  }
  if (scheduler.current === null) {
    scheduler.current = new RouteScheduler<Plan, NeighboursResult>({
      send: async (plan) => {
        // A shared route's link: its line first (openSaved sets savedShown), then this plan.
        if (SHARED_WAIT) await SHARED_WAIT;
        if (sharedRevoked && (revokedPlan ??= sentPlanKey(plan.points, plan.preset, plan.dials)) === sentPlanKey(plan.points, plan.preset, plan.dials))
          return { ok: false, error: SHARED_REVOKED_ERROR };
        const saved = savedShown.current;
        if (saved && saved.key === keptPlanKey(plan.points, plan.preset, plan.dials)) {
          keptShown.current = null;
          return { ok: true, route: saved.answer };
        }
        savedShown.current = null;
        const replay = replayFor(firstAnswer.current, replayAsked.current, sentPlanKey(plan.points, plan.preset, plan.dials));
        replayAsked.current = null;
        if (replay) {
          keptShown.current = null;
          return { ok: true, route: replay };
        }
        // An opened file not edited since follows its line exactly (core/follow.py), whatever the ride type.
        const follow = followLine(importBase.current, plan.points, plan.dials.loop);
        // Its manual mode (Plan's "Follow the file exactly"): rules or not, as for a road closed for a parade. Plan
        // only, where the switch is: Go keeps to the rules.
        const followExact = follow !== undefined && importBase.current?.exact === true && modeRef.current === "plan";
        const asked = {
          confirmLong: plan.confirmLong,
          dials: plan.dials,
          vias: viaIndices(plan.points, VIA_MARKS.isVia),
          straight: drawnLegs(plan.points),
          quick: plan.quick,
          follow,
          followExact,
        };
        // Asked for already, before the tap (Go's early start): that request's answer, not a second request.
        const early = earlyStart.current?.take(routeRequestBody(plan.points, plan.preset, asked)) ?? null;
        const result = early
          ? await early.catch(() => requestRoute(plan.points, plan.preset, asked))
          : await requestRoute(plan.points, plan.preset, asked);
        // The API could not follow this file (core/follow.py): its fitting rounds are planned, not traced again.
        if (follow && result.ok && !result.route.follows_file && importBase.current) importBase.current.unfollowed = true;
        keptShown.current = null;
        // A kept route is keyed by the plan alone, not the manual mode: none stands in for one followed exactly.
        if (result.ok || result.error.kind !== "network" || followExact) return result;
        const kept = await keptAnswerFor<RouteResponse>(keptPlanKey(plan.points, plan.preset, plan.dials, viaIndices(plan.points, VIA_MARKS.isVia))).catch(() => undefined);
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
          if (usesBikeshare(plan.preset) && keepsFirst(bikeshareOf(result.route)))
            firstAnswer.current = { key: sentPlanKey(plan.points, plan.preset, plan.dials), trip: optionsKey(plan.points, plan.preset), route: result.route };
          // Plan mode (v0.7.0, lib/planFirst.ts): the plan this route is drawn for, for Reset and for what the
          // next update changes; an update pressed for keeps the old line as a dashed ghost, with a summary.
          const before = drawnRef.current;
          const drawnNow: Drawn = {
            points: plan.points,
            ride: plan.ride ?? rideRef.current,
            dialsKey: plan.dialsKey ?? "",
            route: result.route,
            loop: loopStops(plan.preset, plan.dials.loop),
            pins: plan.pins ?? {},
            transitPick: plan.transitPick ?? null,
          };
          drawnRef.current = drawnNow;
          setDrawn(drawnNow);
          if (plan.pressed && before) {
            setGhost(before.route.geometry.coordinates);
            setChangeLine(changeSummary(before.route, result.route));
            // The per-leg details behind the summary's tap (inverted pyramid).
            setChangeDetails(legChanges(before, drawnNow, VIA_MARKS.isVia, (p) => namer.name(p)?.name));
          }
          setRoute(result.route);
          setRoutedPoints(plan.points);
          setRoutedLoop(loopStops(plan.preset, plan.dials.loop));
          routedKey.current = keptPlanKey(plan.points, plan.preset, plan.dials, viaIndices(plan.points, VIA_MARKS.isVia));
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
      // Go's first route (v0.7.0, "Faster routing"): its full plan is asked for once it is shown.
      refine: (plan: Plan, shown: RouteResult) =>
        shown.ok && shown.route.provisional
          ? () =>
              requestRoute(plan.points, plan.preset, {
                confirmLong: plan.confirmLong,
                dials: plan.dials,
                vias: viaIndices(plan.points, VIA_MARKS.isVia),
                straight: drawnLegs(plan.points),
              })
          : null,
      // The full plan replaces the first route before Start only, and is said once where it is another route; the
      // focus stays where it is, and the route's own sentence is not said again.
      onRefined: (plan: Plan, result: RouteResult) => {
        const now = shownNow.current;
        if (!result.ok || !takesRefined(now.answer, now.riding, now.startAsked) || !now.answer) return;
        // A first route not yet said (it stood less than a moment) is not held: the full plan's sentence is the one said.
        const heard = routeSaidNow.current;
        const line = heard ? betterRouteSaid(now.answer, result.route) : null;
        if (heard) setRefinedHeld({ route: result.route, said: heard });
        drawnRef.current = drawnRef.current ? { ...drawnRef.current, route: result.route } : drawnRef.current;
        if (drawnRef.current) setDrawn(drawnRef.current);
        setRoute(result.route);
        routedKey.current = keptPlanKey(plan.points, plan.preset, plan.dials, viaIndices(plan.points, VIA_MARKS.isVia));
        if (line) setNoticeSaying(line, line);
      },
      // Go's More direct and Calmer (lib/neighbours.ts), once the route shown is final: one request for both, at the
      // lowest priority, so nothing waits for it (a re-plan, Start or a ride's re-route goes at once). Not once Start is
      // pressed or a ride is on, not for a long ride, and not on a ride type that offers neither.
      after: (plan: Plan, final: RouteResult) => {
        const now = shownNow.current;
        if (!final.ok || final.route.provisional || modeRef.current !== "go" || now.riding || now.startAsked) return null;
        // Nor for a plan with legs drawn in Plan's manual mode: the rider drew that way on purpose.
        if (!offersNeighbours(plan.preset) || plan.confirmLong || drawnLegs(plan.points).length) return null;
        // Bikeshare keeps the plan's own docks: only the ride between them changes.
        const dials = neighbourDials(plan.preset, plan.dials, final.route);
        if (!dials) return null;
        return () => requestNeighbours(plan.points, plan.preset, { dials, vias: viaIndices(plan.points, VIA_MARKS.isVia) });
      },
      onAfter: (plan: Plan, result: NeighboursResult) => {
        const now = shownNow.current;
        if (!result.ok || !now.answer || now.answer.provisional || now.riding) return;
        const answer = now.answer;
        // Only the answer's own routes count as kept in place; options already shown for this answer keep their rows.
        setNeighbours((before) => ({
          answer,
          preset: plan.preset,
          dials: plan.dials,
          options: result.options,
          keepRouter:
            before && before.answer === answer ? before.keepRouter : Math.min(now.choice, answer.candidates?.length ?? 0),
        }));
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
    const hash = encodePlan(points, preset, dials, viaIndices(points, VIA_MARKS.isVia));
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
      // A plan opened from a link opens drawn, in Plan as in Go (v0.7.0), and is not compared with the last one.
      forgetDrawn();
      setRouteAsk((n) => n + 1);
      setPoints(VIA_MARKS.markDrawn(VIA_MARKS.markAt(plan.points, plan.vias), plan.drawn));
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

  // Plan mode: write the plan first, then route (v0.7.0, lib/planFirst.ts). Go routes whenever the plan changes;
  // Plan routes on its Route button, except a plan opened from a link, a kept route or a file (it opens drawn),
  // the stations or a transit option chosen for the route shown (they re-plan it at once), and Undo back to the
  // drawn plan after a Clear (it is drawn again).
  const planFirst = mode === "plan" && !riding;
  const [routeAsk, setRouteAsk] = useState(initialPlan.points.length >= 2 ? 1 : 0);
  const routedAsk = useRef(0);
  const asked = useRef<{ points: LonLat[]; preset: PresetId; routeKey: string; planKey: string; confirmedKm: number | null } | null>(null);
  const drawnRef = useRef<Drawn | null>(null);
  const [drawn, setDrawn] = useState<Drawn | null>(null);
  const [changeDetails, setChangeDetails] = useState<string[]>([]);
  const [ghost, setGhost] = useState<LonLat[] | null>(null);
  const [changeLine, setChangeLine] = useState<string | null>(null);
  /** Another plan opened (a link, a file): no Reset back to the last one, and no summary against it. */
  const forgetDrawn = () => {
    drawnRef.current = null;
    setDrawn(null);
    setGhost(null);
    setChangeLine(null);
    setChangeDetails([]);
  };

  // Route when the plan changes (Go) or the Route button is pressed (Plan).
  useEffect(() => {
    if (points.length < 2) {
      scheduler.current?.clear();
      setRoute(null);
      setStatus({ kind: "idle" });
      // The next route opens compact again (the correctness review's N1).
      setEditPoints(false);
      asked.current = null;
      return;
    }
    const pressed = routeAsk !== routedAsk.current;
    routedAsk.current = routeAsk;
    const last = asked.current;
    const samePlan = last !== null && last.points === points && last.preset === preset && last.routeKey === routeKey;
    if (!pressed && samePlan && last.planKey === planKey && last.confirmedKm === confirmedKm) return;
    // In Plan every change waits for Route, the stations and a transit option too (they are part of planKey).
    const backToDrawn = answer === null && drawnRef.current !== null && !planChanged(drawnRef.current, points, preset, planKey);
    if (planFirst && !pressed && !backToDrawn) return;
    asked.current = { points, preset, routeKey, planKey, confirmedKm };
    scheduler.current?.request({
      points,
      preset,
      dials: planDials,
      confirmLong: sendsConfirmation(points, confirmedKm),
      ride: rideRef.current,
      dialsKey: planKey,
      pressed: pressed && planFirst,
      pins: stationPins,
      transitPick,
      // Go shows the first good route at once and swaps in the full plan before Start (v0.7.0, "Faster routing");
      // Plan keeps the full search on its Route button.
      quick: mode === "go" && !riding,
    }, { now: goPickedNow.current && mode === "go" });
    goPickedNow.current = false;
  }, [points, preset, planDials, confirmedKm, routeAsk, planFirst]);

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

  // After Remove, the focus goes to the next Remove button, or (none left) to the search; after Clear
  // (index -1), to the search, Go's Where to? in Go, once the cleared route no longer hides it.
  useEffect(() => {
    const index = focusAfterRemove.current;
    if (index === null) return;
    const target = index < 0 ? null : removeRefs.current[Math.min(index, points.length - 1)];
    const search = pointsSearchRef.current ?? panelRef.current?.querySelector(".go-search") ?? null;
    const input = search?.querySelector<HTMLElement>("input");
    if (!target && index < 0 && route && input?.closest("[hidden]")) return;
    focusAfterRemove.current = null;
    (target ?? input)?.focus();
  }, [points, route]);

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
  const saveMyGoNow = (next: MyGo, speak = true, onSaved?: (saved: boolean) => void) => {
    setMyGo(next);
    if (meRef.current.signed_in) {
      if (!accountMyGoRead.current) {
        onSaved?.(false);
        return;
      }
      saveAccountCopy(next);
      void saveMyGo(window.location.origin, next).then((saved) => {
        if (saved) setMyGo(saved);
        if (speak) sayMyGo(saved ? MY_GO_SAVED : MY_GO_NOT_SAVED);
        onSaved?.(saved !== null);
      });
    } else {
      saveDeviceMyGo(next);
      if (speak) sayMyGo(MY_GO_SAVED_DEVICE);
      onSaved?.(true);
    }
  };
  // Home alone (lib/homeSet.ts): from the Home sheet's search, the map, or Settings. Said at once, politely, through
  // the page's region ("Home set to <name>."); the focus stays where it is. Signed in, a save the account refused
  // is said after it; signed out, it is kept on this device.
  const setHome = (home: Home | null) => {
    announce(home ? homeSetSaid(home) : HOME_CLEARED);
    saveMyGoNow({ ...myGoRef.current, home }, false, (saved) => {
      if (!saved) announce(MY_GO_NOT_SAVED);
    });
  };
  // Saved settings (v0.7.0): the account's win on sign-in; an empty account takes this device's.
  const lastSettings = useRef<SettingsDoc | null>(null);
  const [settingsSynced, setSettingsSynced] = useState(false);
  const [homeAsk, setHomeAsk] = useState<HomeOffer | null>(null);
  const syncSettingsOnSignIn = async (origin: string, live: () => boolean) => {
    const account = await fetchSettings(origin);
    if (!live() || account === undefined) return;
    const device = deviceSettings({ preset: rideRef.current.preset, dials: rideRef.current.dials });
    const step = onSignIn(account, device);
    if (step.kind === "push-device") {
      lastSettings.current = device;
      void saveSettings(origin, device);
    } else {
      applyToDevice(step.doc);
      lastSettings.current = step.doc;
      setWaterPrefsState(readWaterPrefs());
      setClimbsOnState(readClimbsOn());
      setClimbsFromState(readClimbsFrom());
      if (step.doc.topo !== undefined) setTopoLines(step.doc.topo, { remember: false });
      const plan = planFromSetting(step.doc.plan);
      if (plan && !PLAN_LINK && !rideTouched.current && pointsRef.current.length === 0 && modeRef.current !== "go") {
        setPreset(plan.preset);
        setDials(plan.dials);
      }
      if (!sameSettings(step.doc, device)) announce(ACCOUNT_SETTINGS_USED);
    }
    setSettingsSynced(true);
  };
  useEffect(() => {
    let live = true;
    const origin = window.location.origin;
    void fetchMe(origin).then(async (found) => {
      if (!live) return;
      setMe(found);
      // A tab left in Review by an account that may no longer review opens in Plan; this device's last Review
      // comes back once the account is known to be one that may (lib/appMode.ts reopenReview).
      const reviews = found.can_change_lts;
      if (!reviews && modeRef.current === "review") {
        setModeState("plan");
        writeTabMode("plan");
      } else if (reopenReview({ lastReview: readLastReview(), canReview: reviews, by: OPENING.by, switched: modeSwitched.current, mode: modeRef.current })) {
        modeSwitched.current = true;
        setModeState("review");
        leaveGo();
      }
      if (!found.signed_in) {
        // Signed out (or the account's copy is from before a sign-out): this device's My Go.
        if (START_MY_GO.account) {
          saveAccountCopy(null);
          setMyGo(readStartMyGo().myGo);
        }
        return;
      }
      void syncSettingsOnSignIn(origin, () => live);
      const account = await fetchMyGo(origin);
      if (!live || !account) return;
      accountMyGoRead.current = true;
      setMyGo(account);
      saveAccountCopy(account);
      // A Home kept on this device while signed out: offered to the account, never merged silently.
      setHomeAsk(homeOffer(deviceHome(), account.home));
      if (laterMyGoApplies(OPENING.by, modeSwitched.current)) {
        const later = openingMode({ tab: null, planLink: false, openIn: account.openIn, wide: !window.matchMedia(NARROW).matches }).mode;
        setModeState((now) => (now === later ? now : later));
        if (later !== "go") leaveGo();
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
  // A notice already said as part of a fuller line (a pressed destination waiting for a start) is not said again.
  const noticeSaidAs = useRef<string | null>(null);
  useEffect(() => {
    const saidAlready = notice !== null && noticeSaidAs.current === notice;
    noticeSaidAs.current = null;
    if (!saidAlready && noticeSaidElsewhere(notice, plannerShownNow.current)) announce(notice as string);
  }, [notice, announce]);
  // More direct and Calmer, said once when they come for the route shown ("2 other routes: more direct, calmer."), through
  // the app's polite region; not again as the rider moves among the routes, nor for the same options re-read.
  const neighboursSaidFor = useRef<object | null>(null);
  useEffect(() => {
    if (kept.length === 0 || neighboursSaidFor.current === neighbours) return;
    neighboursSaidFor.current = neighbours;
    announce(neighboursSaid(kept, displacedBy(answer, picked, kept)));
  }, [kept, neighbours, announce, answer, picked]);
  // Shows `shown` and says `said` in its place, in one announcement.
  const setNoticeSaying = (shown: string, said: string) => {
    noticeSaidAs.current = shown;
    setNotice(shown);
    announce(said);
  };

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

  /**
   * Every edit of the points goes through here, so undo can give the list before it back. A point it adds is drawn
   * to in manual mode, or where it splits a drawn leg (lib/pointKinds.ts afterEdit).
   */
  const commit = useCallback(
    (next: LonLat[], ride?: Ride) => edits.commit(VIA_MARKS.afterEdit(pointsRef.current, next, manualRef.current), ride),
    [edits],
  );

  /** Undo or redo: the list the history gives back, which is not itself an edit. */
  const travel = useCallback(
    (direction: "undo" | "redo") => {
      const active = document.activeElement;
      historyPress.current = active instanceof HTMLElement && active.dataset.history ? { direction, button: active, row: active.parentElement } : null;
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
  // Undo or Redo pressed for the last step it had goes (Redo, the map's buttons) or is disabled (Undo):
  // the focus goes to the other one, or to the Points heading with neither (review a11y-2).
  const historyPress = useRef<{ direction: "undo" | "redo"; button: HTMLElement; row: Element | null } | null>(null);
  useEffect(() => {
    const press = historyPress.current;
    historyPress.current = null;
    if (!press) return;
    const usable = (element: Element): boolean => element instanceof HTMLElement && element.isConnected && !(element as HTMLButtonElement).disabled;
    const other = press.row?.querySelector<HTMLElement>(`[data-history="${press.direction === "undo" ? "redo" : "undo"}"]`) ?? null;
    const where = afterHistoryStep<Element>({ button: press.button, other }, document.activeElement, document.body, usable);
    if (where === "stay") return;
    (where === "other" ? other : pointsHeadingRef.current)?.focus();
    // A phone's hidden sheet hides the heading too: the map, where the buttons were.
    if (document.activeElement === document.body) mapRef.current?.getCanvas().focus();
  }, [can]);
  // A press whose step changed neither button (can unchanged) is not kept for a later change to act on.
  useEffect(() => {
    historyPress.current = null;
  });

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
    // The Home sheet's "Pick on the map" (lib/homeSet.ts): this tap is Home, not a point or a destination.
    if (homePickRef.current) {
      setHomePick(false);
      void setHomeAtRef.current(point);
      return;
    }
    // In Go, the spot pressed is the destination, in place of any before it, routed as a picked one is.
    if (goTapSetsEnd(modeRef.current)) {
      void goToRef.current(point, goPlaceName(namer.name(point)?.name, point), true);
      return;
    }
    if (pointsRef.current.length >= MAX_POINTS) {
      setNotice(maxPointsNotice());
      return;
    }
    setNotice(null);
    const current = pointsRef.current;
    // Manual mode: the tap is the new end, drawn to from the last one (commit marks it), so a path is traced tap by
    // tap. An end drawn to before goes on as a via point; an end that was a chosen place stays a stop.
    const next =
      manualRef.current && current.length >= 1
        ? [...current.slice(0, -1), ...current.slice(-1).map((end) => (current.length > 1 && VIA_MARKS.isDrawn(end) ? VIA_MARKS.withKind(end, "via") : end)), point]
        : addPoint(current, point, loopVias);
    // A point tapped in between the ends is a via point (v0.7.0, "Via points vs stops"); its menu makes it a stop.
    const index = next.indexOf(point);
    if (isMiddle(index, next.length, loopVias) && index < next.length - 1) VIA_MARKS.via(point);
    commit(next);
    const said = kindSaid(next, index, VIA_MARKS.isVia, loopVias, "added");
    announce(index > 0 && VIA_MARKS.isDrawn(point) ? `${said} ${DRAWN_SAID}` : said);
  }, [commit, announce, loopVias]); // namer is the page's one, kept for the page (usePlaceNames)

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
    // A Go destination that waited on this look-up (pressed in Go while it ran): the answer is that destination's.
    if (goWaitingRef.current()) {
      goSettleRef.current(result);
      return;
    }
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
    // A dragged point keeps its kind (lib/pointKinds.ts).
    commit(movePoint(pointsRef.current, index, VIA_MARKS.moved(before, point)));
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
      // The line dragged is a via point (v0.7.0): it shapes the route, with no stop there.
      const next = insertIntoRide(routed, leg, VIA_MARKS.via(point), loopVias);
      if (next === null) {
        setNotice(`A route can have at most ${MAX_POINTS} points.`);
        return;
      }
      setNotice(null);
      commit(next);
      announce(insertedSaid(leg, next.length, loopVias, VIA_POINT_NAME));
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
  // The route shown (set where Find food works it out, below): with one, the list is by least detour off it.
  const nearestRoute = useRef<RouteForDetour | null>(null);
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
          // A Go destination that waited on this look-up is settled by its answer too.
          if (goWaitingRef.current()) goSettleRef.current(result);
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
        closedReason: (station) => closedReason(station, { metro: true, marc: false }, railClosures),
        request: (from, places) => requestNearest(from, places, ride.preset, ride.dials),
        route: nearestRoute.current,
      });
      if (outcome.fix) {
        setHere(outcome.fix);
        // Go's start, the location before a destination, moves with the new look-up (freshHere, below).
        if (goStartRef.current.kind === "here" && pointsRef.current.length === 0 && insideCoverage(outcome.fix.point)) setGoStart(goHereStart(outcome.fix.point));
      }
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
  // Go centres the rider's location in the open part of the map, between Go's bar and the panel (lib/visibleCentre.ts).
  // The panel's height, for what sits on the map just above Go's sheet (the attribution, the Beta chip; styles.css
  // --go-sheet-h): the sheet is as tall as its content, so a fixed share of the screen left them floating.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    // A hidden panel (a ride) keeps the last height, so the map's corners stay where they were.
    const observer = new ResizeObserver(() => {
      const height = Math.round(panel.getBoundingClientRect().height);
      if (height > 0) root.style.setProperty("--go-sheet-h", `${height}px`);
    });
    observer.observe(panel);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--go-sheet-h");
    };
  }, []);
  // A location found before the map is ready is centred once it is (onReady).
  const centreWhenReady = useRef<LonLat | null>(null);
  const flyToInView = (point: LonLat, zoom: number) => {
    const map = mapRef.current;
    centreWhenReady.current = map ? null : point;
    if (!map) return;
    const bar = document.querySelector(".go-top")?.getBoundingClientRect().bottom ?? 0;
    const panel = panelRef.current?.getBoundingClientRect() ?? null;
    const offset = visibleCentreOffset(map.getContainer().getBoundingClientRect(), bar, panel, window.matchMedia(NARROW).matches);
    map.flyTo({ center: point, zoom: Math.max(map.getZoom(), zoom), offset });
  };
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
  // link holds no position until a destination is picked). A start from the link, or one typed first (or
  // placed in Plan), wins; a press on the map in Go is the destination, never the start. Denied, unavailable or timed out: the start stays empty and that is said politely.
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
      // It settles a destination that waited on it itself, below.
      goAwaiting.current = false;
      const pending = goPending.current;
      if (!result.ok || !insideCoverage(result.fix.point)) {
        setGoStart({ kind: "none" });
        if (pointsRef.current.length === 0) {
          if (pending?.pressed) setNoticeSaying(goDestinationNeedsStart(pending.name), goPressNeedsStartSaid(pending.name));
          else setNotice(pending ? goDestinationNeedsStart(pending.name) : GO_START_UNAVAILABLE);
        }
        return;
      }
      setHere(result.fix);
      setGoStart(goHereStart(result.fix.point));
      if (pointsRef.current.length > 0) return;
      // A destination picked while the location was being found: routed now, not dropped.
      if (pending) {
        clearGoPending();
        routeGoRef.current(result.fix.point, true, pending.dest, pending.name, !!pending.pressed && !pending.said, pending.vias);
      } else {
        // Go opens on the rider (the owner, 2026-10-17): the location, centred above the sheet.
        flyToInView(result.fix.point, 15);
        announce(GO_START_SAID);
      }
    })();
    // Once per page, when Go is first shown (locateForGo reads only refs and stable setters).
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps
  // Go's start found long ago (the page or the phone app left open since an earlier ride; the owner, 2026-10-19) is
  // looked up again (Go's own look-up, locateForGo), without moving the map, when the page comes back into view, so the first destination picked routes from where the
  // rider is now. A pick while this runs waits on it as on any look-up (settleGoWaiting); a pick with no fresh start
  // looks it up itself (goPickAction).
  useEffect(() => {
    const refresh = async () => {
      if (document.visibilityState !== "visible" || modeRef.current !== "go" || pointsRef.current.length > 0) return;
      if (!goStartStale(goStartRef.current)) return;
      const result = await locateForGo();
      if (result === null) return;
      if (goWaitingRef.current()) {
        goSettleRef.current(result);
        return;
      }
      if (!result.ok || !insideCoverage(result.fix.point)) return;
      if (goStartRef.current.kind === "here" && pointsRef.current.length === 0) {
        setHere(result.fix);
        setGoStart(goHereStart(result.fix.point));
      }
    };
    const onVisible = () => void refresh();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
    // locateForGo reads only refs and stable setters, as the opening look-up's does.
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
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
      clearGoPending();
      routeGo(point, false, pending.dest, pending.name, false, pending.vias);
      return;
    }
    commit([point]);
    announce(`Start: ${found.name}.`);
  };
  // A Go route from `start` to `dest` (through `vias`: a climb's bottom), in one edit, with a loop the rider had
  // on turned off (to a place and no further). `pressed`: the destination is a spot pressed on the map, said as
  // "Destination set" (an essential).
  const routeGo = (start: LonLat, located: boolean, dest: LonLat, name: string, pressed = false, vias: LonLat[] = []) => {
    const ride = rideRef.current;
    setNotice(null);
    goPickedNow.current = true;
    commit([start, ...vias, dest], ride.dials.loop ? { ...ride, dials: { ...ride.dials, loop: false } } : undefined);
    if (located) setFromHere((prior) => [...prior, start]);
    if (pressed) announce(goTapRoutedSaid(name, located, saysExtra(announceLevelNow.current)));
    else announceExtra(`Planning a route to ${name} from ${located ? "your location" : "your start"}.`);
    if (goSheetNow.current === "peek") setGoSheet("half");
    mapRef.current?.flyTo({ center: dest, zoom: Math.max(mapRef.current.getZoom(), 13) });
  };
  // The opening look-up answers after later renders: it routes through the current one.
  const routeGoRef = useRef(routeGo);
  routeGoRef.current = routeGo;
  const goTo = async (dest: LonLat, name: string, pressed = false, vias: LonLat[] = []) => {
    cancelLocateNotice();
    setNotice(null);
    if (!insideCoverage(dest)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    // The start Go already has: the plan's first point (typed, from the link or placed in Plan), else the location
    // found when Go opened. While the location is still being found, the destination waits for it.
    const action = goPickAction(pointsRef.current, goStartRef.current);
    if (action.kind === "route") {
      clearGoPending();
      routeGo(action.point, action.located, dest, name, pressed, vias);
      return;
    }
    // A pressed destination with no start yet: kept for the start as a picked one is, and said set together with
    // what it waits for, in one announcement (said apart, the second replaced the first a moment later).
    goPending.current = { dest, name, vias, pressed, said: pressed && action.kind === "wait" };
    if (action.kind === "wait") {
      if (pressed) setNoticeSaying(goDestinationLocating(name), goPressLocatingSaid(name));
      else setNotice(goDestinationLocating(name));
      return;
    }
    // No location yet: one more look-up (the rider may have allowed it since); failing that the destination is
    // kept and the start box asks for a start. The destination is never made the start.
    setGoStart({ kind: "locating" });
    // A pressed destination is said, with what it waits for, once the look-up has taken GO_PRESS_LOCATING_SAY_MS
    // (a timeout can take up to a minute); a quick answer (a denial) is said alone, so nothing is replaced at once.
    const mine = goPending.current;
    const sayLocating = () => {
      if (!mine || goPending.current !== mine || mine.said) return;
      mine.said = true;
      setNoticeSaying(goDestinationLocating(name), goPressLocatingSaid(name));
    };
    const slow = pressed ? window.setTimeout(sayLocating, GO_PRESS_LOCATING_SAY_MS) : undefined;
    const result = await locateForGo();
    window.clearTimeout(slow);
    if (result === null) {
      // Another look-up is under way: its answer settles the destination waiting (settleGoWaiting), whichever asked
      // for it (Go's opening look-up, an earlier destination's, Locate's, Use my location's or the nearest finder's).
      // A press is said now, as it is while Go's opening look-up runs.
      if (pressed) sayLocating();
      goAwaiting.current = true;
      return;
    }
    settleGoWaiting(result);
  };
  // A Go look-up's answer for the destination waiting on it (the latest one picked or pressed): found, Go's start
  // is the location and the destination is routed from it; not, the start box asks for a start, shown and said.
  // Either way only while the plan has no start (one typed meanwhile is routed from, as Go's opening look-up does).
  // `reason`: Locate's answer keeps its own reason in the line ("Your location is blocked…, or type a start.").
  const settleGoWaiting = (result: LocateResult, reason = false) => {
    goAwaiting.current = false;
    const pending = goPending.current;
    if (!result.ok || !insideCoverage(result.fix.point)) {
      setGoStart({ kind: "none" });
      if (pending && pointsRef.current.length === 0) {
        const why = reason && !result.ok ? result.reason : null;
        const shown = why ? goDestinationNeedsStartBecause(pending.name, why) : goDestinationNeedsStart(pending.name);
        if (pending.pressed) setNoticeSaying(shown, why ? goPressNeedsStartBecause(pending.name, why) : goPressNeedsStartSaid(pending.name));
        else setNotice(shown);
      }
      return;
    }
    setHere(result.fix);
    setGoStart(goHereStart(result.fix.point));
    clearGoPending();
    if (pending && pointsRef.current.length === 0) routeGo(result.fix.point, true, pending.dest, pending.name, !!pending.pressed && !pending.said, pending.vias);
  };
  // Whether a Go destination found the gate busy and still waits on the look-up under way (goAwaiting, in Go, with a
  // destination waiting): then its answer is settleGoWaiting's, whoever asked for it.
  const goWaiting = () => goAwaiting.current && goPending.current !== null && modeRef.current === "go";
  // For Use my location's callback and the nearest finder, made before these (they read the current ones).
  const goWaitingRef = useRef(goWaiting);
  goWaitingRef.current = goWaiting;
  const goSettleRef = useRef(settleGoWaiting);
  goSettleRef.current = settleGoWaiting;
  // A map press (place, a callback kept across renders) goes through the current goTo.
  const goToRef = useRef(goTo);
  goToRef.current = goTo;
  const goToPlace = (found: Place) => {
    const point = placeFromSearch(found, (p, name, label) => namer.remember(p, name, label), stationEntranceForPlace);
    if (point === null) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    void goTo(point, found.name);
  };
  // Go's early start (v0.7.0, "Faster routing" step 4; lib/progressive.ts): the route to a place the rider is looking
  // at (the top search result, Home when Go opens), asked for before the tap exactly as the tap will ask for it: from
  // Go's start, no stops, no loop, the dials as they are, the first route. Not for Bikeshare or transit (live
  // stations), nor past GO_EARLY_MAX_KM of straight line; never during a ride.
  const goEarly = (dest: LonLat) => {
    if (modeRef.current !== "go" || shownNow.current.riding || !insideCoverage(dest)) return;
    const action = goPickAction(pointsRef.current, goStartRef.current);
    const ridePreset = rideRef.current.preset;
    if (action.kind !== "route" || twoPointsOnly(ridePreset)) return;
    const ends: LonLat[] = [action.point, dest];
    if (spanKm(ends) > GO_EARLY_MAX_KM) return;
    const { closureBypass: _bypass, ...kept } = planDialsNow.current;
    const asked = { dials: { ...kept, loop: false }, quick: true };
    earlyStart.current?.start(routeRequestBody(ends, ridePreset, asked), () => requestRoute(ends, ridePreset, asked));
  };
  const goEarlyToPlace = (found: Place) => {
    const point = placeFromSearch(found, () => undefined, stationEntranceForPlace);
    if (point) goEarly(point);
  };
  // Go's "Add a stop" (v0.7.0, "Keep adding stops by search"; also the nearest and Sights sheets): with a route, a place is a stop where it adds the
  // least distance, routed at once as any Go edit is; one edit, so Undo removes it. Without a route it is the
  // destination, as Where to? makes it.
  const goAddStopAt = (point: LonLat, name: string) => {
    const current = pointsRef.current;
    const ride = rideRef.current;
    if (current.length < 2 || twoPointsOnly(ride.preset)) {
      void goTo(point, name);
      return;
    }
    if (current.length >= MAX_POINTS) {
      setNotice(maxPointsNotice());
      return;
    }
    const loop = loopStops(ride.preset, ride.dials.loop);
    const added = addStopWhereShortest(current, point, loop);
    setNotice(null);
    commit(added.points);
    announce(stopAddedSaid(added.points, added.index, VIA_MARKS.isVia, loop, name));
  };
  const goAddStop = (found: Place) => {
    const point = placeFromSearch(found, (p, name, label) => namer.remember(p, name, label), stationEntranceForPlace);
    if (point === null) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    goAddStopAt(point, found.name);
  };
  // Go's Home chip: with a Home (the account's, or this device's when signed out), ride there. Without one the chip
  // opens Go's Home sheet (app/Go.tsx HomeSetter) in place, so it never comes here.
  const goHome = () => {
    const home = myGoRef.current.home;
    if (!home) return;
    namer.remember(home.point, home.label || "Home", home.label || "Home");
    void goTo(home.point, home.label || "Home");
  };
  // Home at a spot on the map (the road panel's Set as Home, or Pick on the map then a tap): named by a name the page
  // has, else the reverse look-up (through the page's one geocoding gate), else its coordinates.
  const setHomeAt = async (point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    const known = namer.name(point)?.name;
    const reverse = known ? null : await geoGate.run(() => fetchPlaces(reverseUrl(point))).catch(() => null);
    setHome(homeAtSpot(point, known, reverse));
  };
  const setHomeAtRef = useRef(setHomeAt);
  setHomeAtRef.current = setHomeAt;
  const pickHome = () => {
    const on = !homePickRef.current;
    setHomePick(on);
    if (on && goSheet === "full") setGoSheet("half");
    announce(on ? HOME_PICK_LINE : HOME_PICK_CANCELLED);
  };
  // Picking Home on the map is Go's, and ends when Go does (or a ride starts).
  useEffect(() => {
    if (mode !== "go" || riding) setHomePick(false);
  }, [mode, riding]);
  // Go open with Home set and the rider's location found, and no route yet: the route Home is asked for early, so
  // the Home chip shows it finished (v0.7.0, "Faster routing" step 4). Signed in or out: Home works either way.
  const homeEarly = myGo.home !== null ? myGo.home.point : null;
  useEffect(() => {
    if (mode === "go" && !riding && points.length === 0 && goStart.kind === "here" && homeEarly) goEarly(homeEarly);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- asked once each time these change, not each render
  }, [mode, riding, points.length, goStart.kind, homeEarly?.[0], homeEarly?.[1]]);
  // Go's Locate (the top bar): the map goes to the rider, and nothing is added to the plan.
  const goLocate = async () => {
    const result = await locateForGo();
    if (result === null) return;
    // A destination pressed or picked while Locate looked: its answer is that destination's (routed, or the start
    // box asks for a start), not Locate's own notice or camera move.
    if (goWaiting()) {
      settleGoWaiting(result, true);
      return;
    }
    if (!result.ok) {
      setNotice(LOCATE_MESSAGES[result.reason]);
      return;
    }
    setHere(result.fix);
    if (!insideCoverage(result.fix.point)) setNotice(LOCATION_OUTSIDE);
    else announceExtra("The map is at your location.");
    flyToInView(result.fix.point, 15);
  };
  // A ride type chip (Go's quick three, or the Ride sheet's): as the ride type dialog picks one.
  const pickRide = (id: PresetId) => {
    if (id === preset) return;
    choosePreset(id, mtbChosen(preset, id, chooseRideType(id, carries(id) ? "cargo" : null, dials)));
    announceExtra(`${presetSaid(id)}.`);
  };
  // Search prefers places near the rider: the location the app already has (`here`, rounded to about 1 km)
  // while it is in the map's view, else the map's centre.
  const searchBias = (): LonLat | undefined => {
    const map = mapRef.current;
    const centre = map?.getCenter();
    const b = map?.getBounds();
    const view: ViewBounds | undefined = b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : undefined;
    return searchBiasPoint(here?.point, centre ? [centre.lng, centre.lat] : undefined, view);
  };

  const removeAt = (index: number) => {
    focusAfterRemove.current = index;
    commit(pointsRef.current.filter((_, i) => i !== index));
  };
  // A stop dragged to another stop's place in the points list (lib/pointMover.ts; Stephen 2026-10-18, beside Best
  // order): `from` and `to` are the two stops' points. Only stops move, as Best order moves them: the start and the end
  // stay, and each via point goes with the stop it leads to. One edit, so Undo puts it back; the same pairs, so each
  // keeps its kind, its name and whether it is the location. A drag is said ("Union Market is now Stop 1."); after a
  // key the focus is on the moved stop's grip, whose new name says it.
  const reorderPoint = (from: number, to: number, by: "drag" | "key") => {
    const current = pointsRef.current;
    const split = stopsOnly(current, VIA_MARKS.isVia, loopVias);
    const a = split.points.indexOf(current[from]);
    const b = split.points.indexOf(current[to]);
    if (a < 1 || b < 1 || a === b) return;
    const next = withVias(reorder(split.points.map((_, i) => i), a, b), split);
    commit(next);
    if (by !== "drag") return;
    const moved = next.indexOf(current[from]);
    const role = namePoints(next, VIA_MARKS.isVia, loopVias)[moved]?.name ?? "";
    const name = fromHere.includes(current[from]) ? YOUR_LOCATION : namer.name(current[from])?.name;
    announce(name ? `${name} is now ${role}.` : `Moved to ${role}.`);
  };
  // From the map: the focus stays where it was (on a phone the sheet may be
  // hidden), and the removal is said instead.
  const removeFromMap = useCallback(
    (index: number) => {
      const current = pointsRef.current;
      if (index < 0 || index >= current.length) return;
      const said = kindSaid(current, index, VIA_MARKS.isVia, loopVias, "removed");
      commit(current.filter((_, i) => i !== index));
      announce(said);
    },
    [commit, announce, loopVias],
  );
  // The point menu's "Make this a stop / a via point" (v0.7.0): a new pair of the other kind in its place, one
  // edit, so Undo switches it back.
  const switchKind = useCallback(
    (index: number) => {
      const current = pointsRef.current;
      const point = current[index];
      if (!point || namePoints(current, VIA_MARKS.isVia, loopVias)[index]?.role === "start") return;
      const to = VIA_MARKS.isVia(point) ? "stop" : "via";
      commit(current.map((p, i) => (i === index ? VIA_MARKS.withKind(p, to) : p)));
      announce(kindSwitchedSaid(to, namer.name(point)?.name));
    },
    [commit, announce, loopVias, namer],
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
    const reversed = reversedPoints(current, loopVias);
    // A leg drawn in manual mode stays drawn, now ridden the other way (a loop's drawn legs are not used).
    const drawn = drawnLegs(current);
    const end = current.length - 2;
    commit(drawn.length && reversed[0] !== current[0] ? VIA_MARKS.withLegs(reversed, drawn.map((leg) => end - leg)) : reversed);
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
  // Best order moves stops only (v0.7.0): via points go with the stop they lead to.
  const orderShown = !isMassRide(preset) && stopsThatMove(stopsOnly(points, VIA_MARKS.isVia, loopVias).points, loopVias) >= 2;
  // Go with a route (v0.7.0, "Keep adding stops by search"): "Add a stop" and Best order in the route sheet, and a
  // chip's place a stop; never during a ride, nor on a ride type of a start and an end only.
  const goStops = mode === "go" && !riding && points.length >= 2 && !twoPointsOnly(preset) && !isMassRide(preset);
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
    const stops = stopsOnly(current, VIA_MARKS.isVia, loop);
    if (isMassRide(ride.preset) || stopsThatMove(stops.points, loop) < 2) return;
    orderingRef.current = true;
    setOrdering(true);
    announce(FINDING_ORDER_SAID);
    const result = await requestStopOrder(stops.points, ride.preset, ride.dials);
    orderingRef.current = false;
    setOrdering(false);
    const now = rideRef.current;
    const applied = applyAnswer(
      { points: current, preset: ride.preset, dials: ride.dials, loop, stops: stops.points.length < current.length ? stops : undefined },
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
    // Cleared, the next save is a new saved route.
    openSavedRoute.current = null;
    commit([], ride.imported ? { ...ride, imported: null } : undefined);
    // Said, and the focus to the place search, as every other removal hands it on (review a11y-1).
    announce(CLEARED_SAID);
    focusAfterRemove.current = -1;
    // Not kept past the clear's own renders: a route that does not go would leave it for a later edit.
    window.setTimeout(() => {
      if (focusAfterRemove.current === -1) focusAfterRemove.current = null;
    }, CLEAR_FOCUS_WAIT_MS);
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
    // A file's points are stops (v0.7.0), but for those a RouteMaker file names "Via point" (lib/gpx.ts).
    const opened = plan.points.slice(0, MAX_POINTS);
    VIA_MARKS.markAt(opened, viaPointsNamed(plan.pointNames, opened.length));
    commit(opened, { ...rideAfterImport(plan, rideRef.current), imported: plan });
    // An opened file is a saved route: it opens drawn (v0.7.0), and is not compared with the plan before it.
    forgetDrawn();
    setRouteAsk((n) => n + 1);
  };
  const getMap = useCallback(() => mapRef.current, []);
  // A fitting round for an opened track: part of the same edit as the import
  // (the rider did not make it), so it is not an undo step of its own.
  const refineImported = useCallback((next: LonLat[]) => {
    if (importBase.current) importBase.current = { ...importBase.current, points: next };
    pointsRef.current = next;
    setPoints(next);
  }, []);
  const addAtCentre = () => {
    const map = mapRef.current;
    if (!map) return;
    // Map tools' Add point while the plan is full (aria-disabled, review a11y-7): its reason, said each press.
    if (!goTapSetsEnd(mode) && pointsRef.current.length >= MAX_POINTS) {
      announce(maxPointsNotice());
      return;
    }
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
    scheduler.current?.request({ points, preset, dials: planDials, confirmLong: sendsConfirmation(points, confirmedKm), ride: rideRef.current, dialsKey: planKey, pins: stationPins, transitPick });
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
    scheduler.current?.request({ points, preset, dials: planDials, confirmLong: true, ride: rideRef.current, dialsKey: planKey, pins: stationPins, transitPick });
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
    if (next !== "go") leaveGo();
    announceExtra(modeSaid(next));
    // Review is remembered on this device; Go and Plan are My Go's Open in, as before.
    writeLastReview(next === "review");
    if (next !== "review") saveMyGoNow({ ...myGoRef.current, openIn: next }, false);
  };
  // A place shared to RouteMaker (the Share sheet, or a geo: link on desktop): Go's destination (app/sharedLaunch.ts).
  useSharedLaunch((place) => {
    if (modeRef.current !== "go") changeMode("go");
    goToPlace(place);
  }, setNotice);
  // "Copy link": this page with the plan's fragment from encodePlan, which never holds the weight
  // (OWNER-DECISIONS 313). Cleared first and set again a moment later, so a second press is said again.
  // v0.9.0, "share the exact route": it names the exact line shown too, as Share's does (sharedLinkNow), so a link copied
  // into a group chat opens the identical route; a line that could not be kept is said after the copy.
  const copyLink = async () => {
    const press = ++linkPresses.current;
    setLinkSaid("");
    setLinkSpoken("");
    const note = linkNote;
    const { link, kept } = sharedLinkNow();
    const done = await copyText(link, navigator.clipboard, selectionCopy);
    window.setTimeout(() => {
      if (press === linkPresses.current) setLinkSaid(linkSaidFor(done));
      if (press === linkPresses.current) setLinkSpoken(linkSpokenFor(done, note));
    }, 150);
    // Said once the server answers (or gives up, SHARED_STORE_TIMEOUT_MS), never holding up "Link copied."
    if (!done || !kept || (await kept)) return;
    if (sharedLine.current?.kept === kept) sharedLine.current = null;
    window.setTimeout(() => {
      if (press === linkPresses.current) setLinkSaid(`${linkSaidFor(done)} ${SHARED_INPUTS_ONLY}`);
      if (press === linkPresses.current) setLinkSpoken(SHARED_INPUTS_ONLY);
    }, 150);
  };
  // "Share": Copy link's link, to the phone's share sheet. The location line describes the button,
  // so it is read before the sheet opens. Nothing is said when the sheet opened or the rider closed it;
  // a failure is said, offering Copy link. It shares the said lines with Copy link, so the last press speaks.
  // A press while the sheet is open is skipped. shareLink is called before any await, so the press's user
  // activation still holds. The distance is the route shown, so it is left out while a re-plan is pending
  // (the link carries the current points).
  // v0.7.0, "share the identical route" (lib/sharedRoutes.ts): with the route settled, the link also names the
  // exact line shown, sent to the server as the sheet opens, and the sheet carries the GPX file Download GPX
  // would save where the browser can share files. A route shared again keeps its first id. A line too big to
  // keep, or one that could not be sent, leaves the link with the inputs only, said in one line.
  const sharing = useRef(false);
  // What Share said, in the Route file sheet beside it (RoutePanel.tsx ShareControls); the count makes a line said
  // again heard again.
  const [shareSaid, setShareSaid] = useState({ text: "", count: 0 });
  // Share's own presses: a Copy link press does not swallow what Share has to say.
  const sharePresses = useRef(0);
  const sharedLine = useRef<{ of: unknown; keep: string; id: string; kept: Promise<boolean> } | null>(null);
  // How long the server keeps the shared line, chosen beside Share in Plan (lib/sharedRoutes.ts ShareKeep). A
  // route shared again with another keeping is a new line under a new id.
  const [shareKeep, setShareKeep] = useState<ShareKeep>(SHARE_KEEP_DEFAULT);
  // A link turned off or replaced in My routes: Share makes a new one rather than hand out its id again.
  const forgetSharedLine = () => {
    sharedLine.current = null;
  };
  const shareExact = () => {
    const verbatim = imported?.verbatim;
    if (verbatim && !importEdited) {
      const name = fileName();
      // The route shown for the file, once settled (v0.9.0, "share the exact route"): the link opens that very line,
      // followed by the rules or exactly, not the file planned again. A new line (the other mode) is a new link.
      const settled = fileShown();
      return {
        of: settled ?? verbatim,
        save: gpxSave(name, verbatim.text ?? trackGpx(name, verbatim.track), verbatim.track, points, preset, dials, settled),
        file: verbatimDownload(verbatim, importEdited, imported?.name),
      };
    }
    if (!shown || stale || routedPoints !== points) return null;
    const name = defaultRouteName(fileNamed(routedPoints[0]), routedPoints.length > 1 ? fileNamed(routedPoints[routedPoints.length - 1]) : null);
    return { of: shown, save: planSave(name, shown, routedPoints, preset, dials), file: routeGpxFile(shown, routedPoints, routedLoop, federalRoute) };
  };
  // Share's link: the plan's inputs, and the exact line's id with that line sent (once per line and keeping).
  // Share as image's QR code makes its link here too.
  const sharedLinkNow = () => {
    let link = linkToCopy(window.location, points, preset, dials, viaIndices(points, VIA_MARKS.isVia));
    const exact = shareExact();
    let kept: Promise<boolean> | null = null;
    if (exact) {
      const keep = JSON.stringify(keepFields(shareKeep));
      const before = sharedLine.current?.of === exact.of && sharedLine.current.keep === keep ? sharedLine.current : null;
      const id = before?.id ?? newSharedId();
      const body = before ? null : sharedBody(id, exact.save, shareKeep, previewImageOk(exact.save.line, exact.save.inputs.points, myGo.home, me.signed_in));
      if (before || body) {
        link = withSharedId(link, id);
        kept = before?.kept ?? storeShared(origin, body!.json);
        if (!before) sharedLine.current = { of: exact.of, keep, id, kept };
      } else kept = Promise.resolve(false);
    }
    return { link, kept, exact };
  };
  // Share as image's QR code (lib/shareCard.ts): the link only once its exact line is kept; a line not kept is
  // tried again under a new id next time, as Share does.
  const shareCardLink = async (): Promise<string | null> => {
    const { link, kept } = sharedLinkNow();
    if (!kept) return null;
    if (await kept) return link;
    if (sharedLine.current?.kept === kept) sharedLine.current = null;
    return null;
  };
  // Share ride: the same link marked as a ride (lib/sharedRoutes.ts RIDE_PARAM), opened fixed with location sharing.
  const shareRoute = async (ride = false) => {
    if (!shown || sharing.current) return;
    const press = ++sharePresses.current;
    // A ride only with its exact line, kept with the route shown for it: while the route is still being planned the
    // link would plan again, a route, so it is said rather than shared.
    if (ride && !shareExact()?.save.answer) {
      setShareSaid((before) => ({ text: SHARE_RIDE_WAIT, count: before.count + 1 }));
      return;
    }
    sharing.current = true;
    setShareSaid((before) => ({ text: "", count: before.count }));
    const distanceM = !stale && routedPoints === points ? shown.distance_m : null;
    const now = sharedLinkNow();
    const { kept, exact } = now;
    const link = ride && kept ? asRideLink(now.link) : now.link;
    const file = exact?.file ? gpxShareFile(exact.file.text, exact.file.fileName) : null;
    const content = withGpxFile(navigator, shareContent(link, distanceM, presetSaid(preset)), file);
    const outcome = shareLink(navigator, content);
    let said: string;
    try {
      const done = await outcome;
      said = shareSaidFor(done);
      // The line not kept: the link plans again when opened. Said unless the sheet failed (that line says more),
      // and the next press tries again with a new id.
      if (kept && !(await kept)) {
        if (sharedLine.current?.kept === kept) sharedLine.current = null;
        if (done !== "failed" && done !== "cancelled") said = SHARED_INPUTS_ONLY;
      } else if (ride && kept && done === "shared") {
        // The one who shared a ride has the same location sharing, but leads it: re-routed off it as any ride is (the
        // owner, 2026-10-18: "Maybe make the sharer able to reroute").
        setSharedOpen({ answer: shown, ride: true, own: true });
      }
    } finally {
      sharing.current = false;
    }
    if (!said) return;
    window.setTimeout(() => {
      if (press === sharePresses.current) setShareSaid((before) => ({ text: said, count: before.count + 1 }));
    }, 150);
  };

  // Start ride (plan Q1, Q3): the first ride asks how to say the cues; later rides start at once. The
  // voice is unlocked inside this press (iOS speaks only after a gesture).
  // unlocked: Start's own press has already unlocked the voice (startRideChecked), before its closure check.
  // `rest`: Ride the rest's own route (rideRest, below), ridden in place of the plan's.
  const beginRide = (prefs: RidePrefs, unlocked = false, rest?: { route: RouteResponse; points: LonLat[] }) => {
    const route = rest?.route ?? shown;
    if (!route) return;
    if (!unlocked) startRideGesture(prefs);
    const leg = rideLegOf(route, rest?.points ?? routedPoints, rest ? false : routedLoop);
    // A More direct or Calmer chosen rides at its own traffic setting, so a re-route keeps to it; the plan's dials and
    // the saved default stay the rider's (lib/neighbours.ts rideDials).
    // A route everyone shares stays fixed (the owner, 2026-10-18: "For sharing mass rides and group rides, rerouting
    // defeats the purpose"; "ride is the fixed one ... route is so people can review or do it themselves
    // separately"): a link shared as a ride, opened unchanged; a Mass Ride or Group Ride, unless shared as a route.
    // Its sharer is not held to it ("Maybe make the sharer able to reroute").
    const opened = sharedOpen?.answer === route ? sharedOpen : null;
    const fixed = fixedRide(leg, opened, !!rest);
    setRideStart((before) => ({ route, ...leg, dials: rideDials({ ...planDials, closuresNow: true }, rest ? null : route), fixed, n: (before?.n ?? 0) + 1 }));
    // The installed app keeps the ride's route as the last ride (OWNER-DECISIONS 465a); End ride gives it
    // the map the ride kept. A browser tab keeps nothing unless the rider presses Keep for offline.
    // A Keep for offline still fetching stops: the ride keeps its own corridor, and two walks would share the page's queue.
    keepAbort.current?.abort();
    if (!rest && shown && isStandalone() && routedKey.current) {
      void keepLastRide({ plan: routedKey.current, title: keptTitle(), distanceM: shown.distance_m, answer: shown })
        .then(() => setKeptVersion((v) => v + 1))
        .catch(() => undefined);
    }
    setRideAsk(false);
    setFollow(true);
    setRideView(null);
    setRiding(true);
  };
  // Keep for offline (P3): the plan, its answer and the map along it; the press asks the browser to
  // keep the site's storage (navigator.storage.persist), and what it did is said politely.
  const keptTitle = () => {
    const first = routedPoints[0];
    const last = routedPoints[routedPoints.length - 1];
    return routeTitle(fileNamed(first), fileNamed(last), routedLoop);
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
    const hash = dials.rideSize && plan.preset === preset ? encodePlan(plan.points, plan.preset, { ...plan.dials, rideSize: dials.rideSize }, plan.vias, plan.drawn) : kept.plan;
    if (window.location.hash !== hash) window.location.hash = hash;
    announce(`Opening ${kept.title}.`);
  };
  const startRide = (unlocked = false) => {
    const opener = document.activeElement;
    rideOpener.current = opener instanceof HTMLElement && opener.closest(".start-ride, .description-actions") ? opener : startRideRef.current;
    // Go goes straight to the ride (the owner, 2026-10-11 20:23 UTC: "just ... find a destination and go"):
    // no first-ride question; the cues are Settings > Ride mode's (the defaults until changed there). Plan asks once.
    if (!ridePrefs.chosen && mode !== "go") {
      setRideAsk(true);
      return;
    }
    beginRide(ridePrefs, unlocked);
  };
  // ---- v0.7.0: saved routes, the verbatim GPX and the closure check ----
  const origin = window.location.origin;
  // Signed in, a change to the settings is saved once it settles (one save for a slider dragged).
  useEffect(() => {
    if (!me.signed_in || !settingsSynced) return;
    const timer = window.setTimeout(() => {
      const doc = deviceSettings({ preset, dials });
      if (sameSettings(doc, lastSettings.current)) return;
      lastSettings.current = doc;
      void saveSettings(window.location.origin, doc);
    }, SAVE_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [me.signed_in, settingsSynced, preset, dials, waterPrefs, climbsOn, climbsFrom, showTopoLines]);
  const answerHome = (move: boolean) => {
    const offer = homeAsk;
    if (!offer) return;
    answerHomeOffer(offer.device);
    setHomeAsk(null);
    if (move) saveMyGoNow({ ...myGoRef.current, home: offer.device }, false);
    announce(move ? HOME_MOVED : HOME_KEPT);
  };
  // An opened file not edited since: its points and ride type as the import left them (a fitting round moves
  // the base with it, refineImported).
  const importBase = useRef<{ imported: ImportedPlan; points: LonLat[]; preset: PresetId; unfollowed?: boolean; exact?: boolean } | null>(null);
  if (!imported) importBase.current = null;
  else if (importBase.current?.imported !== imported) importBase.current = { imported, points, preset, exact: imported.exact === true };
  const importEdited = !imported || importBase.current?.points !== points || importBase.current?.preset !== preset;
  // "Follow the file exactly" (Stephen 2026-10-17, "give a manual mode option"): the file planned again, followed as
  // ridden. Off for each file opened; offered while it is not edited (its line is what is followed).
  const setFollowExact = (on: boolean) => {
    if (!importBase.current) return;
    importBase.current = { ...importBase.current, exact: on, unfollowed: false };
    // A saved or shared file's line stands for its own mode only: the other is planned.
    savedShown.current = null;
    setRouteAsk((n) => n + 1);
  };
  const fileName = () => imported?.name || keptTitle();
  // The route on screen for an opened file, once it answers the file's plan as it stands; null while one is planned.
  // A file followed in one mode while the other is planned (the switch just pressed) is not yet the route shown.
  const fileShown = () =>
    shown && !stale && routedPoints === points && (!shown.follows_file || (shown.follows_exactly === true) === (importBase.current?.exact === true && mode === "plan"))
      ? shown
      : null;
  // A saved route's line about today's map (more than 5% apart in distance), with Update route.
  const [savedNote, setSavedNote] = useState<{ key: string; savedM: number; todayM: number } | null>(null);
  const [myRoutesVersion, setMyRoutesVersion] = useState(0);
  // The saved route on screen (opened from My routes, or saved last): in Plan, saved again under its own name it
  // is a new version of that route (lib/savedRoutes.ts versionOf). A new file, a shared route or Clear forget it.
  const openSavedRoute = useRef<OpenSaved | null>(null);
  const saveCurrent = async (name: string): Promise<string> => {
    const verbatim = imported?.verbatim;
    const body =
      verbatim && !importEdited
        ? gpxSave(name, verbatim.text ?? trackGpx(name, verbatim.track), verbatim.track, points, preset, dials, fileShown())
        : shown
          ? planSave(name, shown, routedPoints, preset, dials)
          : null;
    if (!body) return SAVE_FAILED;
    const of = versionOf(openSavedRoute.current, name, mode === "plan");
    const outcome = await saveAsVersion(origin, body, of);
    if (!outcome.ok) return outcome.message || SAVE_FAILED;
    setMyRoutesVersion((v) => v + 1);
    if (mode === "plan") openSavedRoute.current = { id: outcome.route.id, name: outcome.route.name };
    // No `versioned`: a plain save (or the route was gone, and this one is new).
    if (outcome.versioned === undefined) return SAVED_SAID(name);
    return outcome.versioned === false ? UNCHANGED_SAID(outcome.route.name, body.source) : VERSION_SAID(outcome.route.name);
  };
  const saveProps = me.signed_in
    ? {
        defaultName: () =>
          (mode === "plan" ? openSavedRoute.current?.name : undefined) ??
          defaultRouteName(fileNamed(routedPoints[0]), routedPoints.length > 1 ? fileNamed(routedPoints[routedPoints.length - 1]) : null),
        onSave: saveCurrent,
      }
    : null;

  // The closure check (v0.7.0, "closure warning first", and its correction): a route opened, Start ride, and a
  // download are checked against the closures in force now; any hit asks in the major dialog.
  const [closureAsk, setClosureAsk] = useState<ClosureAsk | null>(null);
  const closurePending = useRef<{ line: number[][]; index: number[]; closures: Closure[]; gpx: boolean; nowOnly: boolean; proceed: () => void; afterGpx?: (track: number[][]) => void } | null>(null);
  // A line the rider chose to ride anyway is not asked about again (on Start ride, say).
  const closureLetGo = useRef<string | null>(null);
  const lineKey = (line: readonly (readonly number[])[]) => `${line.length}:${line[0]?.join(",")}:${line[line.length - 1]?.join(",")}`;
  // A press's check under way (Start ride, a download, a save): another press waits for it, ignored (v0.7.0 end
  // review). The check gives up after CHECK_TIMEOUT_MS and the press goes ahead unchecked.
  const closureChecking = useRef(false);
  const checkThen = async (why: CheckFor, line: readonly (readonly number[])[], gpx: boolean, proceed: () => void, afterGpx?: (track: number[][]) => void, onAsk?: () => void) => {
    if (line.length < 2 || closureLetGo.current === lineKey(line)) {
      proceed();
      return;
    }
    const pressed = why !== "open";
    if (pressed && closureChecking.current) return;
    if (pressed) closureChecking.current = true;
    // At the plan's ride time (its When), with the closures it routes through anyway (v0.7.0).
    // Go, and Start ride from either view, check only the closures known to be on (v0.9.1, lib/dials.ts closuresNow).
    const nowOnly = !!planDials.closuresNow || why === "ride";
    const found = await checkClosures(origin, line, fetch, { when: planDials.when, bypass: planDials.closureBypass, nowOnly }).finally(() => {
      if (pressed) closureChecking.current = false;
    });
    if (!found || found.closures.length === 0) {
      proceed();
      return;
    }
    onAsk?.();
    closurePending.current = { line: line.map((v) => [...v]), index: found.index, closures: found.closures, gpx, nowOnly, proceed, afterGpx };
    setClosureAsk({ why, closures: found.closures, unchecked: found.unchecked, notices: found.notices });
  };
  const closureAnyway = () => {
    const pending = closurePending.current;
    closurePending.current = null;
    setClosureAsk(null);
    if (!pending) return;
    closureLetGo.current = lineKey(pending.line);
    pending.proceed();
  };
  const closureCancel = () => {
    closurePending.current = null;
    setClosureAsk(null);
  };
  // Reroute around them: an opened file keeps every point but the closed stretches, each replaced by a way round
  // planned between the points either side; a planned route is planned again with today's map. A ride is not
  // started by it: the rider presses Start ride again.
  const closureReroute = async () => {
    const pending = closurePending.current;
    closurePending.current = null;
    setClosureAsk(null);
    if (!pending) return;
    const file = rideRef.current.imported;
    if (!pending.gpx || !file?.verbatim) {
      savedShown.current = null;
      setSavedNote(null);
      announce("Planning again around the closures.");
      retry();
      return;
    }
    const stretches = closedStretches(pending.line, pending.closures, pending.index);
    announce("Finding a way round the closures.");
    const detours = await Promise.all(
      stretches.map(async ({ before, after }) => {
        const ends: LonLat[] = [
          [pending.line[before][0], pending.line[before][1]],
          [pending.line[after][0], pending.line[after][1]],
        ];
        // The detour's line alone is used: no routes to choose from (review speed-5).
        // The detours go round what the check found: on Start ride, only the closures known to be on.
        const dials = pending.nowOnly ? { ...planDials, closuresNow: true } : planDials;
        const result = await requestRoute(ends, rideRef.current.preset, { dials, routeOnly: true });
        return result.ok ? result.route.geometry.coordinates.map(([lon, lat]) => [lon, lat] as LonLat) : null;
      }),
    );
    const failed = detours.filter((d) => d === null).length;
    announce(reroutedSaid(stretches.length, failed));
    if (failed === stretches.length) return;
    const track = spliceDetours(pending.line, stretches, detours).map((v) => [...v]) as NonNullable<ImportedPlan["verbatim"]>["track"];
    // The plan's own points inside a closed stretch go; the rest stay where the file put them.
    const inside = (p: LonLat) => {
      let best = 0;
      let bestD = Infinity;
      pending.line.forEach((v, i) => {
        const d = (v[0] - p[0]) ** 2 + (v[1] - p[1]) ** 2;
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      });
      return stretches.some((s, k) => detours[k] !== null && best > s.before && best < s.after);
    };
    const kept = pointsRef.current.filter((p, i, all) => i === 0 || i === all.length - 1 || !inside(p));
    // A snapped line (lib/gpxMatch.ts) was of the line before the detours: it goes with it.
    const { matched: _snapped, ...unsnapped } = file;
    const next: ImportedPlan = { ...unsnapped, verbatim: { text: null, track }, reference: track.map(([lon, lat]) => [lon, lat] as LonLat) };
    commit(kept, { ...rideRef.current, imported: next });
    pending.afterGpx?.(track);
  };
  // Download GPX: an opened file not edited since downloads as it came; otherwise the route on screen.
  // `said` (the GPX sheet's) gets the line saying what was saved, once it is, for the sheet's status region.
  const downloadRoute = (said?: (line: string) => void) => {
    const verbatim = imported?.verbatim;
    const file = verbatim ? verbatimDownload(verbatim, importEdited, imported?.name) : null;
    if (file && verbatim) {
      const name = fileName();
      void checkThen(
        "download",
        verbatim.track,
        true,
        () => {
          downloadText(file.text, file.fileName);
          said?.(GPX_SAID_OPENED);
        },
        (track) => {
          downloadText(trackGpx(name, track as NonNullable<ImportedPlan["verbatim"]>["track"]), verbatimFileName(name));
          said?.(GPX_SAID_TRACK);
        },
      );
      return;
    }
    if (!shown) return;
    const route = shown;
    const at = routedPoints;
    void checkThen("download", route.geometry.coordinates, false, () => {
      downloadGpx(route, at, routedLoop, federalRoute);
      said?.(GPX_SAID_ROUTE);
    });
  };
  // Download a FIT or TCX course or a PDF cue sheet (Plan's GPX sheet): the route on screen, checked as Download GPX
  // is; `said` gets the line saying what was made, for the sheet's status region.
  const downloadCourseRoute = (format: FileFormat, profile: DeviceProfileId, said: Said) => {
    if (!shown) return;
    const route = shown;
    const at = routedPoints;
    void checkThen("download", route.geometry.coordinates, false, () => void Promise.resolve(downloadCourse(route, at, format, profile)).then(said));
  };
  // Send to Garmin (Go and Plan's GPX sheet): the route on screen as a FIT course for Garmin Connect, checked as
  // Download GPX is.
  const sendToGarminRoute = (said: Said) => {
    if (!shown) return;
    const route = shown;
    const at = routedPoints;
    void checkThen("download", route.geometry.coordinates, false, () => void sendCourseToGarmin(route, at).then(said));
  };
  // Start ride: the line about to be ridden, checked first ("Ride it anyway" goes on to the ride).
  // The voice is unlocked first, synchronously inside the press (iOS speaks only in a gesture; after the
  // check's await it would be too late). A press that asks the first-ride question unlocks in that dialog.
  const startRideChecked = () => {
    const unlocked = ridePrefs.chosen || mode === "go";
    if (!shown) return startRide(false);
    // A second press while the first one's check runs is ignored (checkThen).
    if (closureChecking.current) return;
    // Unlocked silently inside the press; "Ride started." is said once the ride starts, after the
    // check or "Ride it anyway" (review F1: never before a closure is found).
    if (unlocked) primeRideVoice(ridePrefs);
    // A slow check is said politely.
    const slow = window.setTimeout(() => announce(CHECKING_CLOSURES), CLOSURE_SLOW_MS);
    void checkThen("ride", shown.geometry.coordinates, false, () => {
      window.clearTimeout(slow);
      startRide(false);
    }, undefined, () => {
      window.clearTimeout(slow);
    });
  };
  // Ride the rest (lib/rideTrip.ts): after a transit plan's transit, a ride for its last riding leg, planned
  // as a normal route request from where the rider is (the ride's fix) to the destination, on the leg's
  // ride type; from the trip panel, or with no fix yet, from the leg's own start (no new location look-up).
  // From the ride screen it answers in the ride's own outputs (the returned words; null: the new ride
  // started); from the trip panel, the page's status line says it, and the line is checked for closures
  // first, as Start ride's is.
  // On the ride screen the closure dialog is out of view (the panel is hidden), so closures on the rest's
  // line are said instead, and the route held: a second press within REST_ANYWAY_MS rides it anyway.
  const restHeld = useRef<{ route: RouteResponse; points: LonLat[]; n: number | undefined; at: number } | null>(null);
  const rideRest = async (riderAt: LonLat | null, fromRide: boolean): Promise<string | null> => {
    // The ride pressed from is still on (End ride, or another ride, while the request runs: nothing starts).
    const n = rideNow.current.start?.n;
    const stillOn = () => (fromRide ? ridingNow.current && rideNow.current.start?.n === n : !ridingNow.current);
    const held = restHeld.current;
    restHeld.current = null;
    if (fromRide && held && held.n === n && Date.now() - held.at < REST_ANYWAY_MS) {
      closureLetGo.current = lineKey(held.route.geometry.coordinates);
      beginRide(ridePrefs, false, held);
      return null;
    }
    const trip = fromRide ? rideStart?.trip : shown ? rideTripOf(shown, routedPoints) : null;
    const rest = trip?.rest;
    if (!rest) return null;
    const asked = restRequest(rest, riderAt);
    if (!asked) return NO_FIX_YET;
    const result = await requestRoute(asked.points, asked.preset, { dials: { ...planDials, loop: false, closuresNow: true }, routeOnly: true });
    if (!stillOn()) return null;
    if (!result.ok) return `${result.error.title}. ${result.error.message}`;
    if (!rideableRoute(result.route)) return RIDE_TOO_LONG;
    const line = result.route.geometry.coordinates;
    const go = () => {
      if (stillOn()) beginRide(ridePrefs, false, { route: result.route, points: asked.points });
    };
    if (!fromRide) {
      void checkThen("ride", line, false, go);
      return null;
    }
    const found = closureLetGo.current === lineKey(line) ? null : await checkClosures(origin, line, fetch, { when: planDials.when, bypass: planDials.closureBypass, nowOnly: true });
    if (!stillOn()) return null;
    if (found && found.closures.length > 0) {
      restHeld.current = { route: result.route, points: asked.points, n, at: Date.now() };
      return restClosedSaid(found.closures.map((c) => c.road ?? c.title ?? "a closure"));
    }
    go();
    return null;
  };
  const restPanelBusy = useRef(false);
  const rideRestFromPanel = () => {
    if (restPanelBusy.current) return;
    restPanelBusy.current = true;
    // The voice is unlocked inside the press (iOS), as Start's is; "Ride started." is said when the ride starts.
    primeRideVoice(ridePrefs);
    // The focus comes back to this button when the ride ends, as it does to Start's.
    if (document.activeElement instanceof HTMLElement) rideOpener.current = document.activeElement;
    announce(RIDE_REST_FINDING);
    void rideRest(null, false)
      .then((said) => {
        if (said) announce(said);
      })
      .finally(() => {
        restPanelBusy.current = false;
      });
  };
  // An opened file is checked at once, against its own track.
  const openImportedChecked = (plan: ImportedPlan) => {
    // Another file is not the saved route on screen (a saved file reopened sets it again, openSaved).
    openSavedRoute.current = null;
    openImported(plan);
    if (plan.verbatim) void checkThen("open", plan.verbatim.track, true, () => {});
  };
  // A plan link (or a plan left open) is checked once its first route is on screen.
  const checkFirstAnswer = useRef(PLAN_LINK);
  useEffect(() => {
    if (!checkFirstAnswer.current || !route || riding) return;
    checkFirstAnswer.current = false;
    if (!imported) void checkThen("open", route.geometry.coordinates, false, () => {});
  }, [route]);
  // My routes: open as saved (the line unchanged), or export.
  const openSaved = (saved: Pick<SavedRoute, "name" | "source" | "distance_m" | "line" | "inputs" | "answer" | "gpx"> & { id?: number | string }, said = OPENED_SAID(saved.name)) => {
    showPlanner(true);
    setSharedNote(null);
    setSavedNote(null);
    // A saved route's own id (a shared route's is a string, and is not one of the rider's).
    const own: OpenSaved | null = typeof saved.id === "number" ? { id: saved.id, name: saved.name } : null;
    openSavedRoute.current = own;
    if (saved.source === "gpx" && saved.gpx) {
      // Kept with the route shown for it (v0.9.0, "share the exact route"): the file opens on the plan it was kept
      // with (its points, ride type and sliders) and that very line answers it, in the mode it was followed in.
      const answer = saved.answer ?? null;
      const at = answer ? decodePlan(saved.inputs.hash) : null;
      if (at) VIA_MARKS.markDrawn(at.points, at.drawn);
      const keepShown = () => {
        if (answer && at) savedShown.current = { key: keptPlanKey(at.points, at.preset, at.dials), answer };
      };
      // The link's own plan (the same points) is answered by that line too while the file is read.
      keepShown();
      void readGpx(new Blob([saved.gpx])).then((outcome) => {
        if (!outcome.ok) {
          announce(outcome.message);
          return;
        }
        keepShown();
        openImportedChecked(asKept({ ...outcome.plan, name: saved.name }, at, answer));
        openSavedRoute.current = own;
        announce(said);
      });
      return;
    }
    const plan = decodePlan(saved.inputs.hash);
    // Its drawn legs (Plan's manual mode) on its points, so its key is the plan's as the page will ask it.
    VIA_MARKS.markDrawn(plan.points, plan.drawn);
    const answer = savedAnswer(saved);
    const key = keptPlanKey(plan.points, plan.preset, plan.dials);
    savedShown.current = answer ? { key, answer } : null;
    if (window.location.hash !== saved.inputs.hash) window.location.hash = saved.inputs.hash;
    else retry();
    announce(said);
    void checkThen("open", saved.line, false, () => {});
    // Today's map, asked quietly: more than 5% apart in distance offers Update route; nothing changes without it.
    void requestRoute(plan.points, plan.preset, { dials: plan.dials, straight: plan.drawn }).then((today) => {
      if (today.ok && savedShown.current?.key === key && differsTooMuch(saved.distance_m, today.route.distance_m))
        setSavedNote({ key, savedM: saved.distance_m, todayM: today.route.distance_m });
    });
  };
  const exportSaved = (saved: SavedRoute) => {
    if (saved.gpx) return downloadText(saved.gpx, verbatimFileName(saved.name));
    const answer = savedAnswer(saved);
    if (answer) downloadGpx(answer, saved.inputs.points, loopStops(saved.inputs.preset, saved.inputs.dials.loop));
    else downloadText(trackGpx(saved.name, saved.line), verbatimFileName(saved.name));
  };
  const updateSaved = () => {
    savedShown.current = null;
    setSavedNote(null);
    retry();
  };
  // A shared route's link (lib/sharedRoutes.ts): its exact line opens as a saved route does (the closure check,
  // Update route); a line no longer kept leaves the link's inputs planned again, said in one line.
  const [sharedNote, setSharedNote] = useState<string | null>(null);
  // The route a shared link opened as (its kept answer), and whether it was shared as a ride (Share ride) or as a
  // route: while it is the route shown or ridden, a ride is ridden fixed with location sharing offered (RideGroup),
  // and a route is the opener's own to change and ride, even a Mass Ride's. `own`: the ride this rider shared, not
  // held to it.
  const [sharedOpen, setSharedOpen] = useState<{ answer: RouteResponse; ride: boolean; own?: boolean } | null>(null);
  // The "planned again" line is about the plan the link named: a change to the plan clears it.
  useEffect(() => setSharedNote(null), [points, preset, dials]);
  useEffect(() => {
    if (!SHARED_ID) return;
    let live = true;
    void readShared(origin, SHARED_ID).then((shared) => {
      if (!live) return;
      if (shared === "revoked") {
        sharedRevoked = true;
        // Shown and said by the plan's error where the link carries a plan; where it carries none, shown here as a
        // plan's error is, and said.
        if (decodePlan(window.location.hash).points.length < 2) {
          setStatus({ kind: "error", error: SHARED_REVOKED_ERROR });
          announce(SHARED_REVOKED);
        }
      } else if (shared) {
        // The open's own check stands for the link's first-answer check.
        checkFirstAnswer.current = false;
        openSaved(shared, SHARED_OPENED(shared.name));
        if (shared.answer) setSharedOpen({ answer: shared.answer, ride: SHARED_RIDE });
      } else {
        setSharedNote(SHARED_GONE);
        announce(SHARED_GONE);
      }
      sharedArrived();
    });
    return () => {
      live = false;
    };
  }, []);
  const savedNoteShown = sharedNote ? (
    <p className="notice saved-note">{sharedNote}</p>
  ) : savedNote && savedNote.key === routedKey.current ? (
      <p className="notice saved-note">
        {differenceLine(savedNote.savedM, savedNote.todayM)}{" "}
        <button type="button" className="link" onClick={updateSaved}>
          {UPDATE_ROUTE}
        </button>
      </p>
    ) : null;

  const backToRideOpener = () => {
    const opener = rideOpener.current;
    (opener?.isConnected ? opener : startRideRef.current)?.focus();
  };
  // The ride just ended, kept for Undo for a few seconds (v0.7.0, "Go riding fixes" item 6: one tap on
  // End ends the ride with "Ride ended" and Undo). In memory only, as the ride itself is.
  // `from`: the plan End ride left starting where the rider was (part way), so Undo takes that edit back too.
  const endedRide = useRef<{ start: NonNullable<typeof rideStart>; from: LonLat[] | null } | null>(null);
  const [rideEnded, setRideEnded] = useState(0);
  const rideNow = useRef({ start: rideStart });
  rideNow.current = { start: rideStart };
  const endRide = useCallback((after: EndedPlan) => {
    const { start } = rideNow.current;
    // The plan stays, every route of it, to adjust and ride again (the owner, 2026-10-16: "You should keep all
    // the routes ... But be able to adjust things"). Part way, it starts where the rider is ("If you went part
    // way it changes your start location"): the stops passed dropped, a loop's finish still its start, as one
    // edit of the points (re-planned as any is; Undo of the plan takes it back). The start is the ride's own
    // last fix: no new location look-up.
    let from: LonLat[] | null = null;
    if (after && after !== "no-fix" && after.points.length >= 2) {
      from = after.points;
      const ride = rideRef.current;
      commit(from, ride.dials.loop ? { ...ride, dials: { ...ride.dials, loop: false } } : undefined);
      setFromHere((f) => [...f, from![0]]);
    }
    endedRide.current = start ? { start, from } : null;
    setRiding(false);
    setRideStart(null);
    setRideView(null);
    setRideEnded((n) => n + 1);
    // Said by the page's region, always mounted; the focus goes to Undo (RideEnded), not back to Start (review F6).
    announce(from ? RIDE_ENDED_FROM_HERE_SAID : after === "no-fix" ? RIDE_ENDED_NO_FIX_SAID : RIDE_ENDED_SAID);
  }, [announce, commit]);
  // A back gesture during a ride does nothing; End ride is the way out (lib/rideBack.ts, review RIDE-2).
  // Each held back is told, politely, once (review RIDE-2).
  useEffect(() => (riding ? holdBackDuringRide(window, () => announce(STILL_RIDING_SAID)) : undefined), [riding, announce]);
  // No ride is on at load: a ride's entry left by a reload is the page's own again.
  useEffect(() => forgetStaleRideEntry(window), []);
  const undoEndRide = () => {
    const ended = endedRide.current;
    endedRide.current = null;
    setRideEnded(0);
    if (!ended) return;
    // The plan End ride moved to where the rider was goes back, unless it has been edited since.
    if (ended.from && pointsRef.current === ended.from) edits.retract();
    startRideGesture(ridePrefs);
    setRideStart(ended.start);
    setFollow(true);
    setRideView(null);
    setRiding(true);
  };
  // The first ride's question takes the focus to its heading, so its safety note is read before the
  // choices (VoiceOver skips a dialog's description when the focus lands inside it).
  useEffect(() => {
    if (rideAsk) document.getElementById("ride-ask-title")?.focus();
  }, [rideAsk]);
  // Big text hides the map; shown again, it fits its box.
  useEffect(() => {
    if (!(riding && bigText)) mapRef.current?.resize();
  }, [bigText, riding]);

  // The map frames a route in the part the panel does not cover.
  const framePadding = useCallback((): Frame => {
    const panel = panelRef.current?.getBoundingClientRect();
    if (window.matchMedia(NARROW).matches) {
      // The attribution sits above the sheet on a phone; leave room for it too.
      return { top: 40, left: 30, right: 30, bottom: (panel?.height ?? 0) + 90 };
    }
    return { top: 60, bottom: 60, right: 60, left: (panel?.right ?? 0) + 40 };
  }, []);

  // Copy link keeps full precision; when the rider's location or Home is in the plan it says so (review privacy-2).
  const linkNote = linkLocationNote(points, fromHere, myGo.home?.point ?? null);

  const stale = status.kind === "loading" || status.kind === "waiting";
  const shown = status.kind === "error" || status.kind === "confirm" ? null : route;
  // Light times on the route (lib/lightTimes.ts): near dawn or dusk, where the rider will be at each, leaving now.
  // The clock runs only with a route shown, outside a ride; the same marks are kept while nothing they say changed.
  const minute = useMinute(shown !== null && !riding && (mode === "plan" || mode === "go"));
  const lightKept = useRef<LightMark[]>([]);
  const light = useMemo(() => {
    const next = routeLightMarks(shown, minute, dials.when ?? null);
    if (!sameLightMarks(lightKept.current, next)) lightKept.current = next;
    return lightKept.current;
  }, [shown, minute, dials.when]);
  // Share as image (ShareCardDialog, lib/shareCard.ts), beside Share in Plan's More: the route shown, the rider's
  // Home (an end or stop there is cut out of the image unless the rider unchecks it), and an opened file's own name.
  const [shareCardOpen, setShareCardOpen] = useState(false);
  const verbatimTrack = !importEdited ? imported?.verbatim?.track : undefined;
  const verbatimEnds = useMemo<LonLat[]>(
    () => (verbatimTrack && verbatimTrack.length > 0 ? [verbatimTrack[0], verbatimTrack[verbatimTrack.length - 1]].map(([lon, lat]) => [lon, lat] as LonLat) : []),
    [verbatimTrack],
  );
  const shareCardSource = useMemo<ShareCardSource | null>(
    () =>
      shown
        ? {
            line: shown.geometry.coordinates,
            points: routedPoints,
            home: myGo.home,
            name: imported?.name ?? null,
            distanceM: shown.distance_m,
            climbM: shown.climb_m ?? null,
            profile: usableProfile(shown),
            // An unedited opened file is shared as its own track: its ends are checked for Home too.
            homeCheck: verbatimEnds,
          }
        : null,
    [shown, routedPoints, myGo.home, imported?.name, verbatimEnds],
  );
  // Go, a ride, or the route gone closes it for good, so it does not open again on its own.
  useEffect(() => {
    if (mode === "go" || riding || !shown) setShareCardOpen(false);
  }, [mode, riding, shown]);
  const shareCardSettled = (!!imported?.verbatim && !importEdited) || (!!shown && !stale && routedPoints === points);
  // Go's Bikeshare options (lib/bikeshareOptions.ts): the first answer's list, kept for the trip, since a
  // re-plan of one option answers with that pair only.
  const [keptOptions, setKeptOptions] = useState<KeptOptions | null>(null);
  useEffect(() => {
    setKeptOptions((kept) => keepOptions(kept, bikeshareOf(route), optionsKey(routedPoints, route?.preset ?? "")));
  }, [route, routedPoints]);
  // Novice and Nervous where only a busy road connects (v0.7.0): both transit trips found at once, in the background,
  // so they show beside the bike route unasked, each with its time; a later route's offer asks again.
  const [noviceTrips, setNoviceTrips] = useState<{ key: string; trips: Partial<Record<PresetId, NoviceTrip>> } | null>(null);
  const noviceKey = noviceOfferShown(shown, preset) ? JSON.stringify(routedPoints) : null;
  useEffect(() => {
    if (noviceKey === null) return;
    const ends = noviceTripPoints(routedPoints);
    const found = (id: PresetId, trip: NoviceTrip) =>
      setNoviceTrips((was) => (was?.key === noviceKey ? { key: noviceKey, trips: { ...was.trips, [id]: trip } } : was));
    setNoviceTrips({ key: noviceKey, trips: {} });
    for (const choice of NOVICE_TRANSIT_CHOICES) {
      void requestRoute(ends, choice.preset, { dials: noviceTransitDials(choice.preset) }).then(
        (answer) => found(choice.preset, noviceTripOf(answer)),
        () => found(choice.preset, { kind: "none" }),
      );
    }
    // routedPoints is in noviceKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noviceKey]);
  const noviceTripsShown = noviceTrips && noviceTrips.key === noviceKey ? noviceTrips.trips : undefined;
  const goOptions =
    mode === "go" && usesBikeshare(preset) && shown && keptOptions && keptOptions.key === optionsKey(points, preset) && keptOptions.options.length > 1
      ? keptOptions.options
      : null;
  const pickOption = (index: number) => {
    const option = goOptions?.[index];
    // The one already planned: nothing to re-plan.
    if (!option || index === pickedOption(goOptions, bikeshareOf(shown))) return;
    if (replaysFirst(option)) {
      // A free e-bike: the first answer, shown again as it was (asking again could plan another bike or a
      // dock). Only for the plan it answered; else it is not re-planned, and that is said.
      const first = firstAnswer.current;
      if (!first || first.trip !== optionsKey(points, preset) || first.key !== sentPlanKey(points, preset, withStations(planDials, FIRST_ANSWER_PINS))) {
        // Shown and said (Go's notice), so the option is plainly not re-planned.
        setNotice(stationlessUnavailable(placeLetter(index)));
        return;
      }
      replayAsked.current = first.key;
      setStationPins(FIRST_ANSWER_PINS);
      announce(optionReplaySaid(placeLetter(index), option));
      return;
    }
    setStationPins(optionPins(option, points));
    setDials((d) => ({ ...d, ending: option.ending }));
    announce(optionSaid(placeLetter(index), option));
  };
  // A new answer: the Keep button's line was about the route before it.
  useEffect(() => setKeepSpoken({ text: "", count: 0 }), [answer]);
  // The water and restrooms along the route shown, in riding order: the route's "Water and restrooms" fold.
  // It is route data, not map clutter, so it is listed with the map layer off too (review of PR #96); the
  // layer's two filters still apply. The file is loaded once a route is shown.
  const routeShown = shown !== null;
  useEffect(() => {
    if (routeShown) void ensureWater();
  }, [routeShown, ensureWater]);
  const waterAlong = useMemo(
    () =>
      waterData && shown
        ? waterAlongRoute(shown.geometry.coordinates, waterData.filter((p) => waterVisible(p, waterPrefs)))
        : null,
    [waterData, waterPrefs, shown],
  );
  // The Climbs layer in words: the climbs the route rides, in riding order.
  const climbsAlong = useMemo(
    () =>
      climbsOn && climbsData && shown
        ? climbsAlongRoute(shown.geometry.coordinates, climbsData).filter((item) => climbShown(item.climb, climbsFrom))
        : null,
    [climbsOn, climbsData, shown, climbsFrom],
  );
  // Find food (lib/food.ts; FOOD-SEARCH, owner 2026-10-11): a map search by cuisine or name (blank for all
  // food), near the rider (the whole area, the default) or in the map's view. The places file is fetched on
  // the first search. The results are worked out again when the route changes, so each detour is off the
  // route shown (and the list is sorted by it); without a route, by distance from the rider's location where
  // the app has one (the owner, 2026-10-18), else from the map's center where the search was made.
  const [foodQuery, setFoodQuery] = useState("");
  const [foodScope, setFoodScope] = useState<FoodScope>("near");
  const [foodAsked, setFoodAsked] = useState<{ query: string; scope: FoodScope; bounds: Bounds | null; centre: LonLat; fromRider: boolean } | null>(null);
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
  nearestRoute.current = foodRoute;
  // A Water sheet list ranked by detour is for the route it was found on: a new route puts it away.
  useEffect(() => {
    setNearestList((list) => (list?.items[0]?.detour ? null : list));
  }, [foodRoute]);
  const foodAll = useMemo(
    () => (foodAsked && foodPlaces ? searchFood(foodPlaces, { ...foodAsked, route: foodRoute }) : null),
    [foodAsked, foodPlaces, foodRoute],
  );
  const foodResults = useMemo(() => foodAll?.slice(0, foodCount) ?? null, [foodAll, foodCount]);
  const foodRecentred = useRef(false);
  useEffect(() => {
    if (foodRecentred.current) {
      foodRecentred.current = false;
      return;
    }
    if (foodAll && foodAsked) sayFood(foodFoundSaid(foodAsked.query, foodAsked.scope, foodAll.length, Math.min(foodCount, foodAll.length), foodRoute !== null, foodAsked.fromRider));
    // Said for a new search or a new route, not for Show more (which says its own words).
  }, [foodAll]);
  // A list "near you" is from where the rider is now, not where the app last looked (the owner, 2026-10-18: "I was
  // trying to find food when there was no route yet" and the location did not update). Where the app already has a
  // location, an opening or a search shows its list from it at once and asks once more (one look-up, never a watch:
  // OWNER-DECISIONS 395); a new place answers with the list again from there. With none yet, nothing is asked: the
  // map's center stands in, as before. Go's start (the location, before a destination) moves with it.
  const lastHere = (): LonLat | null => here?.point ?? (goStartRef.current.kind === "here" ? goStartRef.current.point : null);
  const freshHere = async (): Promise<LonLat | null> => {
    const press = gate.begin();
    if (press === null) return null;
    setLocating(true);
    const result = await locate(geoEnv);
    if (!gate.finish(press)) return null;
    setLocating(false);
    // A Go destination that found the gate busy waits on this look-up: its answer settles it, as the others' do.
    if (goWaiting()) {
      settleGoWaiting(result);
      return result.ok && insideCoverage(result.fix.point) ? result.fix.point : null;
    }
    if (!result.ok || !insideCoverage(result.fix.point)) return null;
    // A plan's located start keeps its own fix: its note and accuracy circle are that point's.
    if (!(here && pointsRef.current.includes(here.point))) setHere(result.fix);
    if (goStartRef.current.kind === "here" && pointsRef.current.length === 0) setGoStart(goHereStart(result.fix.point));
    return result.fix.point;
  };
  // Only with no route (a route's lists go by least detour off it) and outside a ride (whose watch has the location).
  const freshWanted = () => nearestRoute.current === null && !ridingNow.current;
  // The latest search wins: a chip tapped while the opening search is still loading the file is not lost.
  const foodSeq = useRef(0);
  const searchFoodNow = async (asked?: string) => {
    const seq = ++foodSeq.current;
    const query = asked ?? foodQuery;
    if (!foodLoad.current) {
      foodLoad.current = loadFood(foodUrl).then((data) => {
        if (!data) foodLoad.current = null;
        return data;
      });
    }
    setFoodBusy(true);
    const places = await foodLoad.current;
    if (seq !== foodSeq.current) return;
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
    // From the rider where the app has a location (Go's fix, or the GPS dot), as the place sheets do.
    const fix = lastHere();
    setFoodPlaces(places);
    setFoodCount(FOOD_PAGE);
    setFoodAsked({
      query,
      scope: foodScope,
      bounds: b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null,
      centre: fix ?? (c ? [c.lng, c.lat] : [(COVERAGE_BBOX[0] + COVERAGE_BBOX[2]) / 2, (COVERAGE_BBOX[1] + COVERAGE_BBOX[3]) / 2]),
      fromRider: fix !== null,
    });
    // Near you: the list again from where the rider is now, once the look-up answers (whichever search asked it: a
    // second one while it is under way finds the gate busy and is answered by the first's).
    if (fix === null || foodScope !== "near" || !freshWanted()) return;
    const now = await freshHere();
    if (!now || haversineM(now, fix) < MOVED_M || viewNow.current !== "food") return;
    setFoodAsked((asked) => {
      if (asked?.scope !== "near" || !asked.fromRider) return asked;
      // The same words as the list just said: shown again, not said again (foodRecentred).
      foodRecentred.current = true;
      return { ...asked, centre: now };
    });
  };
  // Opening the Food sheet with nothing typed shows all food at once (the owner, 2026-10-18: "when searching
  // for food, all food should be shown up"), so a hungry rider needs no typing; each opening is from where the
  // rider is then.
  useEffect(() => {
    if (view === "food" && panelOpen && !foodQuery.trim()) void searchFoodNow("");
    // Only on opening the sheet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, panelOpen]);
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
  // v0.7.0's place sheets (app/PlacesSheets.tsx): Go's Repair and Sights behind More, Plan's Places to see.
  // Both list from the rider's location where the app has one (the owner, 2026-10-18: "The default for search
  // should be the current location"), else from the map's center.
  const placesOrigin = (): { point: LonLat; fromRider: boolean } | null => {
    const fix = lastHere();
    if (fix) return { point: fix, fromRider: true };
    const c = mapRef.current?.getCenter();
    return c ? { point: [c.lng, c.lat], fromRider: false } : null;
  };
  const repairList = useMemo(() => {
    if (view !== "repair") return null;
    if (repairData === null) return { items: [] as RepairNearby[], said: "Loading repair stands and bike shops…" };
    if (repairData === "unavailable") return { items: [] as RepairNearby[], said: REPAIR_UNAVAILABLE };
    const from = placesOrigin();
    if (!from) return { items: [] as RepairNearby[], said: REPAIR_NO_ORIGIN };
    // With a route shown, the least detour off it first (the owner, 2026-10-18: "Same for the other detour types").
    const items = nearestRepair(from.point, repairData, undefined, undefined, foodRoute);
    return { items, said: repairFoundSaid(items, from.fromRider) };
    // placesAsked: a new press is a new list from where the rider is now.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, repairData, placesAsked, foodRoute]);
  const placesFound = useMemo((): { list: SightResult[]; fromRider: boolean } | null => {
    if (view !== "places" || !Array.isArray(placesData)) return null;
    const from = placesOrigin();
    if (!from) return { list: [], fromRider: false };
    const list = mode === "go" ? sightsForGo(placesData, from.point, foodRoute) : placesToSee(placesData, from.point, foodRoute, placesFilter);
    return { list, fromRider: from.fromRider };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, placesData, foodRoute, placesFilter, mode, placesAsked]);
  const placesAll = placesFound?.list ?? null;
  const placesShown = placesAll && mode !== "go" ? placesAll.slice(0, placesCount) : placesAll;
  const placesStatus =
    placesData === null
      ? "Loading places to see…"
      : placesData === "unavailable"
        ? PLACES_UNAVAILABLE
        : placesData.length === 0
          ? PLACES_NONE
          : placesAll
            ? placesSaid(placesAll.length, mode === "go" ? "all" : placesFilter, foodRoute !== null, placesFound?.fromRider ?? false)
            : "";
  // Each opening lists from the last location at once, then from a fresh one where the rider has moved (freshHere).
  const placesFromNow = () => {
    const fix = lastHere();
    if (!fix || !freshWanted()) return;
    void freshHere().then((now) => {
      if (now && haversineM(now, fix) >= MOVED_M) setPlacesAsked((n) => n + 1);
    });
  };
  const openRepair = (chip: HTMLElement) => {
    ensureRepair();
    setPlacesAsked((n) => n + 1);
    openView("repair", chip);
    placesFromNow();
  };
  const openPlaces = (chip: HTMLElement) => {
    ensurePlaces();
    setPlacesAsked((n) => n + 1);
    setPlacesCount(PLACES_PAGE);
    openView("places", chip);
    placesFromNow();
  };
  const rideToRepair = (item: RepairNearby) => goToLettered([item.place.lon, item.place.lat], repairTitle(item.place));
  const showSight = (r: SightResult) => {
    const map = mapRef.current;
    const n = placesShown?.indexOf(r) ?? -1;
    map?.flyTo({ center: [r.place.lon, r.place.lat], zoom: Math.max(map.getZoom(), 15) });
    announce(`Showing ${r.place.name} on the map${n >= 0 ? `, marker ${placeLetter(n)}` : ""}.`);
  };
  const addSightStop = (r: SightResult) => {
    const point: LonLat = [r.place.lon, r.place.lat];
    namer.remember(point, r.place.name);
    placeSpot("via", point);
  };
  // Go's Sights: one tap; a stop on the route when there is one (the owner: "a tap to add as a stop"), else the destination.
  const goPickSight = (r: SightResult) => (points.length >= 2 ? addSightStop(r) : goToLettered([r.place.lon, r.place.lat], r.place.name));
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
  // An instance admin's review (rider suggestions, Mass Ride hazard reports): from Suggest, or Go's Menu. It opens
  // Review, the third view (lib/appMode.ts), on the riders' suggestions.
  const reviewOpener = canReview
    ? () => {
        setReviewList("suggestions");
        changeMode("review");
      }
    : null;
  const myGoControls = { myGo, signedIn: me.signed_in, save: saveMyGoNow, setHome, said: myGoSaid, geoGate, searchBias };
  // Go's Menu (the Settings sheet in Go): Plan, Suggest, GPX and an admin's Review, each one step in.
  const menu = {
    onPlan: () => changeMode("plan"),
    onSuggest: (opener: HTMLElement) => openView("suggest", opener, true),
    onGpx: (opener: HTMLElement) => openView("gpx", opener, true),
    onReview: canReview ? () => changeMode("review") : null,
  };
  // The lettered places (the owner, 2026-10-11 21:04 UTC; lib/letteredPlaces.ts): the list on the sheet open,
  // the nearest water, restrooms or Metro, or the food found, lettered on the map as in the list. A pick (its
  // marker, Ride here in Go, or its letter's key) is the destination in Go, straight to the route options;
  // in Plan, the nearest's Ride here, and food's Show on map.
  const letteredOf: "nearest" | "food" | "repair" | "places" | "bikeshare" | null =
    view === "nearest" && nearestList && nearestList.items.length > 0
      ? "nearest"
      : view === "food" && foodResults && foodResults.length > 0
        ? "food"
        : view === "repair" && repairList && repairList.items.length > 0
          ? "repair"
          : view === "places" && placesShown && placesShown.length > 0
            ? "places"
        : goOptions && !(panelOpen && view !== "planner")
          ? "bikeshare"
          : null;
  const lettered = useMemo(
    () =>
      letteredOf === "nearest" && nearestList
        ? letterPlaces(nearestList.items, (item) => ({ point: item.place.point, title: item.place.title, metres: item.detour ? null : item.distanceM }))
        : letteredOf === "food" && foodResults
          ? letterPlaces(foodResults, (r) => ({ point: [r.place.lon, r.place.lat] as LonLat, title: r.place.name, metres: r.detour ? null : r.fromCentreM }))
          : letteredOf === "repair" && repairList
            ? letterPlaces(repairList.items, (item) => ({ point: [item.place.lon, item.place.lat] as LonLat, title: repairTitle(item.place), metres: item.metres }))
            : letteredOf === "places" && placesShown
              ? letterPlaces(placesShown, (r) => ({ point: [r.place.lon, r.place.lat] as LonLat, title: r.place.name, metres: r.detour ? null : r.metres }))
          : letteredOf === "bikeshare" && goOptions
            ? // Each option at its pick-up station, named as its button is.
              goOptions.map((o, i) => ({ letter: placeLetter(i), point: [o.pickup.lon, o.pickup.lat] as LonLat, name: optionName(placeLetter(i), o) }))
            : null,
    [letteredOf, nearestList, foodResults, repairList, placesShown, goOptions],
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
      // With a route in Go, a chip's place is a stop on it (v0.7.0); before one, the destination.
      if (mode === "go" && goStops) {
        namer.remember(item.place.point, item.place.title);
        showPlanner(true);
        goAddStopAt(item.place.point, item.place.title);
      } else if (mode === "go") goToLettered(item.place.point, item.place.title);
      else rideToNearest(item);
    } else if (letteredOf === "food" && foodResults) {
      const r = foodResults[index];
      if (!r) return;
      if (mode === "go" && goStops) {
        const point: LonLat = [r.place.lon, r.place.lat];
        namer.remember(point, r.place.name);
        showPlanner(true);
        goAddStopAt(point, r.place.name);
      } else if (mode === "go") goToLettered([r.place.lon, r.place.lat], r.place.name);
      else showFood(r);
    } else if (letteredOf === "repair" && repairList) {
      const item = repairList.items[index];
      if (item) rideToRepair(item);
    } else if (letteredOf === "places" && placesShown) {
      const r = placesShown[index];
      if (!r) return;
      if (mode === "go") goPickSight(r);
      else showSight(r);
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
  // The climb card's "Ride this climb" (lib/climbCard.ts; the owner, 2026-10-12: "add it to a destination").
  // Go: the climb's top is the destination and its bottom a stop on the way, planned at once from Go's start.
  // Plan: its bottom then its top go in as the next two stops before the destination (rideClimbEdit). One
  // edit either way, so Undo takes it back.
  const rideClimb = (climb: Climb) => {
    const { bottom, top } = climbEnds(climb);
    namer.remember(bottom, climbEndName(climb, "Bottom"));
    namer.remember(top, climbEndName(climb, "Top"));
    if (modeRef.current === "go") {
      showPlanner(true);
      void goTo(top, climbEndName(climb, "the top"), false, [bottom]);
      return;
    }
    if (!insideCoverage(bottom) || !insideCoverage(top)) {
      setNotice(OUTSIDE_NOTICE);
      return;
    }
    const edit = rideClimbEdit(pointsRef.current, { bottom, top }, loopVias);
    if ("refused" in edit) {
      setNotice(edit.refused);
      return;
    }
    setNotice(null);
    commit(edit.next);
    announce(edit.said);
  };
  // The road panel's "Climb details" (the keyboard's way to a climb's card): the card, focused, once the panel has closed.
  const [climbCardRequest, setClimbCardRequest] = useState<{ climb: Climb; n: number } | null>(null);
  const showClimbCard = (climb: Climb) => window.setTimeout(() => setClimbCardRequest((prior) => ({ climb, n: (prior?.n ?? 0) + 1 })), 0);
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
    // A bikeshare ride runs dock to dock, not between the points, and a transit ride's line is its
    // first ride only: neither line is theirs to drag.
    if (bikeshareOf(shown) || shown.transit) return null;
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
      ? `Planning a ${presetSaid(preset)} route…`
      : status.kind === "waiting"
        ? `The planner is busy; trying again in ${formatSeconds(status.seconds)}.`
        : status.kind === "ok" && route
          ? // On arrival the answer's own count is said (More direct and Calmer come later, said once by their own
            // line); a route chosen is said by its place among all the routes shown, or by its name.
            announceRoute(route, routedPoints, chosen ? announceHow(picked, choice, true) : announceHow(answer, choice, false))
          : "";
  // The route's sentence once it has stood a moment (lib/settle.ts): routes
  // that replace each other quickly are said once, the last. "Planning..." is
  // shown but not said, so a release is one announcement, not two.
  const settledSaid = useSettled(status.kind === "ok" ? announcement : "", ANNOUNCE_SETTLE_MS);
  // While a full plan stands in for Go's first route, the region keeps the first route's sentence: the swap has its
  // own line (lib/progressive.ts betterRouteSaid), said once, and a better route is not read out twice.
  const routeSaid = refinedHeld && answer === refinedHeld.route ? refinedHeld.said : settledSaid;
  routeSaidNow.current = routeSaid;
  // A plan still going after a few seconds is said once, so a screen-reader rider
  // can tell a slow plan (a calm route at the top of the slider takes up to half a
  // minute) from a dead one (the a11y review's SF1).
  const slow = useLongerThan(status.kind === "loading", STILL_PLANNING_AFTER_MS);

  // Plan's search and point tools stay in view with a route (v0.7.0, "Keep adding stops by search"; the plan
  // panel holds the plan in words): the points are no longer compacted.
  const compactPoints = false;
  // A route arriving while the focus is in the search or the point tools hides
  // them: the focus goes to "Edit points" rather than dropping to the page (lib/sidebar.ts
  // rescueCompactFocus; the review's B1). After the sheet-order effect above, which may put the
  // focus back on the element it had.
  useLayoutEffect(() => {
    rescueCompactFocus({
      wasCompact: wasCompact.current,
      compact: compactPoints,
      before: focusBeforeRender.current,
      hidden: [pointsEditRef.current],
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
  // ---- Plan mode's plan panel (v0.7.0, "Plan mode: write the plan first, then route"; lib/planFirst.ts) ----
  // The plan differs from the one the route shown was drawn for: the line greys, and the button reads Update route.
  const planEdited = planFirst && planChanged(drawn, points, preset, planKey);
  // The ghost and the change summary last until the next change.
  useEffect(() => {
    if (!planEdited) return;
    setGhost(null);
    setChangeLine(null);
    setChangeDetails([]);
  }, [planEdited]);
  // While routing: the seconds since it began, for the step in words and the count.
  const routingNow = status.kind === "loading" || status.kind === "waiting";
  const [routingSince, setRoutingSince] = useState(0);
  const [routingTick, setRoutingTick] = useState(0);
  useEffect(() => {
    if (!routingNow) return;
    const start = Date.now();
    setRoutingSince(start);
    setRoutingTick(start);
    const timer = window.setInterval(() => setRoutingTick(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [routingNow]);
  const pressRoute = () => {
    setRouteAsk((n) => n + 1);
    announce(PLANNING_SAID);
  };
  const cancelRouting = () => {
    scheduler.current?.clear();
    // Nothing is asked now: a station chosen later re-plans only after the next Route.
    asked.current = null;
    setStatus(answer ? { kind: "ok" } : { kind: "idle" });
    announce(CANCELLED_SAID);
  };
  // Reset: back to the plan the route was drawn for (its points, ride type and sliders), with no re-routing;
  // one edit, so Undo brings the changes back.
  const resetPlan = () => {
    const back = drawnRef.current;
    if (!back || !planEdited) return;
    commit(back.points as LonLat[], back.ride);
    setStationPins(back.pins);
    setTransitPick(back.transitPick);
    setNotice(null);
    announce(RESET_SAID);
  };
  // Clear: every point, the drawn route, its ghost and the change summary; the ride type and sliders stay.
  const clearPlan = () => {
    setGhost(null);
    setChangeLine(null);
    setChangeDetails([]);
    clearAll();
  };
  const routeNow = routeButton({ points: points.length, drawn: drawn !== null, changed: planEdited, routeShown: shown !== null });
  // Plan's bar at the top of the map (the owner, 2026-10-17: "In plan, make "Update route" a big button at the top of
  // the map ... Update route or start route. don't show if there's nothing to change. Also put the undo and clear there
  // as well, smaller"): the Route button big while there is something to route (or it is routing), Undo, Redo and
  // Clear small beside it while each has something to do. A focus left on a button of the bar that went (the
  // big one after routing, Clear after clearing) moves to the panel's Route button where it shows, else the map
  // (never to Clear, where a second Enter would clear the plan).
  const barRoute = planFirst && (routingNow || routeNow.unavailable === null);
  const planBar = planFirst && (barRoute || can.undo || can.redo || points.length > 0);
  const barFocused = useRef(false);
  useEffect(() => {
    if (!barFocused.current) return;
    const active = document.activeElement;
    if (active && active !== document.body && active.isConnected) return;
    barFocused.current = false;
    const route = document.querySelector<HTMLElement>(".plan-panel .route-button");
    (route?.offsetParent ? route : document.querySelector<HTMLElement>(".maplibregl-canvas"))?.focus();
  });
  // Go's bar mirrors Plan's (the owner, 2026-10-18: "mirror what plan does in general, but instead of route, we
  // start the ride"): Undo, Redo, the big button and Clear, each while it has something to do. The big button is
  // Start ride on a route ready to ride, else Route while the plan has changed, as Plan's.
  const goReady = !!shown && !stale && routedPoints === points && rideableRoute(shown);
  const goBig = routingNow
    ? { label: ROUTING_LABEL, start: false, busy: true, onPress: () => {} }
    : goReady
      ? { label: "Start ride", start: true, busy: false, onPress: startRideChecked }
      : points.length >= 2 && routeNow.unavailable === null
        ? { label: routeNow.label, start: false, busy: false, onPress: pressRoute }
        : null;
  const goBar =
    mode === "go" && !riding && (goBig !== null || can.undo || can.redo || points.length > 0)
      ? { onUndo: can.undo ? undo : null, onRedo: can.redo ? redo : null, big: goBig, onClear: points.length > 0 ? clearPlan : null }
      : null;
  const planPanel = (
    <PlanPanel
      key="plan"
      sentences={planSentences(points, VIA_MARKS.isVia, loopVias, (p) => namer.name(p)?.name, {
        ride: presetSaid(preset),
        traffic: stressMax(preset) > 0 ? stressWords(dials.stress) : null,
        hills: hillsWords(dials.hills, seeksClimbs(preset)),
      })}
      button={routeNow}
      onRoute={pressRoute}
      routing={routingNow ? { step: routingStep(routingTick - routingSince), elapsed: elapsedText(routingTick - routingSince) } : null}
      onCancel={cancelRouting}
      change={planEdited ? null : changeLine}
      details={changeDetails}
      onCloseChange={() => {
        setChangeLine(null);
        setChangeDetails([]);
        setGhost(null);
      }}
      resetUnavailable={planEdited ? null : RESET_NOTHING}
      onReset={resetPlan}
      clearDisabled={points.length === 0}
      onClear={clearPlan}
    />
  );
  const pointsSection = (
    <PointsSection key="points"
      {...{
        pointsHeadingRef, zoom, stressVisible, stress, pointsSearchRef, compactPoints, points, loopVias, geoGate,
        searchBias, pickPlace, locateReady, locating, hereInPlan, here, useMyLocation, loop, loopHintId, commitDials,
        dials, accessMode, namer, located: fromHere, removeAt, reorderPoint, pointWarnings, removeRefs, preset, stationChoice, chooseStation,
        federalPlanner,
        pointsEditRef, reverseButton, reverse, reverseHint, orderShown, bestOrder, orderFocused, ordering, narrow,
        undo, can, redo, coverageShown, toggleAccessMode, announce, notice, noticeLive: mode !== "go", tips, setTips, tipsId,
      }}
    />
  );
  const goMode = mode === "go";
  // Review (lib/appMode.ts): the panel holds the queues and the map their roads; the plan stays as it was, unshown.
  const reviewing = mode === "review" && canReview;
  announceLevelNow.current = announceLevel(announceChoice, mode);
  const chooseAnnounce = (level: AnnounceLevel) => {
    setAnnounceChoice(level);
    writeAnnounceChoice(level);
    announce(level === "brief" ? "Announcements: brief." : "Announcements: full.");
  };
  // A bikeshare ride's station choice (the Points section's, before): under Route, closed, as the mockup has it.
  const stations =
    usesBikeshare(preset) && points.length > 0 ? (
      <Fold title="Choose a station" icon="bikeshare" className="stations-fold">
        <NearbyStations points={points} pins={stationChoice} onChoose={chooseStation} />
      </Fold>
    ) : null;
  const actions = {
    routedLoop, copyLink, linkNote, shareImage: () => setShareCardOpen(true), linkSpoken, keepShown, keepForOffline, keeping, keepSpoken, linkSaid,
    downloadRoute, save: saveProps, savedNote: savedNoteShown,
  };
  // Go's ride types: before a route under the place chips, with one under the route card (edit-route redesign).
  const goRides = <RideChips ids={goRideChips(myGo.ride)} preset={preset} onPick={pickRide} more={(opener) => openView("ride", opener)} label="Ride type" ownHint={OWN_RIDE_HINT} />;
  const go = {
    peek: goSheet === "peek",
    full: goSheet === "full" || (!narrow && goSheet !== "peek"),
    options: goOptions ? { list: goOptions, picked: pickedOption(goOptions, bikeshareOf(shown)), busy: stale, onPick: pickOption } : null,
    // Novice and Nervous's offer where only a busy road connects (v0.7.0): the trip on a transit ride type, its
    // bike legs still planned as Novice and Nervous plans them (`noviceLegs`, sent as novice_legs, kept in the link).
    onNoviceTransit: (id: PresetId) => {
      choosePreset(id, { ...chooseRideType(id, null, dials), noviceLegs: true });
      const label = NOVICE_TRANSIT_CHOICES.find((c) => c.preset === id)?.label ?? presetSaid(id);
      announce(noviceTransitSaid(label));
    },
    noviceTrips: noviceTripsShown,
    // The route card (edit-route redesign, Stephen 2026-10-18): the start and the destination, and Edit route, which
    // opens Plan's points in a sheet; with a route and never during a ride.
    routeCard:
      !riding && points.length >= 2 ? (
        <GoRouteCard
          start={fromHere.includes(points[0]) ? YOUR_LOCATION : goPlaceName(namer.name(points[0])?.name, points[0])}
          destination={loopVias ? "Back to the start" : goPlaceName(namer.name(points[points.length - 1])?.name, points[points.length - 1])}
          stops={loopVias ? points.length - 1 : points.length - 2}
          onEdit={(opener) => openView("points", opener)}
        />
      ) : null,
    rides: goRides,
    // "Add a stop", under the route card (Stephen 2026-10-18: kept one tap away); only with a route, never riding.
    addStop: goStops ? (
      <GoAddStop
        geoGate={geoGate}
        searchBias={searchBias}
        onPick={goAddStop}
        full={points.length >= MAX_POINTS}
        orderShown={orderShown}
        ordering={ordering}
        onBestOrder={() => void bestOrder()}
      />
    ) : null,
  };
  // A transit plan's options (lib/transit.ts): a press plans that one, for this trip; a departure the
  // rider would miss plans again, which takes the next one (lib/departure.ts).
  const transitControls = {
    onPick: (key: string) => {
      const option = transitOf(shown)?.options.find((o) => o.key === key);
      setTransitPick({ trip, key });
      if (option) announce(optionChosenSaid(option));
    },
    announce,
    onMissed: retry,
    onRideRest: rideRestFromPanel,
  };
  const routeSection = (
    <RouteSection key="route"
      {...{
        mode, actions, stations, go, transitControls,
        stale, routeHeadingRef, status, announcement, slow, preset, dials, points, cancelLong, planButtonRef,
        confirmLong, errorRef, retry, shown, answer: picked, choice, aroundAvoid, setAroundAvoid, routedPoints, federalRoute,
        narrow, setJunctionFocus, setScrubPoint, choose, startRide: startRideChecked, startRideRef, rideSize, setDials,
        waterStatus, waterAlong, addWaterStop, rideAsk, setRideAsk, backToRideOpener, ridePrefs, changeRidePrefs,
        rideStartFirstRef, beginRide, climbsOn, climbsStatus, climbsAlong, light,
      }}
    />
  );

  const sections: Record<SheetSection, ReactElement> = {
    presets: (
      <RideSection key="presets"
        {...{
          preset, dials, choosePreset, commitDials, route, typeCard: mode !== "go",
        }}
      />
    ),
    points: pointsSection,
    route: routeSection,
  };

  // A Mass Ride or Group Ride link, in Go or riding: the others on the route (RideGroup), by the link's points. A
  // link shared as a ride (Share ride), any ride type, while its route is the one shown or ridden: as a Group Ride
  // where it is not a Mass Ride. One shared as a route has none.
  const rideGroupPoints = riding && rideStart ? rideStart.points : points;
  const onShared = sharedOpen !== null && (riding ? rideStart?.route : shown) === sharedOpen.answer ? sharedOpen : null;
  // The shared line itself, not a re-route its sharer took off it: everyone is placed along the one route.
  const rideGroupRoute = onShared ? onShared.answer : riding && rideView ? rideView.route : shown;
  const rideGroupType: RideLinkType | null =
    onShared && !onShared.ride ? null : isRideLink(preset, rideGroupPoints) ? preset : onShared && rideGroupPoints.length >= 2 ? "group-ride" : null;
  const rideGroupLine = (goMode || riding) && rideGroupType && rideGroupRoute ? (rideGroupRoute.geometry.coordinates as LonLat[]) : null;

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
          modes={switchModes(canReview)}
          onMenu={(button) => openView("settings", button)}
          onLayers={(button) => openView("layers", button)}
          onLocate={() => void goLocate()}
          locating={locating}
          destination={points.length > 0 ? goPlaceName(namer.name(points[points.length - 1])?.name, points[points.length - 1]) : null}
          bar={goBar}
        />
      )}
      <MapView
        points={riding || reviewing ? NO_POINTS : points}
        loopVias={loopVias}
        openAt={OPEN_AT}
        pointWarnings={riding || reviewing ? undefined : pointWarnings}
        route={riding && rideView ? rideView.route : reviewing ? null : shown}
        stale={riding ? false : stale || planEdited}
        permitsOn={!riding && permitsShown(permitsOn, mode)}
        // Plan's ghost of the last route; else the standard way through a closure the route goes round, dashed
        // beside it (v0.8.2), in Go and Plan, and on the ride the line not being followed.
        ghost={riding ? (rideView?.other ?? null) : reviewing ? null : (ghost ?? shown?.closure_through?.geometry.coordinates ?? null)}
        lightMarks={riding || mode !== "plan" ? null : light}
        stressVisible={stressVisible && stress === "available"}
        when={mapWhen(dials.when ?? null)}
        framePadding={framePadding}
        onStressAvailability={setStress}
        onMapClick={riding || reviewing ? ignore : place}
        onMovePoint={riding ? ignore : move}
        lineEdit={riding || reviewing ? null : lineEdit}
        onLineDrop={riding || reviewing ? ignore : insertOnLine}
        pressSetsEnd={goTapSetsEnd(mode)}
        onRemovePoint={riding ? ignore : removeFromMap}
        onSwitchKind={riding ? ignore : switchKind}
        markerReset={markerReset}
        accuracy={riding ? rideCircle : hereCircle}
        rider={riding && rideView?.rider ? rideView.rider : null}
        nextVehicle={riding ? (rideView?.vehicle ?? null) : null}
        // Go, before a destination: its start, the location found, drawn as the ride's still dot (the owner,
        // 2026-10-17: the location centred, so it is seen). With a route its start pin marks it.
        youDot={!riding && mode === "go" && points.length === 0 && goStart.kind === "here" ? goStart.point : null}
        follow={riding && follow && !bigText /* Big text hides the map: no camera work for it */}
        headingUp={headingUp}
        onFollowBroken={() => setFollow(false)}
        junctionFocus={junctionFocus}
        scrubPoint={scrubPoint}
        lettered={riding ? null : lettered}
        onLettered={pickLettered}
        onClosureBypass={(item, on) => {
          setClosureBypass((now) => toggleBypass(now, bypassPlan, item.id, on));
          announce(bypassSaid(item, on));
        }}
        onReady={(map) => {
          mapRef.current = map;
          if (centreWhenReady.current) flyToInView(centreWhenReady.current, 15);
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
        railClosedReason={railClosedReason}
        railBadges={railBadgesOf}
        massCapacity={massMap}
        massArea={isMassRide(preset)}
        massHazards={massHazards}
        water={waterData}
        waterPrefs={waterPrefs}
        climbs={climbsData}
        climbsOn={climbsOn}
        climbsFrom={climbsFrom}
        onRideClimb={riding ? ignore : rideClimb}
        climbCardRequest={climbCardRequest}
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
            addDisabled={!goTapSetsEnd(mode) && points.length >= MAX_POINTS}
            setsEnd={goTapSetsEnd(mode)}
            onRoadInfo={roadInfoAtCentre}
            onCrosshair={toolsCrosshair}
            onShown={toolsShown}
          />
          ) : null
        }
      />
      <RepairStandsOverlay getMap={getMap} places={Array.isArray(repairData) ? repairData : null} on={waterPrefs.on && !riding} pixelRatio={Math.min(2, Math.max(1, Math.round(window.devicePixelRatio || 1)))} />
      <PlacesOverlay getMap={getMap} places={Array.isArray(placesData) ? placesData : null} on={placesOn && !riding} />
      <FoodOverlay getMap={getMap} results={foodAll} on={letteredOf === "food" && !riding} />
      <TrailMilesOverlay getMap={getMap} data={trailMiles} />
      {/* Not in Go, and not on the Mass Ride map (lib/scenicLayer.ts scenicShown). */}
      <ScenicOverlay getMap={getMap} places={Array.isArray(placesData) ? placesData : null} on={scenicShown(scenicOn, mode, massMap)} placesOn={placesOn && !riding} />
      <BikeshareDocksOverlay
        active={docksActive}
        getMap={getMap}
        ask={docksAsk}
        operators={docksOperators}
        pixelRatio={Math.min(2, Math.max(1, Math.round(window.devicePixelRatio || 1)))}
        onReport={onDocksReport}
      />
      {rideGroupLine && (
        <RideGroup type={rideGroupType ?? "group-ride"} points={rideGroupPoints} line={rideGroupLine} getMap={getMap} here={rideView?.rider?.point ?? (here ? here.point : null)} />
      )}
      <ClosureDialog ask={closureAsk} onReroute={() => void closureReroute()} onAnyway={closureAnyway} onCancel={closureCancel} />
      <ShareCardDialog
        open={shareCardOpen && shareCardSource !== null && mode !== "go" && !riding}
        source={shareCardSource}
        settled={shareCardSettled}
        keepKey={JSON.stringify(keepFields(shareKeep))}
        makeLink={shareCardLink}
        onClose={() => setShareCardOpen(false)}
      />
      <RoadInfoDialog
        request={roadInfo}
        massRide={massMap}
        hazards={massHazards}
        station={roadInfo ? stationNearSpot(RAIL_STATIONS, rail, roadInfo.point, WMATA_SLUGS)?.station ?? null : null}
        rail={rail}
        stationClosed={railClosedReason}
        avoid={roadInfo ? avoidNearSpot(route, roadInfo.point) : null}
        junctionShown={roadInfo ? shownNear(route, roadInfo.point) : null}
        federal={roadInfo && federalShown(preset, true) ? federalAreaAt(roadInfo.point, federalData) : null}
        climb={roadInfo && climbsOn ? climbNearSpot(climbsData, roadInfo.point, climbsFrom) : null}
        onShowClimb={showClimbCard}
        trailMiles={trailMiles}
        onClose={closeRoadInfo}
        fallbackFocus={mapFocus}
        onStressChanged={(generation) => {
          // An instance admin changed a road (OWNER-DECISIONS 441h): the map asks for its tiles again.
          const map = mapRef.current;
          if (map) refreshStressTiles(map, window.location.origin, generation);
        }}
        plan={{ count: points.length, loop: loopVias }}
        onPlace={placeSpot}
        onSetHome={(point) => void setHomeAt(point)}
      />
      {crosshairShown && (
        <div className="crosshair" aria-hidden="true" style={crosshairAt ? { left: crosshairAt.x, top: crosshairAt.y } : undefined} />
      )}
      {planBar && (
        <div
          className="plan-map-bar"
          role="group"
          aria-label="Route and edits"
          onFocus={() => (barFocused.current = true)}
          onBlur={(event) => {
            if (event.relatedTarget) barFocused.current = false;
          }}
        >
          {can.undo && (
            <button type="button" className="secondary plan-bar-small" data-history="undo" onClick={undo} aria-label="Undo" title="Undo">
              <Icon name="undo" size={20} />
            </button>
          )}
          {can.redo && (
            <button type="button" className="secondary plan-bar-small" data-history="redo" onClick={redo} aria-label="Redo" title="Redo">
              <Icon name="redo" size={20} />
            </button>
          )}
          {barRoute && (
            <button
              type="button"
              className="plan-bar-route"
              aria-disabled={routingNow ? true : undefined}
              onClick={() => {
                if (!routingNow) pressRoute();
              }}
            >
              <Icon name="routes" size={20} />
              {routingNow ? ROUTING_LABEL : routeNow.label}
            </button>
          )}
          {manualOffered && (
            <button
              type="button"
              className="secondary plan-bar-small plan-bar-manual"
              aria-pressed={manual}
              aria-label={MANUAL_LABEL}
              title={MANUAL_TITLE}
              onClick={() => {
                setManualOn(!manual);
                announce(manual ? MANUAL_OFF_SAID : MANUAL_ON_SAID);
              }}
            >
              <Icon name="draw" size={20} />
            </button>
          )}
          {points.length > 0 && (
            <button type="button" className="secondary plan-bar-small" onClick={clearPlan} aria-label={`${CLEAR_LABEL} the plan`} title={CLEAR_LABEL}>
              <Icon name="trash" size={20} />
            </button>
          )}
        </div>
      )}
      {!riding && !goMode && <PlanMapChips onFood={(chip) => openView("food", chip)} onWater={(chip) => openView("nearest", chip)} onPlaces={openPlaces} />}
      {/* In Plan, Undo and Redo are in the plan's bar at the top of the map instead. */}
      {!riding && narrow && !planFirst && !goMode && (can.undo || can.redo) && (
        // On a phone the sheet may be hidden while the rider edits the map,
        // so Undo and Redo sit on the map there (and only there: one of each
        // per layout), each shown while it has something to give back.
        <div className="map-history">
          {can.undo && (
            <button type="button" data-history="undo" onClick={undo}>
              Undo
            </button>
          )}
          {can.redo && (
            <button type="button" data-history="redo" onClick={redo}>
              Redo
            </button>
          )}
        </div>
      )}
      {/* The beta notice: a chip in the map's free bottom-left corner, only in a VITE_BETA=1 build. */}
      {!riding && (
        <BetaChip
          enabled={isBetaBuild(import.meta.env.VITE_BETA)}
          reportUrl={betaReportUrl(import.meta.env.VITE_BETA_REPORT_URL)}
        />
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
      {!riding && rideEnded > 0 && (
        <RideEnded
          key={rideEnded}
          onUndo={undoEndRide}
          onGone={() => {
            endedRide.current = null;
            setRideEnded(0);
          }}
        />
      )}
      {riding && rideStart && (
        <RideMode
          key={rideStart.n}
          route={rideStart.route}
          points={rideStart.points}
          loop={rideStart.loop}
          preset={rideStart.preset}
          trip={rideStart.trip}
          onRideRest={(riderAt) => rideRest(riderAt, true)}
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
          trailMiles={trailMiles}
          keepLastRide={isStandalone()}
          fixed={rideStart.fixed}
        />
      )}
      {/* Hidden, not removed, during a ride: the planner keeps its state, and Sign in is out of reach (plan section 7). */}
      <aside
        ref={panelRef}
        id="route-planner"
        tabIndex={-1}
        className={`panel ${panelOpen ? "open" : "closed"}${goMode ? ` go-panel go-${goSheet}` : ""}${reviewing ? " review-panel" : ""}`}
        aria-label="Route planner"
        hidden={riding}
      >
        <header className="panel-header">
          <h1 ref={plannerHeadingRef} tabIndex={-1} className={goMode ? "visually-hidden" : undefined}>
            {PLANNER_TITLE}
          </h1>
          {!goMode && <ModeSwitch mode={mode} onChange={changeMode} className="panel-mode" modes={switchModes(canReview)} />}
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
          <AppStatusBar status={appStatus} />
          {homeAsk && (
            <section className="home-offer" aria-labelledby="home-offer-heading">
              <h2 id="home-offer-heading" className="visually-hidden">
                Home on this device
              </h2>
              <p>{homeAsk.question}</p>
              <div className="actions">
                <button type="button" onClick={() => answerHome(true)}>
                  {homeAsk.move}
                </button>
                <button type="button" className="secondary" onClick={() => answerHome(false)}>
                  {homeAsk.keep}
                </button>
              </div>
            </section>
          )}
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
                  onTopPlace={goEarlyToPlace}
                  places={{
                    homeReady: myGo.home !== null,
                    home: myGo.home,
                    onHomePlace: (found) => setHome(homeFromPlace(found)),
                    onClearHome: () => setHome(null),
                    homePicking: homePick,
                    onPickHome: pickHome,
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
                    onRepair: openRepair,
                    onSights: openPlaces,
                  }}
                  rides={goRides}
                  notice={notice}
                  route={points.length > 1 || status.kind !== "idle" ? routeSection : null}
                  startLine={goStartLine(goStart, points.length > 0 ? (namer.name(points[0])?.name ?? "the point on the map") : null)}
                  startMissing={goStart.kind === "none" && points.length === 0}
                  onStartPick={goStartPick}
                />
              ) : reviewing ? (
                <ReviewMode
                  getMap={getMap}
                  announce={announce}
                  list={reviewList}
                  onList={setReviewList}
                  onStressChanged={(generation) => {
                    const map = mapRef.current;
                    if (map) refreshStressTiles(map, window.location.origin, generation);
                  }}
                  onHazardsChanged={() => setHazardsAsked((n) => n + 1)}
                />
              ) : (
                <>
                  {/* Route (the plan panel) after the points and the ride, above the route, as a form's button follows its
                      fields (Plan streamline, Stephen 2026-10-17); on a phone with a route, where the route comes first, on top. */}
                  {/* One flat keyed list, so a change of order moves the panel rather than remounting it. */}
                  {(order[0] === "route" ? [planPanel, ...order.map((id) => sections[id])] : order.flatMap((id) => (id === "route" ? [planPanel, sections[id]] : [sections[id]])))}
                </>
              )}
            </div>

            {/* The sheets stay in the page while hidden, so the opened GPX file and the switches keep their state. */}
            <LayersSheet
              {...{
                nav: sheetNav, massMap, stress, stressVisible, setStressVisible, showHighLanes, preset, federalOn,
                setFederalOn, federalStatus, federalData, points, waterPrefs, changeWaterPrefs, waterStatus,
                rail, setRail, showMtbTrails, showTopoLines, topoReady, climbsOn, changeClimbsOn, climbsFrom, changeClimbsFrom,
                climbsStatus, climbsAlong, openLegend: (opener: HTMLElement) => openView("legend", opener, true),
                placesOn, changePlacesOn, placesStatus: placesData === "unavailable" ? PLACES_UNAVAILABLE : Array.isArray(placesData) && placesData.length === 0 ? PLACES_NONE : "",
                // Plan's alone (the brief: "not in Go"); null leaves the section out of Go's Layers.
                scenic: mode === "go" ? null : { on: scenicOn, onChange: changeScenicOn, status: scenicStatus(scenicOn, stress !== "unavailable", placesData ?? "loading") },
                permits: mode === "go" ? null : { on: permitsOn, onChange: changePermitsOn },
                bikeshare: {
                  operators: docksOperators,
                  choices: docksChoices,
                  onChange: changeDocksChoices,
                  status: bikeshareRide || docksActive ? docksStatus(docksReport.answer, docksReport.asked, docksReport.zoom, docksActive) : "",
                },
              }}
            />
            <LegendSheet
              {...{
                nav: sheetNav, legendHeadingRef, massMap, stress, stressVisible, preset, zoom, facilitiesShown, waterPrefs,
                waterStatus, climbsOn, climbsStatus, federalOn, federalStatus, rail,
                scenicOn: scenicShown(scenicOn, mode, massMap),
              }}
            />
            <SuggestSheet nav={sheetNav} roadInfoAtCentre={roadInfoAtCentre} onReview={reviewOpener} />
            <GpxSheet
              {...{
                nav: sheetNav, shown, routedPoints, routedLoop, federalRoute, points, status, imported,
                openImported: openImportedChecked, refineImported, getMap, downloadRoute, sendToGarmin: sendToGarminRoute,
                ...(mode === "go" ? {} : { downloadCourse: downloadCourseRoute }),
                // Snapping an opened track (lib/gpxMatch.ts) opens the plan along the snapped line: one edit, like the file.
                ...(mode === "go" ? {} : {
                  match: {
                    preset, trailsOff: trailsAreOff(preset, dials), assist: dials.assist === true, onMatched: openImported,
                    ...(importBase.current && !importEdited ? { exact: importBase.current.exact === true, onExact: setFollowExact } : {}),
                  },
                }),
                // Your routes, saved and kept for offline, with a search (the owner, 2026-10-18); versions in Plan only.
                routes: (
                  <YourRoutes
                    signedIn={myGoControls.signedIn}
                    kept={{ shown: keepShown || anyKept(), version: keptVersion, onOpen: openKept, onSay: announce }}
                    myRoutes={{ ...{ version: myRoutesVersion, onOpen: openSaved, onExport: exportSaved, announce, sharedLinks: mode === "plan", onSharedChange: forgetSharedLine,
                      // The saved route on screen follows a rename, and is forgotten once deleted (the next save is new).
                      onRenamed: (id: number, name: string) => {
                        openSavedRoute.current = afterRename(openSavedRoute.current, id, name);
                      },
                      onDeleted: (id: number) => {
                        openSavedRoute.current = afterDelete(openSavedRoute.current, id);
                      },
                    }, versions: mode !== "go" }}
                  />
                ),
                // Save route, then Share (the owner, 2026-10-17: "Basically you save then you share"), for the route shown
                // or the file opened.
                shareControls:
                  shown || (imported?.verbatim && !importEdited) ? (
                    <ShareControls
                      save={saveProps ? <SaveRoute {...saveProps} label={SAVE_ROUTE} /> : null}
                      canShare={canShare}
                      ready={!!shown}
                      shareRoute={(ride) => void shareRoute(ride)}
                      shareKeep={shareKeep}
                      onShareKeep={mode === "plan" ? setShareKeep : null}
                      shareSaid={shareSaid}
                      linkNote={linkNote}
                    />
                  ) : null,
              }}
            />
            <SettingsSheet
              {...{
                bigText: { on: bigText, onChange: setBigText },
                // The rider and bike weight (OWNER-DECISIONS 313-318), in Settings (the owner, 2026-10-18).
                weight: {
                  saved: weight,
                  remembered: weightRemembered,
                  split: defaultSplit(dials.carrying),
                  onSave: (next: StoredWeight, remember: boolean) => {
                    weightStore.current?.save(next, remember);
                    setWeightRemembered(remember && (weightStore.current?.remembered() ?? false));
                    setWeight(next);
                  },
                  onClear: () => {
                    weightStore.current?.clear();
                    setWeightRemembered(false);
                    setWeight(null);
                  },
                },
                nav: sheetNav, settingsHeadingRef, ridePrefs, changeRidePrefs, announce,
                linkNote, accessMode, toggleAccessMode, mode, myGo: myGoControls, menu,
                announcements: { level: announceLevel(announceChoice, mode), choose: chooseAnnounce },
                signInAvailable: me.sign_in,
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
            <RepairSheet nav={sheetNav} status={repairList?.said ?? ""} items={repairList?.items ?? null} at={new Date()} onRide={rideToRepair} />
            <PlacesSheet
              nav={sheetNav}
              go={goMode}
              status={placesStatus}
              items={placesShown}
              total={placesAll?.length ?? 0}
              onMore={() => setPlacesCount((n) => n + PLACES_PAGE)}
              filter={placesFilter}
              onFilter={(next) => {
                setPlacesFilter(next);
                setPlacesCount(PLACES_PAGE);
              }}
              canAddStop={points.length >= 2}
              onShow={showSight}
              onAddStop={addSightStop}
              onGoPick={goPickSight}
            />
            {/* Go's Edit route: Plan's points, the one copy in the page while Go shows (Plan's panel holds it otherwise). */}
            <EditRouteSheet nav={sheetNav}>{goMode && view === "points" && sections.points}</EditRouteSheet>
            <RideSheet nav={sheetNav}>
              <RideGroupChips preset={preset} onPick={pickRide} open={view === "ride"} />
              {/* Go's Ride sheet holds the Ride line and its dials; in Plan they are in the panel (one copy in the page). */}
              {goMode && sections.presets}
              {/* Start from here (the owner, 2026-10-16: "You should be able to make changes then start from the edit
                  default"): the route the sheet's changes planned, ridden at once; the changes are saved as they are
                  made. The same Start as the route panel's, closing the sheet first. */}
              {goMode && shown && !stale && !riding && rideableRoute(shown) && (
                <div className="actions ride-sheet-start">
                  <button
                    type="button"
                    className="start-button"
                    onClick={() => {
                      showPlanner(false);
                      startRideChecked();
                    }}
                  >
                    <Icon name="play" />
                    Start ride
                  </button>
                </div>
              )}
            </RideSheet>
          </div>

          {!goMode && <BottomBar view={view} onOpen={openSheet} buttonRef={(id, button) => (barButtons.current[id] = button)} />}
        </div>
      </aside>
    </div>
  );
}
