/**
 * Ride mode (WEB-NAV-plan.md; OWNER-DECISIONS 255, 434, 465): follow a planned route on a phone with the
 * screen on and the page in front. The engine is lib/navigate.ts; the outputs, the throttle and the wake
 * lock are lib/rideOutput.ts; the one position watch is lib/rideWatch.ts. This component wires them to
 * the screen:
 *
 * - The cue card: the next turn, flagged junction or stop, its distance (US units first, metric in
 *   brackets) and the API's sentence for it. Not a live region: it changes with every fix.
 * - To go: distance, time and arrival clock time to the next stop and to the end, at the rider's pace against the route's (lib/arrival.ts).
 * - Two live regions of its own, polite for advance cues and assertive for "now", leaving the route
 *   and arrival; each repeats the count trick so the same sentence twice is said twice. A cue never
 *   moves the focus.
 * - Where am I? (a button, and the W or C key): said on demand, outside the throttle; it re-centres the map too (the two
 *   buttons merged, the owner, 2026-10-20).
 * - Off route: re-planned automatically after the gate (plan Q5), or "Keep the planned route", which
 *   shows the way back. A fixed route (`fixed`: a link shared as a ride, or a Mass Ride or Group Ride not shared as a route)
 *   is never re-planned on its own: everyone on it stays on the same line, and the way back is shown instead. A re-plan never touches the plan in the address bar (plan Q2): it is the ride's
 *   own route, held here and in App's ride state only.
 * - Large text (the owner, 2026-10-20; it replaced Big text): the card half the screen, the turn as big as fits, the map
 *   below; its side button (and the T key) and Settings' switch are the one choice; heading-up (track-up by default since v0.7.0); and
 *   Road closed ahead and End ride always in view at the top of the card (since v0.9.0; the Settings bubble beside More,
 *   the last side button, opens the ride's settings under that row), with Undo after End ride. End ride part way leaves the plan starting where the rider is.
 * - The map along the route, kept for dead spots (lib/corridor.ts, N5), and Log for 311 with the place in
 *   the route's street names (lib/report311.ts, lib/report311Log.ts; N6; OWNER-DECISIONS 369, 465).
 * - The side buttons (the owner, 2026-10-17: "Remove that bottom part when routing by default. instead put
 *   these as circle icons on the side"): Where am I? (re-centring too), Large text, Broadcast (2026-10-24: "Let people
 *   broadcast from a ride"), Detour (water, restroom, food, repair or a search, lib/detourSearch.ts), on a share bike the dock button with the time undocked
 *   (lib/rideDock.ts), 311 anywhere on the route, and More; each a round icon with its name for screen readers, its menu
 *   opening beside it. More opens a row of bubbles beside it (2026-10-26: "just expanded as more bubble buttons, not in
 *   settings"): the route's changes (Less traffic and Fewer hills, one step down the traffic or hills slider and a new
 *   route from here, lib/rideEase.ts; Skip this stop, lib/rideStops.ts), Topo lines on or off (lib/topoLines.ts) and
 *   Settings, the ride's settings opening under the top row. The bottom panel shows only when it
 *   has something to say or ask: GPS and screen notes, off route, Ride the rest.
 *   Answers asked for (Where am I?, a detour's progress) show for a few seconds by the buttons.
 *
 * Privacy (plan section 7): positions stay in memory for the ride; nothing is stored or logged; the only
 * ones sent are a re-plan's start point and, when the rider asks for the nearest water or restroom, the
 * search's own (POST /api/nearest), each in a POST body, as planning with "Use my location" sends it.
 */
import { BROADCAST_HOLD_HINT } from "./lib/broadcastQr.ts";
import { useHold } from "./lib/useHold.ts";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type FocusEvent, type PointerEvent } from "react";
import { HoldTimer } from "./lib/holdTimer.ts";
import { rejoinsFirst, startsWayBack, wayBackRoute } from "./lib/rejoin.ts";
import {
  ON_DETOUR_SAID,
  ON_STANDARD_SAID,
  ROAD_CLOSED_FINDING,
  ROAD_CLOSED_NAME,
  ROAD_CLOSED_TEXT,
  ROAD_CLOSED_NO_PLACE,
  closedAhead,
  onOtherLine,
  withClosed,
} from "./lib/roadClosed.ts";
import { requestRoute, type ErrorKind, type RouteResponse } from "./lib/api.ts";
import { VIA_MARKS, drawnLegs, stopNames, viaIndices, type RideStopMark } from "./lib/pointKinds.ts";
import {
  SKIP_STOP,
  detourButtonName,
  insteadLabel,
  insteadName,
  insteadSaid,
  skipStopName,
  restartKept,
  restartReplanSaid,
  restartSaid,
  restartStops,
  restartUnchanged,
  skippingSaid,
  withoutStop,
  type RestartStop,
} from "./lib/rideStops.ts";
import { RestartStopsDialog } from "./RestartStopsDialog.tsx";
import { keepLeftRide } from "./lib/rideResume.ts";
import type { Dials } from "./lib/dials.ts";
import { haversineM, type LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import { formatDistance, formatDuration, spokenDistance } from "./lib/format.ts";
import { arrivalClock, atPace, paceFactor, paceStart, paceStep, type PaceTrack } from "./lib/arrival.ts";
import { cueParts } from "./lib/cueShown.ts";
import { jogArrowPath } from "./lib/jogArrow.ts";
import { rideLightCorner } from "./lib/lightTimes.ts";
import { LOCATE_MESSAGES } from "./lib/geolocation.ts";
import {
  POOR_FIX_M,
  GPS_WEAK_SAID,
  weighFix,
  CUE_SHEET_SAID,
  cueSheet,
  cueSheetAfterMs,
  cueSheetShown,
  CUE_SHEET_CHECK_MS,
  type GpsWeakness,
  REPLAN_FAILED,
  REPLAN_FOUND,
  REPLAN_NO_AHEAD,
  UTURN_START,
  type UTurnState,
  uturnAheadOnly,
  isStartUTurn,
  uturnStep,
  setsOffBack,
  withUTurn,
  REPLAN_NO_SIGNAL,
  REPLAN_REJOIN,
  REPLAN_REJOIN_AHEAD,
  REPLAN_FINDING,
  REPLAN_STILL_WAITING,
  ReplanGate,
  VERBOSITY_LABELS,
  crossArrow,
  nextAction,
  planAfterEnd,
  replanKept,
  skippableVia,
  viaSkipWorth,
  viaSkippedNote,
  replanTold,
  rideModel,
  secondsBetween,
  startState,
  stopsAhead,
  toGo,
  wayBack,
  whereAmI,
  whereAmIShown,
  arrivedShown,
  snap,
  CUE_SHEET_SHOWN,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./lib/navigate.ts";
import { statsPause, statsStart, statsStep, type RideStats } from "./lib/rideStats.ts";
import {
  Announcer,
  OUTPUT_LABELS,
  RIDE_TEXT_BUTTON,
  ScreenWake,
  Voice,
  phoneKind,
  toScreenReader,
  toVoice,
  wakeSaid as wakeWords,
  type CueOutput,
  type RidePrefs,
  type RideTextSize,
  type Said,
} from "./lib/rideOutput.ts";
import { ScreenSleepNote } from "./ScreenSleepNote.tsx";
import { useRailFit } from "./lib/railFit.ts";
import { WAITING_FOR_GPS, watchRide, type RideGeoEnv } from "./lib/rideWatch.ts";
import { askCompass } from "./lib/compassHeading.ts";
import { rideGeoEnv, rideSpeech, rideWake, ridesHidden, showCue, speaksAloud } from "./lib/nativeShell.ts";
import {
  DETOUR_BUSY,
  DETOUR_FULL,
  DETOUR_HELP,
  NO_FIX_YET,
  STILL_SEARCHING,
  detourPoints,
  detourRowShown,
  nearbyText,
  requestNearest,
  type Nearby,
} from "./lib/nearest.ts";
import {
  DETOUR_CHOICES,
  DETOUR_SEARCH_BUTTON,
  DETOUR_SEARCH_HINT,
  DETOUR_SEARCH_LABEL,
  DETOUR_SUMMARY,
  detourFindingSaid,
  findDetour as searchDetour,
  type DetourAsk,
  type DetourDeps,
  type DetourFound,
  type DetourKind,
} from "./lib/detourSearch.ts";
import type { FoodPlace } from "./lib/food.ts";
import type { RepairPlace } from "./lib/repair.ts";
import type { WaterPoint } from "./lib/waterRestrooms.ts";
import type { TrailMiles } from "./lib/trailMiles.ts";
import { WATER_CAUTION } from "./lib/waterRestrooms.ts";
import { corridorWorry, type PrefetchResult } from "./lib/corridor.ts";
import { clearCorridor, copyCorridor, keepCorridor } from "./lib/corridorStore.ts";
import { lastRideAdopter } from "./lib/offlineKeep.ts";
import { blockOf, rescueRideFocus, type RideBlock } from "./lib/rideFocus.ts";
import { REPORT_SENT, report311Enabled, sendReport311, reportPlace, type ReportKind } from "./lib/report311.ts";
import { entryText, kindLabel, report311Log, type LogEntry } from "./lib/report311Log.ts";
import { RIDE_311_NAME, RIDE_311_TEXT, Ride311Menu, ride311Shown } from "./lib/ride311.ts";
import {
  DOCKED_SHOWN,
  DOCK_NAME,
  DOCK_WAYS,
  LEFT_DOCK_M,
  RESTART_TIME,
  TIME_RESTARTED,
  dockAt,
  dockButtonName,
  dockedSaid,
  docksAround,
  dockFinding,
  fetchDocks,
  findDock,
  CHOSEN_STILL_MS,
  DOCKED_M,
  stillAtLength,
  stillStep,
  undockedMinutes,
  undockedShown,
  undockedWarning,
  warningDue,
  type DockWay,
  type Still,
} from "./lib/rideDock.ts";
import { Icon } from "./Icon.tsx";
import { TOPO_LINES_LABEL, setTopoLines, topoArchive, useTopoLines } from "./lib/topoLines.ts";
import { TOPO_LINES_ROW_UNAVAILABLE } from "./lib/terrainSection.ts";
import { DepartureTimer } from "./DepartureTimer.tsx";
import { NextVehicleLine } from "./NextVehicleLine.tsx";
import type { VehicleMark } from "./lib/nextVehicle.ts";
import { SettingRow, SettingSelect } from "./SettingRow.tsx";
import { shortLabel } from "./lib/shortLabel.ts";
import { EASE_AT_END, EASE_NAME, EASE_SAME, EASE_SHOWN, easeFinding, eased, sameLine, type Ease } from "./lib/rideEase.ts";
import { RING, junctionPaths, ringPaths, type JunctionShape } from "./lib/junctionShape.ts";
import { NOTHING_DISMISSED, RIDE_WEATHER_MS, alertKey, alertSaid, alertUrgent, dismissWeather, newAlerts, rainLine, rainSays, rainStage, weatherPoints, weatherToShow } from "./lib/weather.ts";
import { useWeather } from "./useWeather.ts";
import { WeatherLines } from "./WeatherLines.tsx";
import {
  RIDE_REST,
  RIDE_REST_FINDING,
  RIDE_REST_HINT,
  approachWords,
  restFrom,
  restNear,
  restReadySaid,
  tripRideStart,
  tripStep,
  type RideTrip,
} from "./lib/rideTrip.ts";
import { t } from "./lib/i18n.ts";
import { countText } from "./lib/rideGroup.ts";

/**
 * One voice for the page: the Start ride press unlocks it (iOS speaks only after a gesture has). Web
 * Speech in a browser; in the phone app (v0.8.0), the native voice, which goes on with the screen locked.
 */
export const rideVoice = new Voice(rideSpeech());

/** Said as the ride starts, inside the Start press, so the voice is unlocked by it. */
export const RIDE_STARTED = t("Ride started.");
/** How long after the start its note (startNote) is said: after "Ride started.". */
export const START_NOTE_MS = 1_500;
/** The always-visible End ride button's words (the owner, 2026-10-16: "add a method of ending navigation"). */
export const END_RIDE_NAME = t("End ride");
/** The least a long instruction shrinks to at normal text, from its own size (styles.css .cue-text, 1.5rem). */
const CUE_TEXT_MIN_PX = 16;
/** Its words once arrived, filled (the UI review, 2026-10-28); the name goes on with End ride. */
export const RIDE_DONE_TEXT = t("Done");
/**
 * ", 8 min · 6:42 AM" after a distance to go: the minutes and the clock time of arrival (the owner, 2026-10-26: "Add
 * estimated clock time of arrival to the ride." and "Stops too"). "about" and "arriving about" are for screen readers
 * only: fewer words on screen (the owner, 2026-10-20), every word for speech, and still an estimate.
 */
function TimeToGo({ seconds, nowMs }: { seconds: number; nowMs: number }) {
  return (
    <>
      , <span className="visually-hidden">{t("about")} </span>
      {formatDuration(seconds)}
      <span aria-hidden="true"> · </span>
      <span className="visually-hidden">{t(", arriving about")} </span>
      <span className="ride-arrive">{arrivalClock(nowMs, seconds)}</span>
    </>
  );
}

/** End ride is a slide to end until the rider has arrived (the owner, 2026-10-19: "Add a swipe confirmation on ending the ride unless at the destination"). */
export const SLIDE_TO_END = t("Move it to the end to end the ride");
/** The keys that move a range: only these count as a step of End ride's slide. */
const SLIDE_KEYS = new Set(["ArrowRight", "ArrowUp", "ArrowLeft", "ArrowDown", "PageUp", "PageDown", "Home", "End"]);
/** End ride's slide left part way goes back after this long. */
const SLIDE_BACK_MS = 4_000;
/** Said and shown when End ride is tapped rather than slid. */
export const SLIDE_TO_END_HINT = t("Slide it to the right to end the ride.");
/** The words on End ride's slide (and End roam's): what to do, its name for screen readers keeping what it ends. */
export const SLIDE_TO_END_LABEL = t("Slide to end");
/**
 * The last side button opens these, under the top row (the owner, 2026-10-16: "the buttons to change the settings seem
 * hidden"; a gear in the rack since v0.9.0): since 2026-10-24 More, the route's changes above the settings (Stephen:
 * "put options like skip a stop, lower traffic and hills in an expansion with settings").
 */
export const RIDE_SETTINGS_TEXT = t("More");
/** The words under Less traffic and Fewer hills in More (the UI review, 2026-10-28); their names stay EASE_NAME. */
export const EASE_WORD: Record<Ease, string> = { calmer: t("Calmer"), flatter: t("Flatter") };
export const RIDE_MORE_NAME = t("More: change the route or the map, and ride settings");
/** Topo lines from More (Stephen 2026-10-26: "In the ... section allow topo lines to be toggled on and off during a ride"): Map layers' own switch (lib/topoLines.ts). */
export const RIDE_TOPO_ON = `${TOPO_LINES_LABEL} on.`;
export const RIDE_TOPO_OFF = `${TOPO_LINES_LABEL} off.`;
export const RIDE_TOPO_OFFLINE = `${TOPO_LINES_LABEL} need a connection. Try again once you have signal.`;
export const RIDE_SETTINGS_TITLE = t("Ride settings");
export const RIDE_CHANGE_TITLE = t("Change the route");
/** Broadcast on the ride screen (Stephen 2026-10-24: "Let people broadcast from a ride"): Plan's and Go's Broadcast, the ride already going. */
export const RIDE_BROADCAST_NAME = t("Broadcast");
/** More > Riders: the riders panel, its count now on Broadcast. */
export const RIDERS_NAME = t("Riders");
/** What End ride leaves behind (lib/navigate.ts planAfterEnd): the plan from here, or as it was. */
export type EndedPlan = ReturnType<typeof planAfterEnd>;
/** How long the 311 line ("Logged for 311: Pothole.") stays (review F4); held the same way. */
export const SAID_311_MS = 8_000;
/** Said when a 311 pick has no place on the route yet. */
export const NO_PLACE_311 = t("Your place on the route is not known yet, so nothing was logged.");
/** Said when a problem is logged: "Logged for 311: Pothole." */
export function loggedSaid(entry: LogEntry): string {
  return t("Logged for 311: {kind}.", { kind: kindLabel(entry.kind) });
}
/** Said as the ride ends, by the voice and the page's polite region; the figures are on the summary card. */
export const RIDE_ENDED_SAID = t("Ride ended.");
/** Shown and said with the ride's summary in Plan where End ride came part way (lib/navigate.ts planAfterEnd): the plan now starts where the rider is. */
export const RIDE_ENDED_FROM_HERE_NOTE = t("The route now starts where you are.");
/** Part way in Plan with no recent location: the plan keeps its start, and the rider is told. */
export const RIDE_ENDED_NO_FIX_NOTE = t("Route start unchanged.");

/**
 * A short-lived message's timer (lib/holdTimer.ts) with the handlers that hold it: while the focus is inside, or a
 * mouse is over it (a touch's emulated hover is not a hover: it would hold the message until the next tap).
 */
function useHoldTimer(ms: number, onDone: () => void) {
  const done = useRef(onDone);
  done.current = onDone;
  const timer = useRef<HoldTimer | null>(null);
  if (timer.current === null) timer.current = new HoldTimer(ms, () => done.current());
  useEffect(() => () => timer.current?.stop(), []);
  const hold = useMemo(
    () => ({
      onFocus: () => timer.current?.focus(true),
      onBlur: (event: FocusEvent<HTMLElement>) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) timer.current?.focus(false);
      },
      onPointerEnter: (event: PointerEvent<HTMLElement>) => {
        if (event.pointerType === "mouse") timer.current?.hover(true);
      },
      onPointerLeave: (event: PointerEvent<HTMLElement>) => {
        if (event.pointerType === "mouse") timer.current?.hover(false);
      },
    }),
    [],
  );
  return { timer: timer.current, hold };
}
/** Hidden this long, the watch stops (privacy and battery) and the ride offers Resume (plan section 5). */
export const HIDDEN_STOP_MS = 10 * 60_000;
export const PAUSED_SAID = t("Ride paused while the page was in the background. Press Resume to carry on.");
/** A re-plan that has not answered in this long is said as no signal (a hung connection); its answer still counts. */
export const REPLAN_TIMEOUT_MS = 25_000;
/** No fix for this long and a failure from the watch: the rider is told (once) that GPS is lost. */
export const GPS_LOST_MS = 30_000;
export const GPS_LOST_SAID = t("No GPS signal: the cues are paused until it comes back.");

/** The rider's responsibility and the battery, in the ride's settings (plan sections 5 and 10). */
export const RIDE_SAFETY_BROWSER =
  t("Ride mode guides you along the planned route; you stay responsible for riding safely and obeying the rules of the road, and the route can be wrong. It needs the screen on and this page in front, and GPS with a lit screen drains the battery quickly.");
/** In the phone app (v0.8.0) the cues go on with the screen locked, so the screen sentence is not said. */
export const RIDE_SAFETY_APP =
  t("Ride mode guides you along the planned route; you stay responsible for riding safely and obeying the rules of the road, and the route can be wrong. In this app the cues go on with the screen locked until you end the ride, and GPS drains the battery.");
export const RIDE_SAFETY = ridesHidden() ? RIDE_SAFETY_APP : RIDE_SAFETY_BROWSER;
/** Its first point, the one shown in the ride's settings; the rest is under "About Ride mode". */
export const RIDE_SAFETY_SHORT = t("You ride at your own risk; the route can be wrong.");

/** Called inside the Start ride press: unlock the voice with the first sentence, where the rider chose it. */
export function startRideGesture(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(RIDE_STARTED);
  // iPhones give the compass for the map's first heading only once allowed, asked inside this press (lib/compassHeading.ts).
  askCompass();
}

/** Start's press, before its closure check: unlocks the voice silently (iOS speaks only after a
 * gesture has spoken once), so "Ride started." is said only when the ride does start. */
export function primeRideVoice(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(" ");
  askCompass();
}

export const VOICE_ON = t("Voice on.");

/** Called inside the press that changes the ride's outputs: a voice newly chosen is unlocked there (iOS). */
export function voiceTurnedOn(before: RidePrefs, next: RidePrefs, voice: Pick<Voice, "unlock"> = rideVoice): void {
  if (!toVoice(before.output) && toVoice(next.output)) voice.unlock(VOICE_ON);
}

/** Said politely when Start's closure check takes more than a moment (CLOSURE_SLOW_MS). */
export const CHECKING_CLOSURES = t("Checking closures…");
export const CLOSURE_SLOW_MS = 600;

/** What App shows on the map for the ride. */
export interface RideView {
  route: RouteResponse;
  /** The other line (v0.8.2): the standard way through a marked closure, or its detour while on the standard way. */
  other?: LonLat[] | null;
  rider: { point: LonLat; headingDeg: number | null; accuracyM: number } | null;
  /** Where the next train or bus is while the rider waits at a Metro or Metrobus boarding (v0.9.0). */
  vehicle?: VehicleMark | null;
  /** The stops still ahead, drawn on the ride's map with their names (2026-10-24). */
  stops?: RideStopMark[];
}

function arrowFor(
  cue: Cue | null,
): "left" | "right" | "bear_left" | "bear_right" | "uturn" | "straight" | "stop" | "end" | "warn" | NonNullable<ReturnType<typeof crossArrow>> {
  if (!cue) return "straight";
  if (cue.kind === "end") return "end";
  if (cue.kind === "stop") return "stop";
  // Across a road, then the turn (lib/navigate.ts crossArrow).
  const across = crossArrow(cue);
  if (across) return across;
  if (cue.movement) return cue.movement;
  if (cue.kind === "hazard" || cue.kind === "walk") return "warn";
  return "straight";
}

/**
 * The card's shape for the cue: an arrow, a stop or a finish mark, a warning sign. A shape, never colour alone. A
 * turn at an unusual junction (v0.10.0; lib/junctionShape.ts) is drawn as the junction: the way taken solid with
 * its arrowhead, the other ways dashed.
 */
function CueShape({ shape, junction, exit, jog }: { shape: ReturnType<typeof arrowFor>; junction?: JunctionShape; exit?: number; jog?: string | null }) {
  if (junction?.ring && exit && shape !== "uturn" && shape !== "stop" && shape !== "end" && shape !== "warn") {
    // A circle: the ring with the exit's number in it, the way round solid, the exits passed dashed.
    const drawn = ringPaths(junction);
    return (
      <svg className="cue-shape cue-junction" viewBox="0 0 48 56" aria-hidden="true" focusable="false">
        <path d={drawn.ring} fill="none" stroke="currentColor" strokeWidth="1.5" />
        {drawn.others.map((d) => (
          <path key={d} d={d} fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="4 2.5" strokeLinecap="butt" />
        ))}
        <path d={drawn.route} fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        <text x={RING.x} y={RING.y} textAnchor="middle" dominantBaseline="central" fontSize="12" fontWeight="700" fill="currentColor">
          {exit}
        </text>
      </svg>
    );
  }
  // Turns in quick succession (lib/jogArrow.ts): one arrow through them all, in place of the first turn's junction.
  if (jog) {
    return (
      <svg className="cue-shape cue-jog" viewBox="0 0 48 56" aria-hidden="true" focusable="false">
        <path d={jog} fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (junction && shape !== "uturn" && shape !== "stop" && shape !== "end" && shape !== "warn") {
    const drawn = junctionPaths(junction);
    return (
      <svg className="cue-shape cue-junction" viewBox="0 0 48 56" aria-hidden="true" focusable="false">
        {drawn.main ? <path d={drawn.main} fill="none" stroke="currentColor" strokeWidth="1.5" /> : null}
        {drawn.others.map((d) => (
          <path key={d} d={d} fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="4 4" strokeLinecap="butt" />
        ))}
        <path d={drawn.route} fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  const paths: Record<typeof shape, string> = {
    left: "M30 52 V28 H14 M22 18 L12 28 L22 38",
    right: "M18 52 V28 H34 M26 18 L36 28 L26 38",
    bear_left: "M30 52 V30 L14 14 M14 26 V14 H26",
    bear_right: "M18 52 V30 L34 14 M22 14 H34 V26",
    uturn: "M32 52 V22 A10 10 0 0 0 12 22 V38 M4 30 L12 40 L20 30",
    straight: "M24 52 V10 M14 20 L24 10 L34 20",
    // Across the road drawn between ROAD_EDGES, then the turn on its far side.
    cross: "M24 52 V10 M14 20 L24 10 L34 20",
    cross_left: "M32 52 V12 H10 M18 4 L10 12 L18 20",
    cross_right: "M16 52 V12 H38 M30 4 L38 12 L30 20",
    stop: "M14 10 V52 M14 12 H38 L32 20 L38 28 H14",
    end: "M14 10 V52 M14 12 H38 V28 H14 M26 12 V28 M14 20 H38",
    warn: "M24 8 L44 46 H4 Z M24 20 V32 M24 38 V40",
  };
  const across = shape === "cross" || shape === "cross_left" || shape === "cross_right";
  return (
    <svg className="cue-shape" viewBox="0 0 48 56" aria-hidden="true" focusable="false">
      {across ? <path d={ROAD_EDGES} fill="none" stroke="currentColor" strokeWidth="1.5" /> : null}
      <path d={paths[shape]} fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The road a "cross" arrow goes over: its two edges, thin, across the arrow's stem below the turn. */
const ROAD_EDGES = "M4 26 H44 M4 40 H44";

/**
 * End ride as a slide (the owner, 2026-10-19), so a bump while riding does not end it: a range from 0 to
 * 100 in quarters, the ride ended when it reaches the end. A native range, so the keyboard's arrows and a
 * screen reader's adjust gestures move it too. A tap on the track that jumps it half way or more is a tap,
 * not a slide: it springs back and says how. Let go short of the end, or left part way, it springs back; let go
 * by a finger or a mouse, it says how too, so a tap anywhere on it (the thumb, or the track short of half way) is
 * answered (the audit's P14: a tap in the middle did nothing). The words on it say what to do, "Slide to end ››";
 * its name keeps what it ends ("End ride: slide to end").
 */
export function SlideToEnd({ onEnd, onTap, name = END_RIDE_NAME }: { onEnd: () => void; onTap: () => void; name?: string }) {
  const [value, setValue] = useState(0);
  const last = useRef(0);
  const key = useRef(false);
  // Said already for this press (a jump), so letting go does not say it again.
  const told = useRef(false);
  const back = () => {
    key.current = false;
    last.current = 0;
    setValue(0);
  };
  // Left part way (a screen reader's adjust gestures move it without the focus, so no blur comes): back after a few seconds.
  useEffect(() => {
    if (value === 0 || value >= 100) return;
    const timer = window.setTimeout(back, SLIDE_BACK_MS);
    return () => window.clearTimeout(timer);
  }, [value]);
  return (
    <div className="ride-end ride-slide">
      <span className="ride-slide-text" aria-hidden="true">
        {SLIDE_TO_END_LABEL}
        <span className="ride-slide-arrows">››</span>
      </span>
      <input
        type="range"
        className="ride-slide-range"
        min={0}
        max={100}
        step={25}
        value={value}
        aria-label={t("{name}: slide to end", { name })}
        aria-valuetext={value === 0 ? SLIDE_TO_END : `${value}%`}
        onKeyDown={(event) => {
          // Only the keys that move a range count as a step, so a stray key never lets a tap through.
          key.current = SLIDE_KEYS.has(event.key);
        }}
        onPointerDown={() => {
          key.current = false;
          told.current = false;
        }}
        onChange={(event) => {
          const next = Number(event.currentTarget.value);
          const byKey = key.current;
          key.current = false;
          if (!byKey && next - last.current >= 50) {
            back();
            told.current = true;
            onTap();
            return;
          }
          last.current = next;
          setValue(next);
          if (next >= 100) onEnd();
        }}
        onPointerUp={() => {
          if (last.current >= 100) return;
          back();
          if (!told.current) onTap();
          told.current = true;
        }}
        onPointerCancel={back}
        onBlur={() => {
          if (last.current < 100) back();
        }}
      />
    </div>
  );
}

/** A live region that says the same sentence twice when it is set twice (App's count trick). */
export function LiveRegion({ said, urgent }: { said: { text: string; count: number }; urgent: boolean }) {
  return (
    <p className="visually-hidden" role={urgent ? "alert" : "status"} aria-live={urgent ? "assertive" : "polite"}>
      {said.text}
      {said.count % 2 === 1 ? " " : ""}
    </p>
  );
}

export function RideSettingsFields({
  prefs,
  onChange,
  idBase,
  compact = false,
}: {
  prefs: RidePrefs;
  onChange: (prefs: RidePrefs) => void;
  idBase: string;
  /** Settings: two pickers, with what each level says behind an (i); the ride's own settings keep the radios. */
  compact?: boolean;
}) {
  if (compact) {
    const levels = Object.keys(VERBOSITY_LABELS) as Verbosity[];
    return (
      <>
        <SettingRow infoId={`${idBase}-output-info`} about="say cues with">
          <SettingSelect
            label={t("Say cues with")}
            value={prefs.output}
            options={(Object.keys(OUTPUT_LABELS) as CueOutput[]).map((output) => [output, OUTPUT_LABELS[output]] as const)}
            onChange={(output) => onChange({ ...prefs, output, chosen: true })}
          />
        </SettingRow>
        <SettingRow
          infoId={`${idBase}-level-info`}
          about="how much to say"
          info={
            <ul className="setting-info-list">
              {levels.map((level) => (
                <li key={level}>{VERBOSITY_LABELS[level]}</li>
              ))}
            </ul>
          }
        >
          <SettingSelect
            label={t("How much to say")}
            value={prefs.verbosity}
            options={levels.map((level) => [level, shortLabel(VERBOSITY_LABELS[level])] as const)}
            onChange={(verbosity) => onChange({ ...prefs, verbosity, chosen: true })}
            describedBy={`${idBase}-level-info`}
          />
        </SettingRow>
      </>
    );
  }
  return (
    <>
      <fieldset className="ride-choice">
        <legend>{t("Say cues with")}</legend>
        {(Object.keys(OUTPUT_LABELS) as CueOutput[]).map((output) => (
          <label key={output} className="radio">
            <input
              type="radio"
              name={`${idBase}-output`}
              checked={prefs.output === output}
              onChange={() => onChange({ ...prefs, output, chosen: true })}
            />
            {OUTPUT_LABELS[output]}
          </label>
        ))}
      </fieldset>
      <fieldset className="ride-choice">
        <legend>{t("How much to say")}</legend>
        {(Object.keys(VERBOSITY_LABELS) as Verbosity[]).map((level) => (
          <label key={level} className="radio">
            <input
              type="radio"
              name={`${idBase}-level`}
              checked={prefs.verbosity === level}
              onChange={() => onChange({ ...prefs, verbosity: level, chosen: true })}
            />
            {VERBOSITY_LABELS[level]}
          </label>
        ))}
      </fieldset>
    </>
  );
}

/** The way back to the planned route, said: "The planned route is 300 feet to the left." */
/** Said off a fixed route, before the way back: it is not re-routed (the review of #191). */
export const FIXED_SAID = t("This ride stays on its route, never re-routed.");

function wayBackSaid(back: { metres: number; direction: string }): string {
  return t("The planned route is {distance} to the {direction}.", { distance: spokenDistance(back.metres), direction: back.direction });
}

/** No food, repair or place search given (a test's ride): those detours say they are unavailable. */
const noPlaces = async () => null;
const noSearch: DetourDeps["geocode"] = async () => ({ ok: false, status: 0 });

export function RideMode({
  route: plannedRoute,
  points: plannedPoints,
  loop: plannedLoop,
  preset,
  dials,
  prefs,
  onPrefs,
  follow,
  onFollow,
  headingUp,
  onHeadingUp,
  textSize,
  onTextSize,
  onView,
  onEnd,
  resumeStats = null,
  water,
  food = noPlaces,
  repair = noPlaces,
  geocode = noSearch,
  stopName,
  trailMiles = null,
  geoEnv,
  keepLastRide = false,
  trip = null,
  onRideRest,
  fixed = false,
  onBroadcast = null,
  onBroadcastHold = null,
  passingOn = false,
  broadcasting = false,
  riders = null,
  onRiders = null,
  keepLeft = false,
  startNote = "",
}: {
  route: RouteResponse;
  /** The points the route was planned with, and whether it is a loop: what a re-plan builds on. */
  points: LonLat[];
  loop: boolean;
  preset: PresetId;
  dials: Dials;
  prefs: RidePrefs;
  onPrefs: (prefs: RidePrefs) => void;
  follow: boolean;
  onFollow: (on: boolean) => void;
  headingUp: boolean;
  onHeadingUp: (on: boolean) => void;
  /** Normal, or Large (the card half the screen, the turn as big as fits); kept by App, also in Settings. */
  textSize: RideTextSize;
  onTextSize: (size: RideTextSize) => void;
  /** The ride's route and the rider's position, for the map. */
  onView: (view: RideView) => void;
  /** End ride: with the plan the ride leaves (part way, from here; lib/navigate.ts planAfterEnd) and the ride's figures. */
  onEnd: (after: EndedPlan, stats: RideStats) => void;
  /** Undo after End ride: the ended ride's figures, to carry on from. */
  resumeStats?: RideStats | null;
  /** The water layer's points, loaded if they are not yet (App's ensureWater); for the detours. */
  water?: () => Promise<WaterPoint[] | null>;
  /** Find food's places, loaded if they are not yet (App's ensureFood); for the detours (Stephen 2026-10-24). */
  food?: () => Promise<FoodPlace[] | null>;
  /** The repair stands and bike shops, loaded if they are not yet; for the detours. */
  repair?: () => Promise<RepairPlace[] | null>;
  /** The place search, through the page's one geocoding gate; for Detour's search box. */
  geocode?: DetourDeps["geocode"];
  /** A stop's name to show and say: its own (lib/pointKinds.ts), else the map's name for the spot. */
  stopName?: (point: LonLat) => string | undefined;
  /**
   * The trail mile markers (lib/trailMiles.ts; OWNER-DECISIONS 465), once App has them: the 311 report and
   * "Where am I?" name a trail's mile with them, on the device. Null before, or with none.
   */
  trailMiles?: TrailMiles | null;
  geoEnv?: RideGeoEnv;
  /**
   * The installed app (OWNER-DECISIONS 465a; lib/offlineKeep.ts): at End ride the map the ride kept is
   * handed to the last ride's kept route before it is cleared. Read once, at Start ride.
   */
  keepLastRide?: boolean;
  /**
   * A Bikeshare or transit plan's riding leg (lib/rideTrip.ts): the walk to the first dock said until the
   * rider reaches it (never "off route"), and the dock or the boarding said at the end. Null otherwise.
   */
  trip?: RideTrip | null;
  /** Ride the rest: plans the trip's last riding leg from `here` and starts it; else the words to say why not. */
  onRideRest?: (here: LonLat | null) => Promise<string | null>;
  /**
   * The route everyone shares (the owner, 2026-10-18: "For sharing mass rides and group rides, rerouting defeats the
   * purpose. It should be fixed as everyone is using the same route"): off route, it is kept as Keep the planned route
   * keeps it, with the way back said and shown, never re-planned unless the rider presses Re-plan from here or Road
   * closed ahead. Read once, at Start ride.
   */
  fixed?: boolean;
  /**
   * Broadcast from the ride (Stephen 2026-10-24: "Let people broadcast from a ride"): the share sheet with Share ride's
   * link, the rider its leader; answers what to say. Null where the ride cannot be shared as a ride (a ride opened from
   * someone else's link that is not their broadcast, Ride the rest). Following a broadcast, it passes its link on.
   */
  onBroadcast?: (() => Promise<string>) | null;
  /** Broadcast held (or right-clicked): its link as a QR code (lib/broadcastQr.ts); answers what to say. */
  onBroadcastHold?: (() => Promise<string>) | null;
  /** Following someone's broadcast: Broadcast passes their link on (they stay its leader). */
  passingOn?: boolean;
  /** This ride is broadcast, led by this rider: Broadcast shows on, and a press shares the same link again. */
  broadcasting?: boolean;
  /**
   * How many are on this broadcast, the leader included (RideGroup's count), shown in Broadcast itself (Stephen
   * 2026-10-27: "the number of riders under the broadcast button and include the leader", "Make it part of the
   * broadcast button"). Null: no broadcast to count.
   */
  riders?: number | null;
  /** More > Riders: the riders panel (who is where, Show me as a dot, your role). */
  onRiders?: (() => void) | null;
  /** The ride is kept on this device to resume (lib/rideResume.ts): each new route is kept in its place. */
  keepLeft?: boolean;
  /** Said once, as an answer, just after the ride starts: Broadcast's link copied where there was no share sheet. */
  startNote?: string;
}) {
  const [route, setRoute] = useState(plannedRoute);
  const routeRef = useRef(route);
  // The rider's route has ridden a dirt trail on a ride type that skips them (the owner, 2026-10-21: "If someone
  // goes onto a dirt trail, any reroutes should include dirt"): every re-plan of the ride may ride any dirt trail.
  const dirtRidden = useRef(Boolean(plannedRoute.dirt_trails));
  // Road closed on a dirt trail (the owner, 2026-10-21: "assume that means bad riding conditions until it's opted
  // back in"): no re-plan of the ride rides one, even once that stretch has dropped out of the ones sent.
  const dirtClosed = useRef(false);
  routeRef.current = route;
  // The dials every re-plan and detour of this ride asks with: the plan's at first, then a step calmer or flatter
  // for each Calmer or Flatter press that found a route (lib/rideEase.ts); Plan's own sliders are left as they were.
  const dialsRef = useRef(dials);
  // A Calmer or Flatter press under way: its re-plan's ticket, the route before it, and how it came out.
  const easing = useRef<{ which: Ease; ticket: number; before: RouteResponse; outcome: "pending" | "found" | "rejoin" } | null>(null);
  // What a re-plan builds on: the plan's points at first, then the last re-plan's (never a loop: its end is sent).
  const plan = useRef({ points: plannedPoints, loop: plannedLoop });
  // The via points are not announced (v0.7.0): the model leaves them out of its cues.
  // A re-route that turns the rider round starts with "Make a U-turn." (lib/navigate.ts withUTurn).
  const uturnRoute = useRef<RouteResponse | null>(null);
  // Re-routes in a row that asked for a U-turn the rider rode on past, and whether, with no way ahead even then
  // (REPLAN_NO_AHEAD), the U-turn route is held: left up and not re-planned again on its own (lib/navigate.ts uturnStep).
  const uturns = useRef<UTurnState>(UTURN_START);
  const checking = useRef(false);
  const modelOf = (r: RouteResponse, points: readonly LonLat[]) => {
    // A stop's own name (2026-10-24) is said and shown with its number.
    const built = rideModel(r, viaIndices(points, VIA_MARKS.isVia), stopNames(points, VIA_MARKS.nameOf, VIA_MARKS.isVia, plan.current.loop));
    return r === uturnRoute.current ? withUTurn(built) : built;
  };
  const model = useMemo(() => modelOf(route, plan.current.points), [route]);
  const modelRef = useRef(model);
  modelRef.current = model;
  // v0.8.2 (lib/roadClosed.ts): the other line beside the ride's route, the standard way through a marked closure
  // (or the detour, on the standard way), which the rider is followed onto if they take it.
  const [other, setOther] = useState<RouteResponse | null>(plannedRoute.closure_through ?? null);
  const otherRef = useRef(other);
  otherRef.current = other;
  const otherModel = useMemo(
    () => (other ? rideModel(other, viaIndices(plan.current.points, VIA_MARKS.isVia), stopNames(plan.current.points, VIA_MARKS.nameOf, VIA_MARKS.isVia, plan.current.loop)) : null),
    [other],
  );
  const otherModelRef = useRef(otherModel);
  otherModelRef.current = otherModel;
  const onStandard = useRef(false);
  // Road closed (lib/roadClosed.ts): the stretches the rider marked closed, left out of every re-plan of this ride;
  // where the last ends on the route it was marked on; and a press while a re-plan was under way.
  const blockedRef = useRef<LonLat[][]>([]);
  const blockedUntil = useRef<{ model: RideModel; untilM: number } | null>(null);
  const closedPending = useRef(false);
  const milesRef = useRef(trailMiles);
  milesRef.current = trailMiles;
  const [ride, setRide] = useState<RideState>(startState);
  // A Bikeshare or transit plan's walk to its first dock (lib/rideTrip.ts): until the rider reaches the
  // line's start, the walk is said and shown, and no fix is taken as off route.
  const approach = trip?.approach ?? null;
  const [walking, setWalking] = useState(approach !== null);
  // The walk, whether it has been said, and the last good fix (lib/rideTrip.ts tripStep); its `ride` is rideRef's.
  const tripRef = useRef(tripRideStart(trip));
  const rideRef = useRef(ride);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const [polite, setPolite] = useState({ text: "", count: 0 });
  const [assertive, setAssertive] = useState({ text: "", count: 0 });
  const [gps, setGps] = useState<string>(WAITING_FOR_GPS);
  const [wakeNote, setWakeNote] = useState("");
  // Whose steps the screen-on note gives: an iPhone's, Android's, or general words (lib/rideOutput.ts).
  const phone = useMemo(() => phoneKind(), []);
  const [replanning, setReplanning] = useState(false);
  const [replanNote, setReplanNote] = useState("");
  // "Keep the planned route": no automatic re-plan until the rider is back on it (or presses it again).
  const [keepPlanned, setKeepPlanned] = useState(false);
  // A fixed route (`fixed`) is kept always: its own ref, so a Keep press or back on route does not undo it.
  const fixedRef = useRef(fixed);
  const keepRef = useRef(keepPlanned);
  keepRef.current = keepPlanned;
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const pausedSaid = useRef(false);
  // The last GPS failure and wake note said, so each is said once, not on every repeat.
  const gpsSaid = useRef<string | null>(null);
  const wakeSaid = useRef("");
  const lastFixAt = useRef(Date.now());
  // The last good fix and whether the weak-GPS note is up (lib/navigate.ts weighFix); a new watch starts afresh.
  const gpsWeak = useRef<GpsWeakness>({ goodAt: Date.now(), weak: false });
  // Weak GPS for long enough (cueSheetShown): the card shows the turns ahead as a list.
  const [cueSheetOn, setCueSheetOn] = useState(false);
  const cueSheetRef = useRef(false);
  const cueSheetId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const whereRef = useRef<HTMLButtonElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  // Ended (End ride, or unmounted): a re-plan answering late says nothing and changes nothing.
  const ended = useRef(false);
  // The ride's own figures for the summary at End ride (lib/rideStats.ts), from the Start press.
  // Undo after End ride carries on from the figures so far, not from nought (the step across the pause not counted).
  const paceRef = useRef<PaceTrack>(paceStart());
  // The arrival clock for "Where am I?": the plan's seconds at the rider's own pace, from now.
  const arrivingAt = useCallback((seconds: number) => arrivalClock(Date.now(), seconds / paceFactor(paceRef.current)), []);
  const statsRef = useRef<RideStats>(resumeStats ? statsPause(resumeStats) : statsStart(Date.now()));
  // Each re-plan's ticket: "Keep the planned route" or a newer re-plan voids an older one's answer.
  const replanTicket = useRef(0);
  const settingsId = useId();
  // More, the last side button (closed at Start): it opens a row of bubbles beside it (Stephen 2026-10-26: "Have many
  // of those options just expanded as more bubble buttons, not in settings"): Less traffic, Fewer hills, Skip this stop
  // and Settings, the last opening the ride's settings under the top row.
  const [moreOpen, setMoreOpen] = useState(false);
  const railRef = useRef<HTMLDivElement>(null);
  const railFit = useRailFit(railRef);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsPanel = useRef<HTMLDivElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsBubble = useRef<HTMLButtonElement>(null);
  // More closed closes the settings too; the focus, if it was in them, back to More. (The idle close looks for typing
  // in the bubbles alone, More's aria-controls: the settings have no text field.)
  const toggleMore = () => {
    if (!moreOpen) {
      openMenu(null);
      setMoreOpen(true);
      return;
    }
    const held = settingsPanel.current?.contains(document.activeElement) ?? false;
    setMoreOpen(false);
    setSettingsOpen(false);
    if (held) settingsButton.current?.focus();
  };
  // Opened, the settings are brought into view (the row above them is sticky; the card may be scrolled) and the focus
  // goes into them: the bubbles come after them, so Tab alone would never reach them.
  useEffect(() => {
    if (!settingsOpen) return;
    settingsPanel.current?.scrollIntoView?.({ block: "nearest" });
    settingsPanel.current?.focus({ preventScroll: true });
  }, [settingsOpen]);
  // The 311 button's menu (lib/ride311.ts; the owner's choice 9). One tap logs; no note in a ride (Stephen,
  // 2026-10-21: "Don't bother with a note as people use it riding"): the checklist in Reports keeps the rest.
  const [menu311, setMenu311] = useState(false);
  const menu311Id = useId();
  const menu311Heading = useRef<HTMLHeadingElement>(null);
  const button311 = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (menu311) menu311Heading.current?.focus();
  }, [menu311]);
  const close311 = () => {
    setMenu311(false);
    button311.current?.focus();
  };
  // Whether the server sends reports to DC 311 itself (v0.7.0 "Go riding fixes" item 3): asked once a ride.
  const [serverOn311, setServerOn311] = useState(false);
  useEffect(() => {
    let current = true;
    void report311Enabled(window.location.origin).then((on) => {
      if (current) setServerOn311(on);
    });
    return () => {
      current = false;
    };
  }, []);
  // What the pick did, shown under the 311 button and said through the rider's outputs (it answers a tap).
  const [said311, setSaid311] = useState("");
  // The line clears after SAID_311_MS (review F4: it stayed for the whole ride), held while focused or hovered.
  const said311Timer = useHoldTimer(SAID_311_MS, () => setSaid311(""));
  const said311Shown = said311 !== "" && !menu311;
  useEffect(() => {
    if (said311Shown) said311Timer.timer.start();
    else said311Timer.timer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the timer is the same object every render
  }, [said311, said311Shown]);
  const tell311 = useCallback((text: string) => {
    setSaid311(text);
    announcer.current?.answer(text);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
  }, []);
  // One tap: the problem picked is logged (lib/report311Log.ts), with the place and the GPS position; in DC,
  // where the server has DC's key, it is sent there too and checked off. The focus goes back to the 311
  // button as the menu closes, never into a form.
  const pick311 = (kind: ReportKind) => {
    setMenu311(false);
    button311.current?.focus();
    const progress = rideRef.current.off ? null : rideRef.current.progressM;
    if (progress === null) {
      tell311(NO_PLACE_311);
      return;
    }
    const place = reportPlace(modelRef.current, progress, milesRef.current);
    const entry = report311Log().add(kind, place);
    if (serverOn311 && entry.where === "dc") {
      setSaid311(t("Sending to DC 311…"));
      void sendReport311(window.location.origin, kind, place, entryText(entry)).then((sent) => {
        if (ended.current) return;
        if (sent) report311Log().setReported(entry.id, true);
        tell311(sent ? REPORT_SENT : loggedSaid(entry));
      });
    } else tell311(loggedSaid(entry));
  };
  // An answer the rider asked for (Where am I?, a detour's progress, a new route), shown by the side buttons
  // for SAID_311_MS and held while focused or hovered; it is said through the rider's outputs as well.
  const [toast, setToast] = useState({ text: "", n: 0 });
  const toastTimer = useHoldTimer(SAID_311_MS, () => setToast((t) => ({ text: "", n: t.n })));
  const showToast = useCallback((text: string) => setToast((t) => ({ text, n: t.n + 1 })), []);
  useEffect(() => {
    if (toast.text) toastTimer.timer.start();
    else toastTimer.timer.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the timer is the same object every render
  }, [toast]);
  // The side buttons' menus: one open at a time (the detour's, the dock's, 311's), each beside the buttons.
  const [detourOpen, setDetourOpen] = useState(false);
  const detourOpenRef = useRef(false);
  detourOpenRef.current = detourOpen;
  const detourId = useId();
  const detourHeading = useRef<HTMLHeadingElement>(null);
  const detourButton = useRef<HTMLButtonElement>(null);
  // The kind picked (Water, Restroom, Food, Repair): its row of buttons gives way to its name and Change (the UI review,
  // 2026-10-28), so the list comes up the menu; Change brings the buttons back. Each opening starts with them.
  const [detourKind, setDetourKind] = useState<DetourKind | null>(null);
  const detourChange = useRef<HTMLButtonElement>(null);
  const detourKinds = useRef<HTMLDivElement>(null);
  const pickedFocus = useRef<"change" | "kinds" | null>(null);
  useEffect(() => {
    if (!detourOpen) setDetourKind(null);
  }, [detourOpen]);
  useEffect(() => {
    // The pressed button goes: the focus to what took its place.
    const to = pickedFocus.current;
    pickedFocus.current = null;
    if (to === "change") detourChange.current?.focus();
    if (to === "kinds") detourKinds.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [detourKind]);
  const [dockOpen, setDockOpen] = useState(false);
  const dockId = useId();
  const dockHeading = useRef<HTMLHeadingElement>(null);
  const dockButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (detourOpen) detourHeading.current?.focus();
  }, [detourOpen]);
  useEffect(() => {
    if (dockOpen) dockHeading.current?.focus();
  }, [dockOpen]);
  // One side menu open at a time: each opens to the buttons' left, More's bubbles too.
  const openMenu = (which: "detour" | "dock" | "311" | null) => {
    setDetourOpen(which === "detour");
    setDockOpen(which === "dock");
    setMenu311(which === "311");
    if (which) {
      setMoreOpen(false);
      setSettingsOpen(false);
    }
  };
  // A share bike (lib/rideDock.ts): the undock is taken as reaching the first dock, or the start where there is
  // no walk to it; reaching a dock ridden to with the dock button starts the time again.
  const shareBike = !!trip?.shareBike;
  const [undockAt, setUndockAt] = useState<number | null>(() => (trip?.shareBike && !trip.approach ? Date.now() : null));
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (undockAt === null) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [undockAt]);
  // The spoken warning at 35 minutes and every 5 after (lib/rideDock.ts warningDue); not while docked or at the end.
  const warnedAt = useRef<number | null>(null);
  useEffect(() => {
    warnedAt.current = null;
  }, [undockAt]);
  const undockRef = useRef(undockAt);
  undockRef.current = undockAt;
  // Docked again (lib/rideDock.ts): the dock's name while docked, its place, and where the rider stands still.
  const [docked, setDocked] = useState<string | null>(null);
  const dockedRef = useRef<LonLat | null>(null);
  const still = useRef<Still | null>(null);
  // The dock the rider chose with the dock button: stopped there a short while is enough.
  const chosenDock = useRef<{ point: LonLat; name: string } | null>(null);
  const restartTime = () => {
    dockedRef.current = null;
    still.current = null;
    setDocked(null);
    setUndockAt(Date.now());
  };
  const arrived = ride.arrived;
  // At the end the dock button goes: a focus in it (or its menu) goes to Where am I?.
  useEffect(() => {
    if (!arrived) return;
    setDockOpen(false);
    const active = document.activeElement;
    if (!active || active === document.body || !active.isConnected) whereRef.current?.focus({ preventScroll: true });
  }, [arrived]);
  useEffect(() => {
    if (undockAt === null || docked || arrived || ended.current) return;
    const mark = warningDue(undockedMinutes(undockAt, now), warnedAt.current);
    if (mark === null) return;
    warnedAt.current = mark;
    const text = undockedWarning(mark);
    // Said at once through the rider's outputs (and the polite region with neither chosen), and shown.
    announcer.current?.answer(text);
    if (prefsRef.current.output === "neither") setPolite((p) => ({ text, count: p.count + 1 }));
    showToast(text);
  }, [undockAt, now, docked, arrived, showToast]);
  const gate = useRef(new ReplanGate()).current;
  // In the phone app (lib/nativeShell.ts) the lock and the watch are the native ones; in a browser, the browser's.
  const wake = useRef(new ScreenWake(rideWake())).current;
  const env = useRef(geoEnv ?? rideGeoEnv()).current;

  // The outputs: the screen reader's regions and the voice, as the rider chose; through the throttle.
  const deliver = useCallback((said: Said) => {
    const output = prefsRef.current.output;
    // A jog's next turn (`after`) in the polite region, so it is read after the turn before rather than in place of it.
    if (toScreenReader(output)) (said.urgent && !said.after ? setAssertive : setPolite)((s) => ({ text: said.text, count: s.count + 1 }));
    // The voice as chosen; in the phone app also "my screen reader" while the page is hidden (nativeShell.ts).
    if (speaksAloud(output, document.visibilityState === "hidden")) rideVoice.speak(said.text, said.urgent, said.after);
    // The phone app's cue notification on Android (nothing in a browser).
    showCue(said.text);
  }, []);
  const announcer = useRef<Announcer | null>(null);
  if (announcer.current === null) announcer.current = new Announcer(deliver);

  // After the page comes back from the background: say where the rider is once, on the next fix.
  const sayWhereNext = useRef(false);
  const say = useCallback((events: RideEvent[]) => {
    for (const event of events) announcer.current?.say(event.spoken, event.urgent, event.after);
  }, []);
  // A note about the ride itself (no GPS, the screen may sleep, paused): said once, politely, through the
  // rider's outputs, and through the polite region with "neither" chosen, since it changes what the rider
  // must do. Not with the voice as well: a screen reader on "voice" heard it twice (review RIDE-10).
  const notify = useCallback((text: string) => {
    if (!text) return;
    announcer.current?.note(text);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
  }, []);
  const noteWake = useCallback(
    (held: boolean) => {
      // Never held: the browser cannot; held earlier this ride and let go: it stopped (review RIDE-8).
      const note = wake.noteFor(held);
      // Said whole, with this phone's own steps; shown as one line (ScreenSleepNote).
      if (note && note !== wakeSaid.current) notify(wakeWords(note, phone));
      wakeSaid.current = note;
      setWakeNote(note);
    },
    [notify, wake, phone],
  );
  // The browser letting the lock go mid-ride (review RIDE-8): asked again, and said if it is not back.
  useEffect(() => {
    wake.whenLost(noteWake);
    return () => wake.whenLost(null);
  }, [wake, noteWake]);

  // The detour's own status (below): said like an answer, since the rider asked for it.
  const [detourStatus, setDetourStatus] = useState("");
  const [detourList, setDetourList] = useState<DetourFound | null>(null);
  const [detourQuery, setDetourQuery] = useState("");
  const sayDetour = useCallback((text: string) => {
    setDetourStatus(text);
    // Shown in the detour's menu while it is open; by the side buttons otherwise (the dock's, a re-plan's outcome).
    if (!detourOpenRef.current) showToast(text);
    // On demand, as Where am I? is: through the rider's outputs, and the polite region with neither chosen.
    announcer.current?.answer(text);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
  }, [showToast]);
  // The re-plan (plan section 4): one POST /api/route from here through the stops not yet passed to the end.
  // With `via`, a detour: from here to that place first, then on through what was left (the nearest water
  // or restroom, below). A detour's place becomes a stop of the new route, so it is cued and arrived at.
  const replan = useCallback(
    async (here: LonLat, via?: LonLat, asked = false, turnRound = false, check = false, skip?: number, done?: ReadonlySet<number>): Promise<boolean> => {
      if (ended.current) return false;
      const current = rideRef.current;
      // The way the rider is going (the owner, 2026-10-18: "Penalize U turns", "For rerouting"): the new route sets
      // off ahead unless turning round saves half a mile. Not after Road closed, where turning round is the point.
      const heading = turnRound ? null : (current.goodFix?.headingDeg ?? null);
      // Two U-turns ridden past: the rider means to stay on this way, so this one sets off ahead whatever turning saves.
      const aheadOnly = uturnAheadOnly(uturns.current, heading);
      // A re-route: via points close ahead are guides and dropped, stops kept (2026-10-24); the stop the rider
      // skipped (Skip this stop, or a place chosen instead of it) is left out.
      // The same kept points for the way back below, so its stops keep their numbers in the new plan.
      // A restart part way (`done`, RestartStopsDialog): the stops the rider left unticked, behind or not.
      const keptPoints = done
        ? restartKept(modelRef.current, current.progressM ?? 0, plan.current.points, plan.current.loop, done)
        : replanKept(modelRef.current, current.progressM ?? 0, plan.current.points, plan.current.loop, true).filter((i) => i !== skip);
      const left = withoutStop(plan.current.points, keptPoints, here, skip ?? -1);
      // `let`: a re-route that leaves out the next via point (VIA_SKIP_EXTRA_S, below) rides the points without it.
      let points = via ? detourPoints(left, via) : left;
      if (!points) {
        sayDetour(DETOUR_FULL);
        return false;
      }
      // A held U-turn's silent check does not take the gate, so the rider's own asks are never held up by it; one of
      // theirs voids it (the ticket).
      if (check ? gate.busy || checking.current : !gate.begin(Date.now())) {
        // Only a detour is the rider's own ask; an automatic re-plan held back by the gate says nothing.
        if (via) sayDetour(DETOUR_BUSY);
        return false;
      }
      const ticket = (replanTicket.current += 1);
      if (check) checking.current = true;
      // A held U-turn's check for a way ahead (UTURN_RECHECK_MS) is silent: nothing shown or said unless it finds one.
      if (!check) {
        setReplanning(true);
        setReplanNote("");
      }
      // The quiet level hears nothing unprompted but arrival, and the stoker only that a new route was
      // found (plan section 3, off route said once); the note stays on screen for all. A detour's outcome
      // answers the rider's ask, so it is said whatever the level (sayDetour); so is Re-plan from here's.
      const tell = (note: string) => {
        if (via) {
          sayDetour(note);
          return;
        }
        const told = replanTold(asked, prefsRef.current.verbosity, note);
        if (told === "say") announcer.current?.say(note, note === REPLAN_NO_AHEAD);
        if (told === "answer") {
          announcer.current?.answer(note);
          if (prefsRef.current.output === "neither") setPolite((s) => ({ text: note, count: s.count + 1 }));
        }
      };
      // No answer in REPLAN_TIMEOUT_MS: the rider is told there is no signal, while the request goes on
      // (the gate stays busy until it settles, so no second one joins it at the server; a late new
      // route is still taken).
      const timer = check ? undefined : window.setTimeout(() => {
        if (ended.current || ticket !== replanTicket.current) return;
        setReplanNote(REPLAN_NO_SIGNAL);
        tell(REPLAN_NO_SIGNAL);
      }, REPLAN_TIMEOUT_MS);
      // The rider is riding a plan already made: a long one is not asked to be confirmed again (a signed-out
      // rider's re-plan of a long ride was refused for want of it).
      const ask = (to: LonLat[]) =>
        requestRoute(to, preset, { dials: { ...dialsRef.current, loop: false }, vias: viaIndices(to, VIA_MARKS.isVia), straight: drawnLegs(to), routeOnly: true, confirmLong: true, blocked: blockedRef.current, heading, aheadOnly, rideReplan: true, dirtRidden: dirtRidden.current, dirtClosed: dirtClosed.current });
      let found: RouteResponse | null = null;
      let failed: ErrorKind | null = null;
      let note = REPLAN_FOUND;
      let skippedVia = false;
      const voided = () => ended.current || ticket !== replanTicket.current;
      // Never back onto a road the rider marked closed: a way back joins the route past it.
      const closed = blockedUntil.current?.model === modelRef.current ? blockedUntil.current.untilM : -Infinity;
      // Off a route the rider chose over the first, the way back to it ahead first (routing audit D15; the owner,
      // 2026-10-27: "stops need to be made and via points should be followed as the default unless there's an
      // overriding reason to change"), so a new plan does not pull them back toward the route they turned down; a new
      // plan only where there is no way back. A way back is a short ask or three, not a plan to the end.
      const backFirst = rejoinsFirst(routeRef.current, { asked, detour: !!via, check, restart: !!done, skip: skip !== undefined });
      if (backFirst) {
        const back = await wayBackRoute(routeRef.current, modelRef.current, current.progressM ?? 0, here, keptPoints, ask, voided, closed);
        if ("route" in back) {
          found = back.route;
          note = REPLAN_REJOIN_AHEAD;
        } else failed = back.failed;
      }
      // No signal for the way back: a plan to the end would not get through either.
      if (!found && failed !== "network" && !voided()) {
        const result = await ask(points);
        found = result.ok ? result.route : null;
        failed = result.ok ? null : result.error.kind;
        // A re-route may leave out the next via point, never a later one and never a stop (Stephen, 2026-10-27: "Vias can
        // be skipped a little more, for instance if a road is closed, you shouldn't expect a 20 minute detour just to get
        // to the other side. Those are guides. Stops are where you want to end up." and "Sometimes people plan very
        // indirect routes for fun, so it shouldn't skip all of the vias"): where the new route takes more than
        // VIA_SKIP_EXTRA_S longer to reach it than the planned one would have from the rider's place, it is planned once
        // more without it. Not for a detour, a held U-turn's check, a restart, or a Calmer or Flatter press (its route is
        // slower by choice). The second ask is made only when that trips.
        const eased = easing.current?.ticket === ticket;
        const next = result.ok && !via && !check && !done && !eased ? skippableVia(modelRef.current, keptPoints) : null;
        if (result.ok && next && viaSkipWorth(modelRef.current, current.progressM ?? 0, next.atM, modelOf(result.route, points), 1) && !voided()) {
          const without = points.filter((_, i) => i !== 1);
          const again = await ask(without);
          if (again.ok) {
            found = again.route;
            points = without;
            skippedVia = true;
          }
        }
        // No new route to the end: the way back to the planned route, which goes on from there (lib/rejoin.ts;
        // the owner, 2026-10-17), unless it was tried first. Not for a detour, whose place the planned route does not
        // pass. The no-signal timer runs on through it.
        if (!result.ok && !backFirst && !via && !check && startsWayBack(result.error.kind) && !voided()) {
          const kept = keptPoints;
          const back = await wayBackRoute(routeRef.current, modelRef.current, current.progressM ?? 0, here, kept, ask, voided, closed);
          if ("route" in back) found = back.route;
          else if (back.failed) failed = back.failed;
          note = REPLAN_REJOIN;
        }
      }
      window.clearTimeout(timer);
      if (check) checking.current = false;
      else gate.finish(found !== null);
      // Road closed pressed while this one was under way: this answer did not leave that road out, so it is
      // dropped (the press voided it) and the ride is planned again from where the rider is now.
      if (!check && closedPending.current && !ended.current) {
        closedPending.current = false;
        gate.online();
        void replanRef.current(rideRef.current.goodFix?.point ?? here, undefined, true, true);
        return false;
      }
      if (voided()) return false;
      // Still no way ahead: the held route stays as it is, and nothing is said.
      if (check && (!found || heading === null || setsOffBack(found.geometry.coordinates, heading))) return false;
      setReplanning(false);
      if (!found) {
        const said = failed === "network" ? REPLAN_NO_SIGNAL : REPLAN_FAILED;
        setReplanNote(said);
        tell(said);
        return false;
      }
      plan.current = { points, loop: false };
      // The first route, without the picker, during a ride (plan section 4).
      announcer.current?.drop();
      // Turned round (the API keeps a U-turn only where it saves half a mile): said plainly, and the first cue.
      const turned = heading !== null && setsOffBack(found.geometry.coordinates, heading);
      uturnRoute.current = turned ? found : null;
      // Counted, said and held there; a way back that turns round is not held (the rider was told to follow it), and
      // a re-route made while stopped (no heading; not Road closed) leaves the count as it is.
      // A Calmer or Flatter press is not riding past a U-turn either: it leaves the count as it is (lib/rideEase.ts).
      const press = easing.current?.ticket === ticket ? easing.current : null;
      const counted = uturnStep(uturns.current, { kind: "rerouted", turned, aheadOnly, stopped: (heading === null && !turnRound) || press !== null, note, now: Date.now() });
      uturns.current = counted.state;
      note = counted.note ?? note;
      // "Skipping via point. New route found." (or its U-turn or keep-ahead form), briefly.
      if (skippedVia) note = viaSkippedNote(note);
      if (press) {
        press.outcome = note === REPLAN_REJOIN ? "rejoin" : "found";
        if (press.outcome === "found" && !turned && sameLine(found.geometry.coordinates, press.before.geometry.coordinates)) note = EASE_SAME[press.which];
      }
      const model = modelOf(found, points);
      modelRef.current = model;
      if (found.dirt_trails) dirtRidden.current = true;
      if (found.dirt_closed) dirtClosed.current = true;
      setRoute(found);
      // The ride as it now stands is what a page closed mid-ride resumes (lib/rideResume.ts); never a trip's leg.
      if (!trip && keepLeft) keepLeftRide({ route: found, points, loop: false, preset, dials: dialsRef.current, fixed: fixedRef.current }, VIA_MARKS, Date.now());
      // The new route's own standard way through a closure it goes round, if any (none past a road marked closed).
      const through = blockedRef.current.length ? null : (found.closure_through ?? null);
      otherRef.current = through;
      setOther(through);
      onStandard.current = false;
      // The rider stays where they are on the map until the next fix places them on the new route.
      const fresh = { ...startState(), fix: rideRef.current.fix, goodFix: rideRef.current.goodFix };
      rideRef.current = fresh;
      setRide(fresh);
      setKeepPlanned(false);
      setReplanNote(note);
      tell(note);
      return true;
    },
    [preset, gate, sayDetour, trip, keepLeft],
  );
  const replanRef = useRef(replan);
  replanRef.current = replan;

  // The rider took the other line (lib/roadClosed.ts onOtherLine): it is the ride's route from here, the one left
  // the other line, with no re-plan and no "off route" (the owner, 2026-10-17: "If you take the standard route, just
  // keep going, if you move to the detour take that").
  const takeOther = useCallback((alongM: number, fix: RideFix) => {
    const was = routeRef.current;
    const next = otherRef.current;
    const nextModel = otherModelRef.current;
    if (!next || !nextModel) return;
    replanTicket.current += 1;
    uturns.current = uturnStep(uturns.current, { kind: "other-line" }).state;
    onStandard.current = !onStandard.current;
    announcer.current?.drop();
    routeRef.current = next;
    modelRef.current = nextModel;
    otherRef.current = was;
    setRoute(next);
    setOther(was);
    const fresh: RideState = { ...startState(), fix, goodFix: fix, goodAt: fix.at, progressM: alongM, speedMs: rideRef.current.speedMs };
    rideRef.current = fresh;
    setRide(fresh);
    setReplanning(false);
    setReplanNote("");
    setKeepPlanned(false);
    if (prefsRef.current.verbosity !== "quiet") announcer.current?.say(onStandard.current ? ON_STANDARD_SAID : ON_DETOUR_SAID, false);
  }, []);

  // No good fix for a minute, or for longer than the next turn is away: the turns ahead as a list, said
  // once; a good fix brings the turn-by-turn card back (the owner, 2026-10-16). Asked on each fix and on
  // a timer (below), so it comes when the fixes stop altogether too.
  const checkCueSheet = useCallback(
    (now: number) => {
      const state = rideRef.current;
      if (ended.current || state.arrived || pausedRef.current) return;
      const sheet = cueSheetShown(gpsWeak.current, now, cueSheetAfterMs(modelRef.current, state.progressM ?? 0, state.speedMs));
      if (sheet && !cueSheetRef.current) notify(CUE_SHEET_SAID);
      cueSheetRef.current = sheet;
      setCueSheetOn(sheet);
    },
    [notify],
  );
  useEffect(() => {
    const timer = window.setInterval(() => checkCueSheet(Date.now()), CUE_SHEET_CHECK_MS);
    return () => window.clearInterval(timer);
  }, [checkCueSheet]);

  // Restarting part way: asked at the first fix past a stop, never after Undo (it carries on) or on a trip's leg (its
  // walk to the dock comes first). The defaults ride on as the ride is; other picks plan again from here.
  const restartAsked = useRef(resumeStats !== null || trip !== null);
  const [restart, setRestart] = useState<RestartStop[] | null>(null);
  // While it is asked, no re-route of its own: the stops it lists are the plan's as it stands (review of #444).
  const restartOpen = useRef(false);
  restartOpen.current = restart !== null;
  const onFix = useCallback(
    (fix: RideFix) => {
      if (ended.current) return;
      gpsSaid.current = null;
      lastFixAt.current = Date.now();
      // Only poor fixes for a while: the cues are paused, so the GPS note says so, once (review RIDE-3).
      const weighed = weighFix(gpsWeak.current, fix.accuracyM, lastFixAt.current);
      gpsWeak.current = { goodAt: weighed.goodAt, weak: weighed.weak };
      if (weighed.sayNow) notify(GPS_WEAK_SAID);
      setGps(weighed.weak ? GPS_WEAK_SAID : "");
      checkCueSheet(lastFixAt.current);
      const auto = !keepRef.current && !fixedRef.current && !restartOpen.current;
      // Walking to the dock, nothing is placed on the line or taken as off route (lib/rideTrip.ts).
      const wasWalking = tripRef.current.walking;
      // Held after "No route found ahead": off route says no "finding a new way", as none is looked for out loud.
      const stepped = tripStep(modelRef.current, trip, { ...tripRef.current, ride: rideRef.current }, fix, prefsRef.current.verbosity, auto && !uturns.current.held);
      tripRef.current = stepped.state;
      for (const note of stepped.notes) notify(note);
      if (wasWalking && !stepped.state.walking) {
        setWalking(false);
        if (trip?.shareBike) setUndockAt(Date.now());
      }
      // On a share bike: stopped at a dock for a while is taken as docked; riding off from it again starts the time from 0.
      if (trip?.shareBike && undockRef.current !== null && fix.accuracyM <= POOR_FIX_M) {
        const at = dockedRef.current;
        if (at) {
          if (haversineM(fix.point, at) > LEFT_DOCK_M) restartTime();
        } else {
          still.current = stillStep(still.current, fix.point, fix.at);
          const chosen = chosenDock.current;
          if (chosen && haversineM(still.current.point, chosen.point) <= DOCKED_M && stillAtLength(still.current, fix.at, CHOSEN_STILL_MS)) {
            still.current = { ...still.current, checked: true };
            chosenDock.current = null;
            dockedRef.current = chosen.point;
            setDocked(chosen.name);
            notify(dockedSaid(chosen.name));
          } else if (stillAtLength(still.current, fix.at)) {
            still.current = { ...still.current, checked: true };
            const where = still.current.point;
            void docksAround(where, fetchDocks).then((docks) => {
              const dock = dockAt(where, docks);
              if (!dock || ended.current || dockedRef.current) return;
              dockedRef.current = [dock.lon, dock.lat];
              setDocked(dock.name);
              notify(dockedSaid(dock.name));
            });
          }
        }
      }
      const out = { state: stepped.state.ride, events: stepped.events };
      rideRef.current = out.state;
      setRide(out.state);
      statsRef.current = stepped.state.walking
        ? statsPause(statsRef.current)
        : statsStep(statsRef.current, fix, out.state, modelRef.current, routeRef.current.profile);
      // The rider's pace against the plan, for the arrival times (lib/arrival.ts).
      const line = modelRef.current;
      paceRef.current = paceStep(paceRef.current, {
        atMs: fix.at,
        progressM: out.state.progressM,
        line: `${line.lengthM}:${line.coordinates.length}`,
        paceMs: line.paceMs,
        plan: (fromM, toM) => secondsBetween(line, fromM, toM),
        riding: !stepped.state.walking && !pausedRef.current && !out.state.off && !out.state.arrived && fix.accuracyM <= POOR_FIX_M,
      });
      if (stepped.state.walking) return;
      // Restarted part way (Stephen 2026-10-24): the first place on the line past a stop asks, once, which are done.
      if (!restartAsked.current && out.state.progressM !== null) {
        restartAsked.current = true;
        const stops = restartStops(modelRef.current, out.state.progressM);
        if (stops) {
          const named = stops.map((s) => (s.name ? s : { ...s, name: stopName?.(plan.current.points[s.index]) }));
          restartOpen.current = true;
          setRestart(named);
          notify(restartSaid(named));
        }
      }
      // Off this line but on the other one (the standard way, or the detour): followed there, not re-planned.
      if (out.state.off && fix.accuracyM <= POOR_FIX_M) {
        const at = onOtherLine(otherModelRef.current, fix.point, fix.accuracyM, out.state.progressM ?? -Infinity);
        if (at !== null) {
          takeOther(at, fix);
          return;
        }
      }
      say(out.events);
      // Turned round as asked: the next U-turn re-route counts from one again.
      uturns.current = uturnStep(uturns.current, { kind: "along", onUTurnRoute: uturnRoute.current === routeRef.current, off: out.state.off, progressM: out.state.progressM }).state;
      // A fixed route: leaving it says the way back, once, as Keep the planned route does.
      if (fixedRef.current && out.events.some((e) => e.kind === "off-route")) {
        const back = wayBack(modelRef.current, out.state);
        if (back) announcer.current?.answer(`${FIXED_SAID} ${wayBackSaid(back)}`);
      }
      // Back on the planned route: "Keep" has done its work; leaving it again re-plans as usual.
      if (out.events.some((e) => e.kind === "back-on-route") || (keepRef.current && !out.state.off)) setKeepPlanned(false);
      // Never from a poor fix: a re-plan from a Wi-Fi guess 300 m out would be wrong at once.
      // Not after "No route found ahead": that route stays up (Re-plan from here still asks again), checked quietly.
      if (out.state.off && auto && !gate.busy && fix.accuracyM <= POOR_FIX_M && out.state.goodFix) {
        const offRoute = uturnStep(uturns.current, { kind: "off-route", now: Date.now() });
        uturns.current = offRoute.state;
        if (offRoute.replan === "ask") void replan(out.state.goodFix.point);
        // Held: a quiet look now and then for a way ahead (the owner, 2026-10-20: "check periodically... but should do so silently").
        else if (offRoute.replan === "check") void replan(out.state.goodFix.point, undefined, false, false, true);
      }
      if (sayWhereNext.current && out.state.progressM !== null) {
        sayWhereNext.current = false;
        announcer.current?.answer(whereAmI(modelRef.current, out.state, false, milesRef.current, arrivingAt));
      }
    },
    [gate, replan, say, notify, checkCueSheet, approach, trip, takeOther, stopName, arrivingAt],
  );
  const onFixRef = useRef(onFix);
  onFixRef.current = onFix;

  // The watch: started with the ride (the Start press), stopped at End ride, after a long hide, on unmount.
  const stopWatch = useRef<(() => void) | null>(null);
  const startWatch = useCallback(() => {
    stopWatch.current?.();
    gpsWeak.current = { goodAt: Date.now(), weak: false };
    stopWatch.current = watchRide(
      env,
      (fix) => onFixRef.current(fix),
      (reason) => {
        if (reason === "timeout") {
          // Many phones report a lost signal as a timeout: said once no fix has come for GPS_LOST_MS.
          if (gpsSaid.current !== reason && Date.now() - lastFixAt.current >= GPS_LOST_MS) {
            notify(GPS_LOST_SAID);
            gpsSaid.current = reason;
          }
          setGps(WAITING_FOR_GPS);
        } else {
          // Said once: at once where the watch has stopped for good, else only once no fix has come for
          // GPS_LOST_MS (a lone failure between fixes is common, and would talk over the cues).
          const final = reason === "denied" || reason === "insecure" || reason === "unsupported";
          if (gpsSaid.current !== reason && (final || Date.now() - lastFixAt.current >= GPS_LOST_MS)) {
            notify(LOCATE_MESSAGES[reason]);
            gpsSaid.current = reason;
          }
          setGps(LOCATE_MESSAGES[reason]);
          if (reason === "denied" || reason === "insecure" || reason === "unsupported") {
            stopWatch.current?.();
            stopWatch.current = null;
          }
        }
      },
    );
  }, [env, notify]);

  useEffect(() => {
    ended.current = false;
    startWatch();
    void wake.hold().then(noteWake);
    headingRef.current?.focus();
    return () => {
      ended.current = true;
      stopWatch.current?.();
      stopWatch.current = null;
      void wake.letGo();
      announcer.current?.drop();
      // The voice is not stopped here: End ride says "Ride ended." as the ride goes (end, below).
    };
  }, [startWatch, wake, noteWake]);

  // The page hidden and shown again (plan section 5): the lock again, a fresh place said once; hidden
  // over HIDDEN_STOP_MS, the watch stops and Resume is offered.
  useEffect(() => {
    let timer: number | undefined;
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        // The phone app keeps the ride going with the screen locked (lib/nativeShell.ts): no pause there.
        if (ridesHidden()) return;
        timer = window.setTimeout(() => {
          stopWatch.current?.();
          stopWatch.current = null;
          pausedRef.current = true;
          setPaused(true);
          void wake.letGo();
        }, HIDDEN_STOP_MS);
      } else {
        window.clearTimeout(timer);
        if (pausedRef.current) {
          // Back after the watch stopped: say so, once; the lock waits for Resume.
          if (!pausedSaid.current) notify(PAUSED_SAID);
          pausedSaid.current = true;
          return;
        }
        void wake.again().then(noteWake);
        if (stopWatch.current) sayWhereNext.current = true;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [wake, notify, noteWake]);

  // No signal: a failed re-plan tries again as the connection comes back.
  useEffect(() => {
    const onOnline = () => {
      gate.online();
      const state = rideRef.current;
      if (state.off && !keepRef.current && !fixedRef.current && !restartOpen.current && !uturns.current.held && state.goodFix) void replan(state.goodFix.point);
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [gate, replan]);

  // The map's view of the ride.
  const fix = ride.fix;
  // Where the next train or bus is, while the rider waits at the boarding (NextVehicleLine).
  const [vehicle, setVehicle] = useState<VehicleMark | null>(null);
  // The stops still ahead (2026-10-24): on the map with their names, and the next one's Skip and Instead.
  const aheadKey = ride.progressM === null ? null : Math.floor(ride.progressM / 10);
  const stops = useMemo(
    () => stopsAhead(model, ride.progressM ?? 0, plan.current.points).map(({ point, number }): RideStopMark => ({ point, number, name: stopName?.(point) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, aheadKey, stopName],
  );
  const nextStop = ride.arrived ? null : (stops[0] ?? null);
  useEffect(() => {
    onView({
      route,
      other: other?.geometry.coordinates ?? null,
      rider: fix ? { point: fix.point, headingDeg: fix.headingDeg, accuracyM: fix.accuracyM } : null,
      vehicle,
      stops,
    });
  }, [route, other, fix, onView, vehicle, stops]);

  // The map along the route, kept for dead spots (lib/corridor.ts, plan section 6): fetched at Start ride
  // and again for a re-plan's new route (only the tiles the first did not cover), cleared at End ride.
  // Shown under the controls, not said: it changes nothing the rider must do.
  const [corridor, setCorridor] = useState<PrefetchResult | "saving" | null>(null);
  const firstCorridor = useRef(true);
  useEffect(() => {
    let current = true;
    setCorridor("saving");
    // The ride's first route clears whatever an earlier ride or page kept before it fetches.
    const first = firstCorridor.current;
    firstCorridor.current = false;
    void keepCorridor(route.geometry.coordinates, first).then((result) => {
      if (current && !ended.current) setCorridor(result);
    });
    return () => {
      current = false;
    };
  }, [route]);
  const handsOn = useRef(keepLastRide);
  useEffect(() => () => void clearCorridor(handsOn.current ? lastRideAdopter() : undefined), []);
  // Hidden, the installed app may be closed and never reach End ride: the last ride gets the map kept
  // so far now, as End ride would hand it on (review RIDE-1).
  useEffect(() => {
    if (!handsOn.current) return;
    const onHide = () => {
      if (document.visibilityState === "hidden" && !ended.current) void copyCorridor(lastRideAdopter());
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, []);
  // Only a problem is shown (the bottom panel stays away while all is well); saved in full says nothing.
  const corridorText = corridorWorry(corridor);

  const resume = () => {
    pausedRef.current = false;
    pausedSaid.current = false;
    setPaused(false);
    sayWhereNext.current = true;
    startWatch();
    void wake.hold().then(noteWake);
    // The Resume button goes: the focus goes to Where am I? rather than the page's top.
    whereRef.current?.focus();
  };
  const askWhere = useCallback(() => {
    // Walking to the dock: the walk, from here.
    const walk = tripRef.current.walking && approach ? approachWords(approach, rideRef.current.fix?.point ?? null) : null;
    const spoken = walk ? walk.spoken : whereAmI(modelRef.current, rideRef.current, false, milesRef.current, arrivingAt);
    // Shown as two short lines (whereAmIShown), said whole.
    showToast(walk ? walk.shown : whereAmIShown(modelRef.current, rideRef.current, milesRef.current, arrivingAt).join("\n"));
    // On demand: through the chosen outputs; with neither chosen, through the polite region too, since
    // the rider asked (the answer is also on screen).
    announcer.current?.answer(spoken);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text: spoken, count: s.count + 1 }));
  }, [approach, showToast, arrivingAt]);
  // Where am I? and Re-centre are one button (the owner, 2026-10-20: "We can merge the where am I and the center on map
  // button functionality"): the map follows the rider again, and the answer is said and shown.
  const findMe = useCallback(() => {
    onFollow(true);
    askWhere();
  }, [askWhere, onFollow]);
  // The Large text button (the owner, 2026-10-20), the same choice as Settings' switch. The change is said as an answer,
  // as Where am I? is, since a pressed state's change is not always read out.
  const cycleText = useCallback(() => {
    const next = textSize === "large" ? "normal" : "large";
    onTextSize(next);
    const said = next === "large" ? t("Large text on") : t("Large text off");
    showToast(said);
    announcer.current?.answer(said);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text: said, count: s.count + 1 }));
  }, [onTextSize, showToast, textSize]);
  // Ride the rest (lib/rideTrip.ts): offered near or past the stop where the transit ends, said once as it
  // shows; the press is answered as Re-plan from here's is, and a new ride replaces this one.
  const rest = trip?.rest ?? null;
  const restShown = !!rest && !!onRideRest && !walking && restNear(rest, ride.fix?.point ?? null, ride.arrived);
  const restSaid = useRef(false);
  useEffect(() => {
    if (!restShown || !rest || restSaid.current) return;
    restSaid.current = true;
    notify(restReadySaid(rest));
  }, [restShown, rest, notify]);
  const restBusy = useRef(false);
  const rideTheRest = () => {
    if (!onRideRest || restBusy.current) return;
    const answer = (text: string) => {
      announcer.current?.answer(text);
      if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
    };
    restBusy.current = true;
    answer(RIDE_REST_FINDING);
    // The last good fix, kept after arrival (the line's goodFix stops at the drop-off), while fresh.
    void onRideRest(restFrom(tripRef.current.lastGood, Date.now())).then((said) => {
      restBusy.current = false;
      if (said && !ended.current) answer(said);
    });
  };
  const end = () => {
    ended.current = true;
    stopWatch.current?.();
    stopWatch.current = null;
    announcer.current?.drop();
    rideVoice.stop();
    // Only "Ride ended." is said; the figures are on the summary (the owner, 2026-10-20: "Just put ride ended.").
    if (toVoice(prefsRef.current.output)) rideVoice.speak(RIDE_ENDED_SAID, true);
    // A Bikeshare or transit trip's riding leg is not the plan: the plan stays as it was.
    onEnd(trip && !trip.asPlanned ? null : planAfterEnd(modelRef.current, rideRef.current, plan.current.points, plan.current.loop, Date.now()), statsRef.current);
  };
  // A toggle: pressed, no automatic re-plan (one in flight is voided) and the way back is said once;
  // pressed again, re-planning is back on.
  const keep = () => {
    if (keepPlanned) {
      setKeepPlanned(false);
      return;
    }
    replanTicket.current += 1;
    // Keep wins over a Road closed press still waiting on a re-plan.
    closedPending.current = false;
    setReplanning(false);
    setKeepPlanned(true);
    setReplanNote("");
    const back = wayBack(modelRef.current, rideRef.current);
    if (back) announcer.current?.answer(wayBackSaid(back));
  };
  // End ride tapped, not slid: the hint by the side buttons, and through the rider's outputs.
  const slideHint = () => {
    showToast(SLIDE_TO_END_HINT);
    announcer.current?.answer(SLIDE_TO_END_HINT);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text: SLIDE_TO_END_HINT, count: s.count + 1 }));
  };
  // Road closed (lib/roadClosed.ts): one press, no menu. The road ahead is marked closed for this ride and the ride
  // planned again round it; the standard way beside a marked closure goes too, as it may run along it.
  const roadClosed = () => {
    const state = rideRef.current;
    const fix = state.goodFix ?? state.fix;
    const stretch = fix ? closedAhead(modelRef.current, state.progressM, state.off, fix.point, fix.headingDeg) : null;
    if (!fix || !stretch) {
      sayDetour(ROAD_CLOSED_NO_PLACE);
      return;
    }
    blockedRef.current = withClosed(blockedRef.current, stretch.line);
    blockedUntil.current = stretch.untilM === null ? null : { model: modelRef.current, untilM: stretch.untilM };
    otherRef.current = null;
    setOther(null);
    setKeepPlanned(false);
    sayDetour(ROAD_CLOSED_FINDING);
    if (gate.busy) {
      // The re-plan under way does not leave it out: it is voided, and the ride planned again once it settles.
      closedPending.current = true;
      replanTicket.current += 1;
      return;
    }
    gate.online();
    void replan(fix.point, undefined, true, true);
  };
  const replanNow = () => {
    // The rider asked, so the press is answered, as Detour's is (review RIDE-5): through the rider's
    // outputs, and the polite region with neither chosen.
    const answer = (text: string) => {
      announcer.current?.answer(text);
      if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
    };
    // Walking to the dock: the walk again, not a ride from here that would skip the dock.
    if (tripRef.current.walking && approach) {
      answer(approachWords(approach, rideRef.current.fix?.point ?? null).spoken);
      return;
    }
    // A re-plan still under way (or one kept waiting after Keep the planned route) holds the gate.
    if (replanning || gate.busy) {
      answer(REPLAN_STILL_WAITING);
      return;
    }
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (!here) {
      answer(NO_FIX_YET);
      return;
    }
    setKeepPlanned(false);
    gate.online();
    answer(REPLAN_FINDING);
    void replan(here, undefined, true);
  };

  // Calmer and Flatter (lib/rideEase.ts; the owner, 2026-10-23): one step down the traffic or hills slider, then
  // planned again from here as Re-plan from here is. A step that finds no new route is undone.
  // An answer to a side button or More's press: said in full; shown in its first sentence alone (fewer words on
  // screen, the owner, 2026-10-20).
  const answer = (text: string) => {
    announcer.current?.answer(text);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
    showToast(text.replace(/(?<=\.) .*$/, ""));
  };
  // The start's own note, after "Ride started." (read once, at Start ride).
  const startNoteRef = useRef(startNote);
  useEffect(() => {
    const text = startNoteRef.current;
    if (!text) return;
    const timer = window.setTimeout(() => answer(text), START_NOTE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, at Start ride
  }, []);
  // Broadcast (App's broadcastFromRide): the share sheet opens inside the press; a second press while one is open is
  // left alone.
  const broadcastBusy = useRef(false);
  const broadcast = async () => {
    if (!onBroadcast || broadcastBusy.current) return;
    broadcastBusy.current = true;
    try {
      const said = await onBroadcast();
      if (said && !ended.current) answer(said);
    } finally {
      broadcastBusy.current = false;
    }
  };
  const broadcastHoldId = useId();
  const broadcastHold = useHold(
    onBroadcastHold
      ? () =>
          void onBroadcastHold().then((said) => {
            if (said && !ended.current) answer(said);
          })
      : null,
  );
  // More's own presses (Less traffic, Fewer hills, Skip this stop): the bubbles close, the map back in view, and the
  // focus goes to More.
  const fromMore = (press: () => void) => {
    setMoreOpen(false);
    setSettingsOpen(false);
    settingsButton.current?.focus();
    press();
  };
  // Topo lines (Stephen 2026-10-26): the same switch as Map layers' Topo lines, kept per browser. Turned on only once
  // the server is found to have the contours (lib/topoLines.ts topoArchive, asked once a ride); otherwise said why.
  const topoOn = useTopoLines();
  const topoFound = useRef(false);
  const topoBusy = useRef(false);
  const toggleTopo = async () => {
    if (topoOn) {
      setTopoLines(false);
      answer(RIDE_TOPO_OFF);
      return;
    }
    if (topoBusy.current) return;
    if (!topoFound.current) {
      topoBusy.current = true;
      const found = await topoArchive();
      topoBusy.current = false;
      if (ended.current) return;
      if (found !== "yes") {
        answer(found === "offline" ? RIDE_TOPO_OFFLINE : TOPO_LINES_ROW_UNAVAILABLE);
        return;
      }
      topoFound.current = true;
    }
    setTopoLines(true);
    answer(RIDE_TOPO_ON);
  };
  const ease = async (which: Ease) => {
    const was = dialsRef.current;
    const next = eased(preset, was, which);
    if (!next) {
      answer(EASE_AT_END[which]);
      return;
    }
    if (tripRef.current.walking && approach) {
      answer(approachWords(approach, rideRef.current.fix?.point ?? null).spoken);
      return;
    }
    if (replanning || gate.busy) {
      answer(REPLAN_STILL_WAITING);
      return;
    }
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (!here) {
      answer(NO_FIX_YET);
      return;
    }
    dialsRef.current = next;
    setKeepPlanned(false);
    gate.online();
    answer(easeFinding(preset, next, which));
    const press = { which, ticket: replanTicket.current + 1, before: routeRef.current, outcome: "pending" as "pending" | "found" | "rejoin" };
    easing.current = press;
    await replan(here, undefined, true);
    if (easing.current === press) easing.current = null;
    // Undone when no route came, or only the way back to the old line; kept when a newer press, Road closed or Keep
    // the planned route took over (the ticket moved on): what comes next is planned with it.
    if (press.outcome !== "found" && replanTicket.current === press.ticket && dialsRef.current === next) dialsRef.current = was;
  };

  // Water or restroom on the way (the owner, 2026-10-10: "If navigating, water sources and restrooms can be
  // detours"): the three nearest by bike from the rider's position, on the ride's own settings; Detour here
  // re-plans through the chosen one. The position is the ride's own fix; nothing new is looked up.
  const detourBusy = useRef(false);
  // Stephen 2026-10-24: "Detours should include food too and anything that a user would search for", "repair stands
  // too": Food and Repair beside them, and a search box for anything else (lib/detourSearch.ts).
  const findDetour = async (ask: DetourAsk) => {
    if (detourBusy.current) {
      sayDetour(STILL_SEARCHING);
      return;
    }
    if (!water) return;
    detourBusy.current = true;
    setDetourList(null);
    sayDetour(detourFindingSaid(ask));
    try {
      const fix = rideRef.current.goodFix ?? rideRef.current.fix;
      if (!fix) {
        sayDetour(NO_FIX_YET);
        return;
      }
      const outcome = await searchDetour(
        {
          here: fix.point,
          water,
          food,
          repair,
          geocode,
          request: (from, places) => requestNearest(from, places, preset, { ...dialsRef.current, loop: false }),
        },
        ask,
      );
      if (ended.current) return;
      if (outcome.found) setDetourList(outcome.found);
      sayDetour(outcome.said);
    } finally {
      detourBusy.current = false;
    }
  };
  const detour = (item: Nearby) => {
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (!here) {
      sayDetour(NO_FIX_YET);
      return;
    }
    if (gate.busy) {
      sayDetour(DETOUR_BUSY);
      return;
    }
    setKeepPlanned(false);
    // The rider asked: not held back by the automatic re-plans' spacing.
    gate.online();
    setDetourList(null);
    setDetourOpen(false);
    // The list (and the pressed button) goes: the focus moves to Where am I?, not to the page's top.
    whereRef.current?.focus();
    sayDetour(t("Finding a way to {place}.", { place: item.place.title }));
    // The place is a stop of the new route, under its own name on the map and in the cues (2026-10-24).
    void replan(here, VIA_MARKS.named([item.place.point[0], item.place.point[1]], item.place.title));
  };

  // The next stop's two options (2026-10-24: "add the option to skip a stop or go to a different one"): Skip this stop
  // in More, Instead of stop N in the Detour menu, so the ride screen gains no button. Each is the rider's own ask, as
  // Detour here is. From More the focus stays on More (`fromMore`); from Detour it goes to Where am I?.
  const stopIndex = (stop: RideStopMark) => plan.current.points.indexOf(stop.point);
  // Restarting part way: the defaults ride on as the ride is; other picks plan again from here.
  const continueRestart = (done: ReadonlySet<number>) => {
    const stops = restart;
    restartOpen.current = false;
    setRestart(null);
    if (!stops || restartUnchanged(stops, done)) return;
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (!here) {
      sayDetour(NO_FIX_YET);
      return;
    }
    if (gate.busy) {
      sayDetour(DETOUR_BUSY);
      return;
    }
    setKeepPlanned(false);
    gate.online();
    sayDetour(restartReplanSaid(stops, done));
    // Back to a stop behind: turning round is the point, as after Road closed.
    const back = stops.some((s) => s.passed && !done.has(s.index));
    void replan(here, undefined, true, back, false, undefined, done);
  };
  const changeStop = (stop: RideStopMark, place?: { point: LonLat; title: string }, keepFocus = false) => {
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    const skip = stopIndex(stop);
    if (!here || skip < 0) {
      sayDetour(NO_FIX_YET);
      return;
    }
    if (gate.busy) {
      sayDetour(DETOUR_BUSY);
      return;
    }
    setKeepPlanned(false);
    gate.online();
    setDetourList(null);
    setDetourOpen(false);
    if (!keepFocus) whereRef.current?.focus();
    sayDetour(place ? insteadSaid(place.title, stop) : skippingSaid(stop));
    void replan(here, place ? VIA_MARKS.named([place.point[0], place.point[1]], place.title) : undefined, true, false, false, skip);
  };

  // The dock button's two ways (lib/rideDock.ts): the closest dock, or the one that adds least; the pick is a
  // detour stop, as Detour here's is. The menu closes and the focus goes back to the dock button.
  const dockBusy = useRef(false);
  const rideToDock = async (way: DockWay) => {
    setDockOpen(false);
    dockButton.current?.focus();
    if (dockBusy.current) {
      sayDetour(STILL_SEARCHING);
      return;
    }
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (!here) {
      sayDetour(NO_FIX_YET);
      return;
    }
    if (gate.busy) {
      sayDetour(DETOUR_BUSY);
      return;
    }
    dockBusy.current = true;
    sayDetour(dockFinding(way));
    try {
      const model = modelRef.current;
      const left = toGo(model, rideRef.current.progressM ?? 0);
      const end = model.coordinates[model.coordinates.length - 1] as LonLat;
      const outcome = await findDock(
        {
          here,
          end,
          remainingM: left.end.metres,
          docks: fetchDocks,
          request: (from, places) => requestNearest(from, places, preset, { ...dialsRef.current, loop: false }),
        },
        way,
      );
      if (ended.current) return;
      sayDetour(outcome.said);
      if (!outcome.ok) return;
      setKeepPlanned(false);
      gate.online();
      chosenDock.current = { point: outcome.dock.place.point, name: outcome.dock.place.title };
      void replan(here, outcome.dock.place.point);
    } finally {
      dockBusy.current = false;
    }
  };

  // Keys while the focus is in Ride mode (outside a text field): W or C where am I (and re-centre), T the text size. Only there
  // (WCAG 2.1.4), so speech input or a stray key elsewhere on the page fires neither.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (!target || !sectionRef.current?.contains(target)) return;
      // End ride's slide is a range: W and C still work there, as they did on its button.
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) && (target as HTMLInputElement).type !== "range";
      if (target.isContentEditable || typing) return;
      if (event.key === "w" || event.key === "W" || event.key === "c" || event.key === "C") {
        event.preventDefault();
        findMe();
      } else if (event.key === "t" || event.key === "T") {
        event.preventDefault();
        cycleText();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [findMe, cycleText]);

  const progress = ride.progressM;
  const cue = progress === null ? null : nextAction(model, progress);
  // The time to go at the rider's own pace against the plan's (lib/arrival.ts), and the clock it ends at.
  const togo = progress === null ? null : atPace(toGo(model, progress), paceFactor(paceRef.current));
  // A tick every 30 s keeps the clock times current while no fix comes (paused, in a tunnel); a fix renders sooner.
  const [, setClockTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setClockTick((n) => n + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const clockMs = Date.now();
  // The to-go words as shown, for the large text's fit: a minute's change can lengthen them ("9:59" to "10:00").
  const togoWords = [togo?.stop, togo?.end]
    .map((t) => (t && t.seconds !== null ? `${formatDuration(t.seconds)}${arrivalClock(clockMs, t.seconds)}`.length : 0))
    .join(",");
  const cueShown = cueParts(cue ? (cue.rideText ?? cue.text) : "");
  // A detour row's place ahead on the route or behind the rider, where the rider is on it (detourRowShown).
  const detourSide = (point: LonLat): "ahead" | "behind" | null => {
    if (progress === null || ride.off) return null;
    const at = snap(model, point);
    return at ? (at.alongM >= progress ? "ahead" : "behind") : null;
  };
  // The destination's name for "Arrived: ..." (a loop's end is its start: none).
  const destinationName = ride.arrived && !plan.current.loop ? (stopName?.(plan.current.points[plan.current.points.length - 1]) ?? null) : null;
  // The distance's metric in brackets a size smaller, so the line stays one line with large text.
  // A re-route's U-turn is now: no distance (it is at the line's start, behind the rider). One further along has its distance.
  const distanceWords = cue && progress !== null && !isStartUTurn(cue) ? formatDistance(cue.atM - progress) : "";
  const metricAt = distanceWords.indexOf(" (");
  const distanceShown = metricAt < 0 ? { us: distanceWords, metric: "" } : { us: distanceWords.slice(0, metricAt), metric: distanceWords.slice(metricAt + 1) };
  // Large: the turn's arrow and words as big as the card has room for (the owner, 2026-10-20: "take up as much
  // screen as possible"), set as --cue-fit on the card. Worked out when the turn, the size or the screen changes, not each
  // fix, with a little room left for the distance's words to grow; the small print stays 16 pt or more (styles.css).
  const cardRef = useRef<HTMLDivElement>(null);
  const fitKey = `${textSize}|${cueShown.head}|${cueShown.rest}|${distanceWords.length}|${ride.off}|${ride.arrived}|${cueSheetOn}|${settingsOpen}|${togoWords}`;
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    if (textSize === "normal") {
      card.style.removeProperty("--cue-fit");
      card.style.removeProperty("--cue-fit-d");
      // The instruction keeps its two-line slot, so the card and the map do not jump between turns (the UI review,
      // 2026-10-28): a long street shrinks to fit it, never under 16 px; longer still, its second line ends in "…".
      const line = card.querySelector<HTMLElement>(".cue-next .cue-text");
      const shown = line?.querySelector<HTMLElement>("[aria-hidden]");
      if (!line || !shown) return;
      const shrink = () => {
        line.style.removeProperty("font-size");
        if (shown.scrollHeight <= shown.clientHeight + 1) return;
        for (let px = Math.floor(parseFloat(getComputedStyle(line).fontSize)) - 1; px >= CUE_TEXT_MIN_PX; px -= 1) {
          line.style.fontSize = `${px}px`;
          // Clamped to two lines (styles.css): it fits once nothing is cut.
          if (shown.scrollHeight <= shown.clientHeight + 1) return;
        }
      };
      shrink();
      let stopped = false;
      void document.fonts?.ready.then(() => {
        if (!stopped) shrink();
      });
      return () => {
        stopped = true;
      };
    }
    // Large text sizes the instruction itself (--cue-fit): normal text's fitted size goes.
    card.querySelector<HTMLElement>(".cue-next .cue-text")?.style.removeProperty("font-size");
    // The ride's settings open in the card: the size stays as it was while they show.
    if (settingsOpen) return;
    // Two scales: the distance line's (and the arrow's), as big as its one line fits across and at most half the card
    // under the top row, whatever the cue says (the owner, 2026-10-20: "When there are multiple options the arrow and
    // distance shrink, which are the most important parts"); then the instruction's, as big as the card's height allows
    // under it. Where even the smallest words do not fit, To the end gives way (kept for screen readers).
    const set = (name: string, k: number) => card.style.setProperty(name, String(k));
    const inside = (selector: string) => {
      const right = card.getBoundingClientRect().right;
      return [...card.querySelectorAll<HTMLElement>(selector)].every((e) => e.scrollWidth <= e.clientWidth + 1 && e.getBoundingClientRect().right <= right + 1);
    };
    const fitsAll = () => card.scrollHeight <= card.clientHeight + 1 && card.scrollWidth <= card.clientWidth + 1;
    const largest = (ok: (k: number) => boolean) => {
      let lo = 0.5;
      let hi = 4;
      for (let i = 0; i < 9; i += 1) {
        const mid = (lo + hi) / 2;
        if (ok(mid)) lo = mid;
        else hi = mid;
      }
      return Math.floor(lo * 0.94 * 100) / 100;
    };
    const words = () =>
      set(
        "--cue-fit",
        largest((k) => {
          set("--cue-fit", k);
          return inside(".cue-text, .cue-more, .cue-then") && fitsAll();
        }),
      );
    const fit = () => {
      card.classList.remove("cue-crowded");
      set("--cue-fit", 0.5);
      const box = card.getBoundingClientRect();
      const top = [...card.querySelectorAll<HTMLElement>(":scope > .ride-top, :scope > .ride-light-below")].reduce((m, e) => Math.max(m, e.getBoundingClientRect().bottom), box.top);
      const below = box.bottom - top;
      const tall = () => [...card.querySelectorAll<HTMLElement>(".cue-shape, .cue-distance")].every((e) => e.getBoundingClientRect().height <= below / 2);
      const distance = largest((k) => {
        set("--cue-fit-d", k);
        return inside(".cue-distance") && tall();
      });
      set("--cue-fit-d", distance);
      words();
      if (fitsAll()) return;
      card.classList.add("cue-crowded");
      words();
    };
    fit();
    // Fitted again, once a frame at most, when the screen or the top row changes size, when a line comes or goes in the
    // card (off route's re-plan line, a departure's timer, the light times), and once the label face has loaded.
    let frame = 0;
    const again = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    };
    let stopped = false;
    void document.fonts?.ready.then(() => {
      if (!stopped) again();
    });
    const mutations = typeof MutationObserver === "undefined" ? null : new MutationObserver(again);
    mutations?.observe(card, { childList: true, subtree: true });
    const section = sectionRef.current;
    const top = card.querySelector(".ride-top");
    const sizes = new Map<Element, string>();
    const resized = typeof ResizeObserver === "undefined" ? null : new ResizeObserver((entries) => {
      let changed = false;
      for (const entry of entries) {
        const size = `${Math.round(entry.contentRect.width)}x${Math.round(entry.contentRect.height)}`;
        if (sizes.has(entry.target) && sizes.get(entry.target) !== size) changed = true;
        sizes.set(entry.target, size);
      }
      if (changed) again();
    });
    if (section) resized?.observe(section);
    if (top) resized?.observe(top);
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      mutations?.disconnect();
      resized?.disconnect();
    };
  }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // The light times for the corner, worked out once a minute and every tenth of a mile or so.
  const minute = Math.floor(Date.now() / 60_000);
  const lightStep = progress === null ? null : Math.round(progress / 160);
  const togoS = togo?.end.seconds ?? null;
  const light = useMemo(
    () => (lightStep === null || ride.arrived ? null : rideLightCorner(model, lightStep * 160, togoS, minute * 60_000)),
    [model, lightStep, togoS === null ? null : Math.round(togoS / 60), ride.arrived, minute], // eslint-disable-line react-hooks/exhaustive-deps
  );
  // Weather along the line still to ride (lib/weather.ts, Stephen 2026-10-24): checked at the start and every 5
  // minutes; a new NWS alert, or rain coming (first forecast, within 15 minutes, or turning heavy), said through the
  // rider's outputs and shown in the bottom panel until dismissed. Nothing asks and nothing waits.
  // Checked from the rider's place on the line, the last one known while off it; the first check waits for one.
  const weatherProgress = useRef(progress);
  if (progress !== null) weatherProgress.current = progress;
  const weatherReady = progress !== null || weatherProgress.current !== null;
  const weather = useWeather(
    ride.arrived || !weatherReady ? null : `ride:${model.lengthM}:${model.coordinates.length}`,
    () => {
      const from = weatherProgress.current;
      return from === null || !model.paceMs ? null : weatherPoints(model.coordinates, from, model.paceMs);
    },
    RIDE_WEATHER_MS,
  );
  const weatherSaid = useRef({ alerts: new Set<string>(), rain: "" });
  const [weatherDismissed, setWeatherDismissed] = useState(NOTHING_DISMISSED);
  useEffect(() => {
    if (!weather) return;
    const said = weatherSaid.current;
    const tell = (text: string, urgent: boolean) => {
      if (urgent) deliver({ text, urgent: true });
      else announcer.current?.note(text);
      if (prefsRef.current.output === "neither") setPolite((p) => ({ text, count: p.count + 1 }));
    };
    const fresh = newAlerts(weather, said.alerts);
    for (const alert of fresh) {
      said.alerts.add(alertKey(alert));
      tell(alertSaid(alert, Date.now()), alertUrgent(alert));
    }
    if (rainSays(said.rain, weather.rain) && weather.rain) tell(rainLine(weather.rain, weather.alongM, true), false);
    said.rain = rainStage(weather.rain);
  }, [weather, deliver]);
  // Shown until dismissed; again only for an alert not dismissed or rain at a new stage.
  const weatherShown = weatherToShow(weather, weatherDismissed);
  // "Ride mode" is for screen readers only and the two buttons fill the row (the owner, 2026-10-20: "People know it's
  // ride mode anyway"). Near dawn or dusk the light times take the corner while they fit beside the buttons on one
  // line, measured, as a phone's own text size can be larger than the page knows; else they go just under the row.
  const topRef = useRef<HTMLDivElement>(null);
  const [cornerFits, setCornerFits] = useState(true);
  const lightKey = light ? light.shown.join("|") : "";
  useLayoutEffect(() => {
    const top = topRef.current;
    const heading = headingRef.current;
    const actions = top?.querySelector<HTMLElement>(".ride-top-actions");
    if (!top || !heading || !actions) return;
    const check = () => {
      // Measured as laid out untight (the buttons not stretched), put back before anything is drawn.
      const tight = top.classList.contains("ride-corner-tight");
      if (tight) top.classList.remove("ride-corner-tight");
      const row = getComputedStyle(top);
      const room = top.clientWidth - parseFloat(row.paddingLeft) - parseFloat(row.paddingRight);
      const buttons = [...actions.children] as HTMLElement[];
      const between = parseFloat(getComputedStyle(actions).columnGap) || 0;
      const need =
        heading.scrollWidth + (parseFloat(row.columnGap) || 0) + buttons.reduce((sum, b) => sum + b.offsetWidth, 0) + between * Math.max(0, buttons.length - 1);
      if (tight) top.classList.add("ride-corner-tight");
      setCornerFits(need <= room);
    };
    check();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(check);
    watch.observe(top);
    for (const button of actions.children) watch.observe(button);
    return () => watch.disconnect();
  }, [lightKey, ride.arrived, walking, textSize]);
  // The riders and Alert chips sit just under the card, never over the turn's arrow and distance (as in Roam; the card's
  // height changes with the turn, the text size and the lines in it).
  useEffect(() => {
    const card = cardRef.current;
    const app = card?.closest<HTMLElement>(".app");
    if (!card || !app || typeof ResizeObserver === "undefined") return;
    const place = () => app.style.setProperty("--ride-card-bottom", `${Math.round(card.getBoundingClientRect().bottom - app.getBoundingClientRect().top)}px`);
    const watch = new ResizeObserver(place);
    watch.observe(card);
    place();
    return () => {
      watch.disconnect();
      app.style.removeProperty("--ride-card-bottom");
    };
  }, []);
  const back = ride.off ? wayBack(model, ride) : null;
  const shape = arrowFor(cue);
  const show311 = ride311Shown({ off: ride.off, progressM: progress });
  const place311 = show311 && progress !== null ? reportPlace(model, progress, trailMiles) : null;
  // A re-plan's outcome back on the route ("New route found.") shows by the side buttons for a few seconds; off
  // the route it stays in the bottom panel with Re-plan from here. Said either way (replan's tell).
  const offNow = ride.off;
  useEffect(() => {
    if (!replanNote || offNow) return;
    showToast(replanNote);
    setReplanNote("");
  }, [replanNote, offNow, showToast]);
  const notesShown = !!((gps && ride.fix) || paused || wakeNote || (ride.off && replanNote) || corridorText || weatherShown);
  const sheetShown = notesShown || ride.off || restShown;
  // The map's scales and credits sit at the bottom of the screen in a ride (the owner, 2026-10-17: "on the bottom
  // of the page in a ride"), just above the bottom panel while it shows (styles.css --ride-sheet-h).
  const sheetRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const sheet = sheetRef.current;
    const set = () => root.style.setProperty("--ride-sheet-h", `${sheet ? Math.round(sheet.getBoundingClientRect().height) : 0}px`);
    set();
    if (!sheet || typeof ResizeObserver === "undefined") return () => root.style.removeProperty("--ride-sheet-h");
    const observer = new ResizeObserver(set);
    observer.observe(sheet);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--ride-sheet-h");
    };
  }, [sheetShown]);

  // Off route, back on, or out of DC: the off-route buttons or the 311 block go, and a focus that was in
  // the one that went goes to Where am I?, so W and C keep working (review a11y-3; lib/rideFocus.ts). A
  // removed element fires no focusout, so the last focusin says where the focus was. The 311 menu closes
  // with its block.
  const block311 = useRef<HTMLDivElement>(null);
  const blockOff = useRef<HTMLDivElement>(null);
  const focusWasIn = useRef<RideBlock | null>(null);
  useEffect(() => {
    const onFocusIn = (event: globalThis.FocusEvent) => {
      focusWasIn.current = blockOf(event.target, { "311": block311.current, off: blockOff.current });
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);
  const shownBefore = useRef({ off: ride.off, show311 });
  useEffect(() => {
    const before = shownBefore.current;
    const now = { off: ride.off, show311 };
    shownBefore.current = now;
    if (before.off === now.off && before.show311 === now.show311) return;
    if (!show311) setMenu311(false);
    const active = document.activeElement;
    const focusLost = !active || active === document.body || !active.isConnected;
    if (rescueRideFocus({ focusWasIn: focusWasIn.current, before, now, focusLost })) {
      focusWasIn.current = null;
      whereRef.current?.focus({ preventScroll: true });
    }
  }, [ride.off, show311]);

  return (
    <section ref={sectionRef} className={`ride${textSize === "large" ? " ride-large" : ""}`} aria-labelledby="ride-heading">
      <LiveRegion said={polite} urgent={false} />
      <LiveRegion said={assertive} urgent />
      <div ref={cardRef} className="cue-card">
        {/* End ride (v0.7.0, "Go riding fixes" item 6): always in view, at the top of the card, which stays at
            every size and in Large text; one slide ends the ride (a tap once arrived), and the page shows the ride's summary
            with Done and Undo (RideSummaryCard). The ride's settings open just under the row, from the side buttons' More. */}
        <div ref={topRef} className={light && cornerFits ? "ride-top" : "ride-top ride-corner-tight"}>
          {/* The heading, "Ride mode", for screen readers; near dawn or dusk the light times shown in the corner
              (the owner, 2026-10-19) where they fit beside the buttons, else just under the row. */}
          <h2 id="ride-heading" ref={headingRef} tabIndex={-1} className={light ? "ride-heading ride-light" : "ride-heading"}>
            {light ? (
              <>
                <span className="visually-hidden">{t("Ride mode")}</span>
                <span className="ride-light-lines" aria-hidden="true">
                  {light.shown.map((line) => (
                    <span key={line}>{line}</span>
                  ))}
                </span>
              </>
            ) : (
              t("Ride mode")
            )}
          </h2>
          {light && <p className="visually-hidden">{light.said}</p>}
          <div className="ride-top-actions">
            {/* End ride first, then Road closed (the owner, 2026-10-19: "switch end ride and road closed"). Until the
                rider has arrived, End ride is slid, not tapped. */}
            {/* Once arrived, a filled Done (the UI review, 2026-10-28): the ride is over, so it reads as the next step,
                not a warning; its name says it ends the ride. */}
            {ride.arrived ? (
              <button type="button" className="primary ride-end ride-done" onClick={end}>
                <Icon name="check" size={22} />
                {RIDE_DONE_TEXT}
                <span className="visually-hidden">: {END_RIDE_NAME}</span>
              </button>
            ) : (
              <SlideToEnd onEnd={end} onTap={slideHint} />
            )}
            {/* Road closed (v0.8.2; in the top row since v0.9.0, the owner, 2026-10-18: "a button you'd want to hit
                on the fly"): one press while riding, no menu. */}
            {!walking && !ride.arrived && (
              <button type="button" className="secondary ride-road-closed" onClick={roadClosed} aria-label={ROAD_CLOSED_NAME} title={ROAD_CLOSED_NAME}>
                <Icon name="barrier" size={22} />
                {/* Always its words, at every size (the owner, 2026-10-20: "make everything have the big button"). */}
                <span className="ride-top-label">{ROAD_CLOSED_TEXT}</span>
              </button>
            )}
          </div>
        </div>
        {/* Where the corner has no room, the light times just under the top row, so they stay in view. */}
        {light && !cornerFits && (
          <p className="ride-light-below" aria-hidden="true">
            {light.shown.join(" · ")}
          </p>
        )}
        <div
          ref={settingsPanel}
          id={`${settingsId}-settings`}
          className="ride-mode-settings"
          role="group"
          aria-label={RIDE_SETTINGS_TITLE}
          hidden={!settingsOpen}
          tabIndex={-1}
          onKeyDown={(event) => {
            // Escape closes it, back to the Settings bubble.
            if (event.key === "Escape") {
              event.preventDefault();
              setSettingsOpen(false);
              settingsBubble.current?.focus();
            }
          }}
        >
          <h3 className="ride-settings-title">{t("Settings")}</h3>
          <RideSettingsFields prefs={prefs} onChange={onPrefs} idBase={settingsId} />
          {/* One line in view (the UI review, 2026-10-28), the whole of it under About Ride mode. */}
          <p className="hint">{RIDE_SAFETY_SHORT}</p>
          <details className="ride-safety-more">
            <summary>{t("About Ride mode")}</summary>
            <p className="hint">{RIDE_SAFETY}</p>
          </details>
          <label className="toggle ride-toggle">
            <input type="checkbox" checked={headingUp} onChange={(event) => onHeadingUp(event.target.checked)} />
            {t("Turn the map to my heading")}
          </label>
        </div>
        {ride.arrived ? (
          <>
            {/* "Arrived: Union Station" (the UI review, 2026-10-28); Done, in the top row, opens the summary. */}
            <p className="cue-text">{trip?.finish?.shown ?? arrivedShown(destinationName)}</p>
            {/* The boarding's departure, its countdown and milestones as in the trip's panel (said through the ride's outputs). */}
            {trip?.departure && <DepartureTimer departure={trip.departure} announce={notify} />}
            {/* Where the next Metro train or Metrobus is while waiting there (v0.9.0), its mark on the map. */}
            <NextVehicleLine ask={trip?.boarding ?? null} waiting={ride.arrived} announce={notify} onMark={setVehicle} />
          </>
        ) : walking && approach ? (
          <p className="cue-text">{approachWords(approach, ride.fix?.point ?? null).shown}</p>
        ) : ride.off ? (
          <div className="cue-off">
            <CueShape shape="warn" />
            <div>
              <p className="cue-text">{t("Off the planned route.")}</p>
              {replanning && <p className="cue-then">{t("Finding a new way from here…")}</p>}
              {(keepPlanned || fixedRef.current) && back && (
                <p className="cue-then">
                  {t("The planned route is {distance} to the {direction}.", { distance: formatDistance(back.metres), direction: back.direction })}
                </p>
              )}
            </div>
          </div>
        ) : cueSheetOn ? (
          // GPS weak for long (cueSheetShown): the turns ahead from the last good place, in order, the
          // next first; a list a screen reader reads as one, with no control of its own.
          <div className="cue-sheet">
            <p id={cueSheetId} className="cue-then">
              {t("Turns ahead, in order:")}
            </p>
            <ol className="cue-sheet-list" aria-labelledby={cueSheetId}>
              {/* Three short rows on screen (distance · turn · street, the UI review 2026-10-28); each row's whole
                  sentence, and the rows after them, for screen readers. */}
              {cueSheet(model, progress ?? 0).map((row, i) => (
                <li
                  key={row.index}
                  className={i === 0 ? "cue-sheet-next" : i >= CUE_SHEET_SHOWN ? "visually-hidden" : undefined}
                  aria-current={i === 0 ? "step" : undefined}
                >
                  <span aria-hidden="true">{row.shown}</span>
                  <span className="visually-hidden">
                    {row.distance}: {row.text}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : cue && progress !== null ? (
          <div className="cue-next">
            <CueShape shape={shape} junction={cue.junction} exit={cue.exit?.number} jog={cue.cross ? null : jogArrowPath(cue)} />
            <div>
              {/* Greyed while GPS is weak or lost (any GPS note): the distance is from an old fix, not where the rider is. */}
              <p className={gps ? "cue-distance cue-distance-weak" : "cue-distance"}>
                {/* Fewer words, larger type (the owner, 2026-10-20); "In" stays for screen readers. */}
                {distanceShown.us && <span className="visually-hidden">{t("In")} </span>}
                {distanceShown.us}
                {distanceShown.metric && <span className="cue-distance-metric"> {distanceShown.metric}</span>}
              </p>
              {/* The instruction large, the rest in small print, street words shortened; the whole sentence for screen readers. */}
              <p className="cue-text">
                <span aria-hidden="true">{cueShown.head.replace(/\.$/, "")}</span>
                <span className="visually-hidden">{cue.rideText ?? cue.text}</span>
              </p>
              {/* At most one short line, always there (empty too), so the card keeps its height between turns. */}
              <p className="cue-more" aria-hidden="true">
                {cueShown.rest}
              </p>
              {cue.citation && <p className="cue-citation">{cue.citation}</p>}
            </div>
          </div>
        ) : (
          <p className="cue-text">{gps || "Finding your place on the route."}</p>
        )}
        {togo && !ride.arrived && (
          <dl className="ride-togo">
            {togo.stop && (
              <div>
                <dt>{t("To stop {number}", { number: togo.stop.number })}</dt>
                <dd>
                  {formatDistance(togo.stop.metres)}
                  {togo.stop.seconds !== null && <TimeToGo seconds={togo.stop.seconds} nowMs={clockMs} />}
                </dd>
              </div>
            )}
            <div className="ride-togo-end">
              <dt>{t("To the end")}</dt>
              <dd>
                {formatDistance(togo.end.metres)}
                {togo.end.seconds !== null && <TimeToGo seconds={togo.end.seconds} nowMs={clockMs} />}
              </dd>
            </div>
          </dl>
        )}
      </div>

      {/* The side buttons (the owner, 2026-10-17: "put these as circle icons on the side"), over the map on the
          right at thumb height; each menu opens beside them. An answer the rider asked for shows to their left. */}
      <div className="ride-middle">
        {/* A minimalist compass (the owner, 2026-10-17), turned with the map; a press switches north-up and track-up
            ("maybe clicking on it changes to north up"), the same choice as the ride settings' switch. */}
        <button type="button" className="ride-compass" aria-pressed={!headingUp} aria-label={t("North up")} title={t("North up")} onClick={() => onHeadingUp(!headingUp)}>
          <svg viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
            <path d="M20 5 L25 20 L20 17 L15 20 Z" className="ride-compass-north" />
            <path d="M20 35 L15 20 L20 23 L25 20 Z" className="ride-compass-south" />
          </svg>
        </button>
        {toast.text && !detourOpen && !dockOpen && !menu311 && !moreOpen && (
          <div className="ride-toast" {...toastTimer.hold}>
            {/* Shown, not a live region: it is said through the rider's own outputs. */}
            <p key={toast.n}>{toast.text}</p>
          </div>
        )}
        {/* Each button's word under it, or beside its icon where the map is short (lib/railFit.ts); its name unchanged. */}
        <div ref={railRef} className={`ride-rail ride-rail-${railFit}`} role="group" aria-label={t("Ride buttons")}>
          {/* Where am I? with Re-centre in it (the owner, 2026-10-20): highlighted when the map stopped following. */}
          <button
            type="button"
            ref={whereRef}
            className={`ride-round${follow ? "" : " ride-round-alert"}`}
            onClick={findMe}
            aria-keyshortcuts="W C"
            aria-label={follow ? t("Where am I?") : t("Where am I? The map stopped following you")}
            title={t("Where am I?")}
          >
            <Icon name="locate" size={24} />
            <span className="ride-word" aria-hidden="true">{t("Locate")}</span>
          </button>
          {/* Large text on and off (the owner, 2026-10-20), shown pressed while on. */}
          <button
            type="button"
            className="ride-round ride-text-size"
            onClick={cycleText}
            aria-keyshortcuts="T"
            aria-pressed={textSize === "large"}
            aria-label={RIDE_TEXT_BUTTON}
            title={RIDE_TEXT_BUTTON}
          >
            <Icon name="textsize" size={24} />
            <span className="ride-word" aria-hidden="true">{t("Text")}</span>
          </button>
          {/* Broadcast (Stephen 2026-10-24: "Let people broadcast from a ride"): as Roam's, shown on while this rider leads. */}
          {onBroadcast && !ride.arrived && (
            <button
              type="button"
              className={`ride-round broadcast-hold${broadcasting ? " ride-round-on" : ""}`}
              onClick={() => void broadcast()}
              {...broadcastHold}
              aria-describedby={onBroadcastHold ? broadcastHoldId : undefined}
              aria-label={`${broadcasting ? t("{name}: on. Share the link again", { name: RIDE_BROADCAST_NAME }) : passingOn ? t("{name}: pass on the link to this ride", { name: RIDE_BROADCAST_NAME }) : t("{name}: share a link others follow you with", { name: RIDE_BROADCAST_NAME })}${riders === null ? "" : `. ${countText(riders)}`}`}
              title={RIDE_BROADCAST_NAME}
            >
              <Icon name="broadcast" size={riders === null ? 24 : 20} />
              {riders !== null && (
                <span className="ride-round-count" aria-hidden="true">
                  <Icon name="user" size={12} />
                  {riders}
                </span>
              )}
              <span className="ride-word" aria-hidden="true">{t("Share live")}</span>
            </button>
          )}
          {onBroadcast && onBroadcastHold && (
            <span id={broadcastHoldId} className="visually-hidden">
              {BROADCAST_HOLD_HINT}
            </span>
          )}
          {water && (
            <div
              className="ride-pop ride-detour"
              onKeyDown={(event) => {
                if (event.key === "Escape" && detourOpen) {
                  event.preventDefault();
                  setDetourOpen(false);
                  detourButton.current?.focus();
                }
              }}
            >
              <button
                type="button"
                ref={detourButton}
                className="ride-round"
                aria-label={detourButtonName(DETOUR_SUMMARY, fixed ? null : nextStop)}
                title={t("Detour")}
                aria-expanded={detourOpen}
                aria-controls={detourId}
                data-idle-close
                onClick={() => openMenu(detourOpen ? null : "detour")}
              >
                <Icon name="detour" size={24} />
                <span className="ride-word" aria-hidden="true">{t("Detour")}</span>
              </button>
              <div id={detourId} className="ride-menu" role="group" aria-labelledby={`${detourId}-heading`} hidden={!detourOpen}>
                <div className="ride-menu-head">
                  <h3 id={`${detourId}-heading`} ref={detourHeading} tabIndex={-1}>
                    {t("Detour")}
                  </h3>
                  <button
                    type="button"
                    className="secondary ride-menu-close"
                    onClick={() => {
                      setDetourOpen(false);
                      detourButton.current?.focus();
                    }}
                  >
                    {t("Close")}
                  </button>
                </div>
                {detourKind === null ? (
                  <div className="actions nearest-kinds" ref={detourKinds}>
                    {DETOUR_CHOICES.map(({ kind, label, icon }) => (
                      <button
                        key={kind}
                        type="button"
                        className="secondary"
                        onClick={() => {
                          pickedFocus.current = "change";
                          setDetourKind(kind);
                          void findDetour({ kind });
                        }}
                      >
                        <Icon name={icon} size={20} />
                        {label}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="detour-picked">
                    <strong>{DETOUR_CHOICES.find((c) => c.kind === detourKind)?.label}</strong>{" "}
                    <button
                      type="button"
                      ref={detourChange}
                      className="link"
                      aria-label={t("Change what to find")}
                      onClick={() => {
                        pickedFocus.current = "kinds";
                        setDetourKind(null);
                      }}
                    >
                      {t("Change")}
                    </button>
                  </p>
                )}
                <form
                  className="detour-search"
                  role="search"
                  onSubmit={(event) => {
                    event.preventDefault();
                    // The focus moves to Find, so a phone's keyboard goes and does not cover the list that comes.
                    event.currentTarget.querySelector<HTMLButtonElement>("button[type=submit]")?.focus();
                    void findDetour({ query: detourQuery });
                  }}
                >
                  <label htmlFor={`${detourId}-search`}>{DETOUR_SEARCH_LABEL}</label>
                  <span className="detour-search-row">
                    <input
                      id={`${detourId}-search`}
                      type="search"
                      enterKeyHint="search"
                      autoComplete="off"
                      placeholder={DETOUR_SEARCH_HINT}
                      value={detourQuery}
                      onChange={(event) => setDetourQuery(event.target.value)}
                    />
                    <button type="submit" className="secondary">
                      <Icon name="search" size={20} />
                      {DETOUR_SEARCH_BUTTON}
                    </button>
                  </span>
                </form>
                {/* Shown, not a live region: what it says is said through the ride's own outputs (sayDetour). */}
                <p className="hint nearest-status">{detourStatus}</p>
                {detourList && detourList.items.length > 0 && (
                  <div className="nearest-list">
                    <h4 id={`${settingsId}-detour`}>{detourList.heading}</h4>
                    <ol role="list" aria-labelledby={`${settingsId}-detour`}>
                      {detourList.items.map((item) => (
                        <li key={item.place.id}>
                          {/* Short on screen (the name, how far, ahead or behind), the whole line for screen readers. */}
                          <span aria-hidden="true">{detourRowShown(item, detourSide(item.place.point))}</span>
                          <span className="visually-hidden">{nearbyText(item)}</span>
                          <span className="actions">
                            <button
                              type="button"
                              className="secondary"
                              aria-label={t("Detour here: {place}", { place: item.place.title })}
                              onClick={() => detour(item)}
                            >
                              {t("Detour here")}
                            </button>
                            {nextStop && !fixed && (
                              <button
                                type="button"
                                className="secondary"
                                aria-label={insteadName(item.place.title, nextStop)}
                                onClick={() => changeStop(nextStop, item.place)}
                              >
                                {insteadLabel(nextStop)}
                              </button>
                            )}
                          </span>
                        </li>
                      ))}
                    </ol>
                    {(detourList.kind === "water" || detourList.kind === "restroom") && <p className="hint">{WATER_CAUTION}</p>}
                    {detourList.attribution && <p className="hint">Search: {detourList.attribution.join("; ")}</p>}
                  </div>
                )}
                {/* Said once by screen readers; no longer shown under every list (the UI review, 2026-10-28). */}
                <p className="visually-hidden">{DETOUR_HELP}</p>
              </div>
            </div>
          )}
          {/* A share bike only (lib/rideDock.ts): its own detour, to a dock, with the rough time undocked on it. */}
          {shareBike && !ride.arrived && (
            <div
              className="ride-pop ride-dock"
              onKeyDown={(event) => {
                if (event.key === "Escape" && dockOpen) {
                  event.preventDefault();
                  setDockOpen(false);
                  dockButton.current?.focus();
                }
              }}
            >
              <button
                type="button"
                ref={dockButton}
                className="ride-round ride-dock-button"
                aria-label={docked ? `${DOCK_NAME}. ${DOCKED_SHOWN}.` : dockButtonName(undockAt === null ? null : undockedMinutes(undockAt, now))}
                title={DOCK_NAME}
                aria-expanded={dockOpen}
                aria-controls={dockId}
                data-idle-close
                onClick={() => openMenu(dockOpen ? null : "dock")}
              >
                <Icon name="bikeshare" size={20} />
                {undockAt !== null && <span aria-hidden="true">{docked ? DOCKED_SHOWN : undockedShown(undockedMinutes(undockAt, now))}</span>}
                <span className="ride-word" aria-hidden="true">{t("Dock")}</span>
              </button>
              <div id={dockId} className="ride-menu" role="group" aria-labelledby={`${dockId}-heading`} hidden={!dockOpen}>
                <div className="ride-menu-head">
                  <h3 id={`${dockId}-heading`} ref={dockHeading} tabIndex={-1}>
                    {DOCK_NAME}
                  </h3>
                  <button
                    type="button"
                    className="secondary ride-menu-close"
                    onClick={() => {
                      setDockOpen(false);
                      dockButton.current?.focus();
                    }}
                  >
                    {t("Close")}
                  </button>
                </div>
                {undockAt !== null && (
                  <p className="hint">{docked ? t("Docked at {dock}.", { dock: docked }) : t("Undocked about {time}.", { time: undockedShown(undockedMinutes(undockAt, now)) })}</p>
                )}
                <ul className="ride-menu-choices" role="list">
                  {DOCK_WAYS.map(({ way, label, hint }) => (
                    <li key={way}>
                      <button type="button" className="ride-menu-choice" onClick={() => void rideToDock(way)}>
                        <strong>{label}</strong>
                        <span>{hint}</span>
                      </button>
                    </li>
                  ))}
                  {undockAt !== null && (
                    <li>
                      <button
                        type="button"
                        className="secondary ride-menu-restart"
                        onClick={() => {
                          restartTime();
                          setDockOpen(false);
                          dockButton.current?.focus();
                          sayDetour(TIME_RESTARTED);
                        }}
                      >
                        {RESTART_TIME}
                      </button>
                    </li>
                  )}
                </ul>
              </div>
            </div>
          )}
          {/* The 311 button (lib/ride311.ts): anywhere on the route; its menu beside the buttons. */}
          {show311 && (
            <div className="ride-311" ref={block311} onKeyDown={(event) => {
              if (event.key === "Escape" && menu311) {
                event.preventDefault();
                close311();
              }
            }}>
              <button
                type="button"
                ref={button311}
                className="ride-311-button"
                aria-label={RIDE_311_NAME}
                aria-expanded={menu311}
                aria-controls={menu311Id}
                data-idle-close
                onClick={() => openMenu(menu311 ? null : "311")}
              >
                <Icon name="flag" size={18} />
                <span aria-hidden="true">{RIDE_311_TEXT}</span>
              </button>
              <Ride311Menu
                id={menu311Id}
                open={menu311}
                place={place311}
                headingRef={menu311Heading}
                onPick={pick311}
                onClose={close311}
              />
              {said311Shown && (
                <div className="ride-311-said" {...said311Timer.hold}>
                  {/* Shown, not a live region: it is said through the rider's own outputs (tell311). */}
                  <p>{said311}</p>
                </div>
              )}
            </div>
          )}
          {/* More, at the end of the side buttons (a gear for the settings since v0.9.0, the owner, 2026-10-18: "Move
              settings to a gear icon in the rack"; More since 2026-10-24). It opens a row of bubbles to its left
              (Stephen 2026-10-26): the route's changes, each one press, a new route from here (not on a route everyone
              shares, `fixed`, nor once arrived), the symbols alone on screen (2026-10-23: "Symbol should be clear"),
              Topo lines on or off (2026-10-26, always there: it changes the map, not the route), and Settings, opening
              the ride's settings under the top row. */}
          <div
            className="ride-pop ride-more"
            onKeyDown={(event) => {
              // Escape in the bubbles closes them, back to More.
              if (event.key === "Escape" && moreOpen) {
                event.preventDefault();
                setMoreOpen(false);
                setSettingsOpen(false);
                settingsButton.current?.focus();
              }
            }}
          >
            <button
              type="button"
              ref={settingsButton}
              className="ride-round ride-settings-button"
              aria-label={RIDE_MORE_NAME}
              title={RIDE_SETTINGS_TEXT}
              aria-expanded={moreOpen}
              aria-controls={`${settingsId}-more`}
              data-idle-close
              onClick={toggleMore}
            >
              <Icon name="more" size={24} />
              <span className="ride-word" aria-hidden="true">{RIDE_SETTINGS_TEXT}</span>
            </button>
            <div id={`${settingsId}-more`} className="ride-more-bubbles" role="group" aria-label={RIDE_MORE_NAME} hidden={!moreOpen}>
              {!fixed &&
                !ride.arrived &&
                (["calmer", "flatter"] as const).map((which) => (
                  <button
                    key={which}
                    type="button"
                    className={`ride-round ride-ease ride-${which}`}
                    onClick={() => fromMore(() => void ease(which))}
                    aria-label={EASE_NAME[which]}
                    title={EASE_SHOWN[which]}
                  >
                    <Icon name={which === "calmer" ? "traffic-down" : "hills-down"} size={26} />
                    <span className="ride-word" aria-hidden="true">{EASE_WORD[which]}</span>
                  </button>
                ))}
              {!fixed && !ride.arrived && nextStop && (
                <button
                  type="button"
                  className="ride-round ride-skip-stop"
                  onClick={() => fromMore(() => changeStop(nextStop, undefined, true))}
                  aria-label={skipStopName(nextStop)}
                  title={SKIP_STOP}
                >
                  <Icon name="skip" size={22} />
                  <span aria-hidden="true">{nextStop.number}</span>
                  <span className="ride-word" aria-hidden="true">{t("Skip")}</span>
                </button>
              )}
              {onRiders && riders !== null && (
                <button type="button" className="ride-round ride-riders-bubble" onClick={() => fromMore(onRiders)} aria-label={`${RIDERS_NAME}: ${countText(riders)}`} title={RIDERS_NAME}>
                  <Icon name="user" size={22} />
                  <span aria-hidden="true">{riders}</span>
                  <span className="ride-word" aria-hidden="true">{RIDERS_NAME}</span>
                </button>
              )}
              <button
                type="button"
                className="ride-round ride-topo"
                onClick={() => fromMore(() => void toggleTopo())}
                aria-label={TOPO_LINES_LABEL}
                aria-pressed={topoOn}
                title={TOPO_LINES_LABEL}
              >
                <Icon name="topo" size={24} />
                <span className="ride-word" aria-hidden="true">{t("Topo")}</span>
              </button>
              <button
                type="button"
                ref={settingsBubble}
                className="ride-round ride-settings-bubble"
                aria-label={RIDE_SETTINGS_TITLE}
                title={RIDE_SETTINGS_TITLE}
                aria-expanded={settingsOpen}
                aria-controls={`${settingsId}-settings`}
                onClick={() => setSettingsOpen(!settingsOpen)}
              >
                <Icon name="gear" size={24} />
                <span className="ride-word" aria-hidden="true">{t("Settings")}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* The bottom panel, only when it has something to say or ask (the owner: "Remove that bottom part when
          routing by default"): the notes, off route, Ride the rest, and the full 311 report once asked for. */}
      {sheetShown && (
        <div ref={sheetRef} className="ride-controls">
          {notesShown && (
            <div className="ride-notes">
              {gps && ride.fix && <p className="hint">{gps}</p>}
              {corridorText && <p className="hint ride-corridor">{corridorText}</p>}
              {weatherShown && <WeatherLines report={weatherShown} riding now={Date.now()} onDismiss={() => { setWeatherDismissed((d) => dismissWeather(weatherShown, d)); headingRef.current?.focus({ preventScroll: true }); }} />}
              <ScreenSleepNote note={wakeNote} kind={phone} />
              {ride.off && replanNote && <p className="hint">{replanNote}</p>}
              {paused && (
                <p className="notice">
                  {PAUSED_SAID}{" "}
                  <button type="button" onClick={resume}>
                    {t("Resume")}
                  </button>
                </p>
              )}
            </div>
          )}
          {ride.off && (
            <div className="actions ride-off-actions" ref={blockOff}>
              <button type="button" onClick={replanNow} aria-disabled={replanning}>
                {t("Re-plan from here")}
              </button>
              {/* A fixed route is always kept: no Keep to press. */}
              {!fixedRef.current && (
                <button type="button" className="secondary" onClick={keep} aria-pressed={keepPlanned}>
                  {t("Keep the planned route")}
                </button>
              )}
            </div>
          )}
          {restShown && (
            <div className="actions ride-rest">
              <button type="button" onClick={rideTheRest} aria-describedby={`${settingsId}-rest`}>
                {RIDE_REST}
              </button>
              <p id={`${settingsId}-rest`} className="hint">
                {RIDE_REST_HINT}
              </p>
            </div>
          )}
        </div>
      )}
      <RestartStopsDialog stops={restart} onContinue={continueRestart} />
    </section>
  );
}
