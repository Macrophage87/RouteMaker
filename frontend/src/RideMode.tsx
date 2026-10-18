/**
 * Ride mode (WEB-NAV-plan.md; OWNER-DECISIONS 255, 434, 465): follow a planned route on a phone with the
 * screen on and the page in front. The engine is lib/navigate.ts; the outputs, the throttle and the wake
 * lock are lib/rideOutput.ts; the one position watch is lib/rideWatch.ts. This component wires them to
 * the screen:
 *
 * - The cue card: the next turn, flagged junction or stop, its distance (US units first, metric in
 *   brackets) and the API's sentence for it. Not a live region: it changes with every fix.
 * - To go: distance and time to the next stop and to the end, at the route's own pace.
 * - Two live regions of its own, polite for advance cues and assertive for "now", leaving the route
 *   and arrival; each repeats the count trick so the same sentence twice is said twice. A cue never
 *   moves the focus.
 * - Where am I? (a button, and the W key): said on demand, outside the throttle.
 * - Off route: re-planned automatically after the gate (plan Q5), or "Keep the planned route", which
 *   shows the way back. A fixed route (`fixed`: a link shared as a ride, or a Mass Ride or Group Ride not shared as a route)
 *   is never re-planned on its own: everyone on it stays on the same line, and the way back is shown instead. A re-plan never touches the plan in the address bar (plan Q2): it is the ride's
 *   own route, held here and in App's ride state only.
 * - Big text (map hidden; a setting, in the ride's Settings and the Settings page), Re-centre (and the C key), heading-up (track-up by default since v0.7.0); and
 *   Settings and End ride always in view at the top of the card (Settings opens the ride's settings just
 *   under it), with Undo after End ride. End ride part way leaves the plan starting where the rider is.
 * - The map along the route, kept for dead spots (lib/corridor.ts, N5), and Report a problem to DC 311
 *   with the place in the route's street names (lib/report311.ts, N6; OWNER-DECISIONS 369, 465).
 * - The side buttons (the owner, 2026-10-17: "Remove that bottom part when routing by default. instead put
 *   these as circle icons on the side"): Where am I?, Re-centre, Road closed ahead, Detour (water or restroom), on a
 *   share bike the dock button with the time undocked (lib/rideDock.ts), and 311 inside DC (Big text moved to
 *   Settings, the owner, 2026-10-17: "not something people will fiddle with mid ride"); each a round
 *   icon with its name for screen readers, its menu opening beside it. The bottom panel shows only when it
 *   has something to say or ask: GPS and screen notes, off route, Ride the rest, the full 311 report.
 *   Answers asked for (Where am I?, a detour's progress) show for a few seconds by the buttons.
 *
 * Privacy (plan section 7): positions stay in memory for the ride; nothing is stored or logged; the only
 * ones sent are a re-plan's start point and, when the rider asks for the nearest water or restroom, the
 * search's own (POST /api/nearest), each in a POST body, as planning with "Use my location" sends it.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type FocusEvent, type PointerEvent, type RefObject } from "react";
import { HoldTimer } from "./lib/holdTimer.ts";
import { startsWayBack, wayBackRoute } from "./lib/rejoin.ts";
import {
  ON_DETOUR_SAID,
  ON_STANDARD_SAID,
  ROAD_CLOSED_FINDING,
  ROAD_CLOSED_NAME,
  ROAD_CLOSED_NO_PLACE,
  closedAhead,
  onOtherLine,
  withClosed,
} from "./lib/roadClosed.ts";
import { requestRoute, type RouteResponse } from "./lib/api.ts";
import { VIA_MARKS, viaIndices } from "./lib/pointKinds.ts";
import type { Dials } from "./lib/dials.ts";
import { haversineM, insideCoverage, type LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import { formatDistance, formatDuration, spokenDistance } from "./lib/format.ts";
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
  REPLAN_UTURN,
  setsOffBack,
  withUTurn,
  REPLAN_NO_SIGNAL,
  REPLAN_REJOIN,
  REPLAN_FINDING,
  REPLAN_STILL_WAITING,
  ReplanGate,
  VERBOSITY_LABELS,
  cueSpoken,
  nextAction,
  planAfterEnd,
  pointAt,
  replanKept,
  replanPoints,
  replanTold,
  rideModel,
  startState,
  toGo,
  wayBack,
  whereAmI,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./lib/navigate.ts";
import {
  Announcer,
  BIG_TEXT_NAME,
  OUTPUT_LABELS,
  ScreenWake,
  Voice,
  toScreenReader,
  toVoice,
  type CueOutput,
  type RidePrefs,
  type Said,
} from "./lib/rideOutput.ts";
import { WAITING_FOR_GPS, watchRide, type RideGeoEnv } from "./lib/rideWatch.ts";
import { rideGeoEnv, rideSpeech, rideWake, ridesHidden, showCue, speaksAloud } from "./lib/nativeShell.ts";
import {
  DETOUR_BUSY,
  DETOUR_FULL,
  DETOUR_HELP,
  DETOUR_KINDS,
  DETOUR_SUMMARY,
  NEAREST_KINDS,
  NO_FIX_YET,
  STILL_SEARCHING,
  detourPoints,
  findingSaid,
  nearbyText,
  nounOf,
  requestNearest,
  rideLocate,
  searchNearest,
  type Found,
  type Nearby,
  type NearestKind,
} from "./lib/nearest.ts";
import type { WaterPoint } from "./lib/waterRestrooms.ts";
import type { TrailMiles } from "./lib/trailMiles.ts";
import { WATER_CAUTION } from "./lib/waterRestrooms.ts";
import { corridorWorry, type PrefetchResult } from "./lib/corridor.ts";
import { clearCorridor, copyCorridor, keepCorridor } from "./lib/corridorStore.ts";
import { lastRideAdopter } from "./lib/offlineKeep.ts";
import { blockOf, rescueRideFocus, type RideBlock } from "./lib/rideFocus.ts";
import { inDc } from "./lib/dcBoundary.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import {
  DC_311_ONLINE,
  REPORT_KINDS,
  REPORT_NOTE_MAX,
  REPORT_NO_PLACE,
  REPORT_OFF_ROUTE,
  REPORT_OUTSIDE_DC,
  REPORT_PRIVACY,
  REPORT_PRIVACY_SERVER,
  REPORT_FORM,
  REPORT_READY,
  REPORT_SEND_FAILED,
  REPORT_SENT,
  pickWay,
  report311Enabled,
  sendReport311,
  REPORT_SUMMARY,
  SHORT_CODE_SPOKEN,
  canText,
  keywordOf,
  onlineHint,
  reportPlace,
  reportText,
  smsHref,
  type ReportKind,
} from "./lib/report311.ts";
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
import { DepartureTimer } from "./DepartureTimer.tsx";
import { NextVehicleLine } from "./NextVehicleLine.tsx";
import type { VehicleMark } from "./lib/nextVehicle.ts";
import { SettingRow, SettingSelect } from "./SettingRow.tsx";
import { shortLabel } from "./lib/shortLabel.ts";
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

/**
 * One voice for the page: the Start ride press unlocks it (iOS speaks only after a gesture has). Web
 * Speech in a browser; in the phone app (v0.8.0), the native voice, which goes on with the screen locked.
 */
export const rideVoice = new Voice(rideSpeech());

/** Said as the ride starts, inside the Start press, so the voice is unlocked by it. */
export const RIDE_STARTED = "Ride started.";
export const RIDE_ENDED = "Ride ended.";
/** The always-visible End ride button's words (the owner, 2026-10-16: "add a method of ending navigation"). */
export const END_RIDE_NAME = "End ride";
/** The top row's Settings button opens these, just under it (the owner, 2026-10-16: "the buttons to change the settings seem hidden"). */
export const RIDE_SETTINGS_TEXT = "Settings";
export const RIDE_SETTINGS_TITLE = "Ride settings";
/** What End ride leaves behind (lib/navigate.ts planAfterEnd): the plan from here, or as it was. */
export type EndedPlan = ReturnType<typeof planAfterEnd>;
/** How long Undo is offered after End (v0.7.0, "Go riding fixes" item 6); held while it has the focus. */
export const UNDO_END_MS = 8_000;
/** How long the 311 line ("Sent to DC 311." and Add a note) stays (review F4); held the same way. */
export const SAID_311_MS = 8_000;
/** Said by the page's polite region (always mounted) as Ride ended shows (review F6). */
export const RIDE_ENDED_SAID = "Ride ended. Undo available.";
/** Said instead where End ride came part way (lib/navigate.ts planAfterEnd): the plan now starts where the rider is. */
export const RIDE_ENDED_FROM_HERE_SAID = "Ride ended. The route now starts where you are. Undo available.";
/** Part way with no recent location: the plan keeps its start, and the rider is told. */
export const RIDE_ENDED_NO_FIX_SAID = "Ride ended. Route start unchanged. Undo available.";

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
export const PAUSED_SAID = "Ride paused while the page was in the background. Press Resume to carry on.";
/** A re-plan that has not answered in this long is said as no signal (a hung connection); its answer still counts. */
export const REPLAN_TIMEOUT_MS = 25_000;
/** No fix for this long and a failure from the watch: the rider is told (once) that GPS is lost. */
export const GPS_LOST_MS = 30_000;
export const GPS_LOST_SAID = "No GPS signal: the cues are paused until it comes back.";

/** The rider's responsibility and the battery, said before the first ride (plan sections 5 and 10). */
export const RIDE_SAFETY_BROWSER =
  "Ride mode guides you along the planned route; you stay responsible for riding safely and obeying the rules of the road, and the route can be wrong. It needs the screen on and this page in front, and GPS with a lit screen drains the battery quickly.";
/** In the phone app (v0.8.0) the cues go on with the screen locked, so the screen sentence is not said. */
export const RIDE_SAFETY_APP =
  "Ride mode guides you along the planned route; you stay responsible for riding safely and obeying the rules of the road, and the route can be wrong. In this app the cues go on with the screen locked until you end the ride, and GPS drains the battery.";
export const RIDE_SAFETY = ridesHidden() ? RIDE_SAFETY_APP : RIDE_SAFETY_BROWSER;

/** Called inside the Start ride press: unlock the voice with the first sentence, where the rider chose it. */
export function startRideGesture(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(RIDE_STARTED);
}

/** Start's press, before its closure check: unlocks the voice silently (iOS speaks only after a
 * gesture has spoken once), so "Ride started." is said only when the ride does start. */
export function primeRideVoice(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(" ");
}

export const VOICE_ON = "Voice on.";

/** Called inside the press that changes the ride's outputs: a voice newly chosen is unlocked there (iOS). */
export function voiceTurnedOn(before: RidePrefs, next: RidePrefs, voice: Pick<Voice, "unlock"> = rideVoice): void {
  if (!toVoice(before.output) && toVoice(next.output)) voice.unlock(VOICE_ON);
}

/** Said politely when Start's closure check takes more than a moment (CLOSURE_SLOW_MS). */
export const CHECKING_CLOSURES = "Checking closures…";
export const CLOSURE_SLOW_MS = 600;

/** What App shows on the map for the ride. */
export interface RideView {
  route: RouteResponse;
  /** The other line (v0.8.2): the standard way through a marked closure, or its detour while on the standard way. */
  other?: LonLat[] | null;
  rider: { point: LonLat; headingDeg: number | null; accuracyM: number } | null;
  /** Where the next train or bus is while the rider waits at a Metro or Metrobus boarding (v0.9.0). */
  vehicle?: VehicleMark | null;
}

function arrowFor(cue: Cue | null): "left" | "right" | "bear_left" | "bear_right" | "uturn" | "straight" | "stop" | "end" | "warn" {
  if (!cue) return "straight";
  if (cue.kind === "end") return "end";
  if (cue.kind === "stop") return "stop";
  if (cue.movement) return cue.movement;
  if (cue.kind === "hazard" || cue.kind === "walk") return "warn";
  return "straight";
}

/** The card's shape for the cue: an arrow, a stop or a finish mark, a warning sign. A shape, never colour alone. */
function CueShape({ shape }: { shape: ReturnType<typeof arrowFor> }) {
  const paths: Record<typeof shape, string> = {
    left: "M30 52 V28 H14 M22 18 L12 28 L22 38",
    right: "M18 52 V28 H34 M26 18 L36 28 L26 38",
    bear_left: "M30 52 V30 L14 14 M14 26 V14 H26",
    bear_right: "M18 52 V30 L34 14 M22 14 H34 V26",
    uturn: "M32 52 V22 A10 10 0 0 0 12 22 V38 M4 30 L12 40 L20 30",
    straight: "M24 52 V10 M14 20 L24 10 L34 20",
    stop: "M14 10 V52 M14 12 H38 L32 20 L38 28 H14",
    end: "M14 10 V52 M14 12 H38 V28 H14 M26 12 V28 M14 20 H38",
    warn: "M24 8 L44 46 H4 Z M24 20 V32 M24 38 V40",
  };
  return (
    <svg className="cue-shape" viewBox="0 0 48 56" aria-hidden="true" focusable="false">
      <path d={paths[shape]} fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** A live region that says the same sentence twice when it is set twice (App's count trick). */
function LiveRegion({ said, urgent }: { said: { text: string; count: number }; urgent: boolean }) {
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
  /** Settings: two pickers, with what each level says behind an (i) (the first Start ride keeps the radios). */
  compact?: boolean;
}) {
  if (compact) {
    const levels = Object.keys(VERBOSITY_LABELS) as Verbosity[];
    return (
      <>
        <SettingRow infoId={`${idBase}-output-info`} about="say cues with">
          <SettingSelect
            label="Say cues with"
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
            label="How much to say"
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
        <legend>Say cues with</legend>
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
        <legend>How much to say</legend>
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

/** Big text (the cue card large, the map hidden): in Settings, not on the ride screen (the owner, 2026-10-17). */
export function BigTextField({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="toggle ride-toggle big-text-setting">
      <input type="checkbox" checked={on} onChange={(event) => onChange(event.target.checked)} />
      {BIG_TEXT_NAME}
    </label>
  );
}

/** How long the copy reply waits after clearing, so a second press is a change a screen reader says. */
const COPY_REPLY_DELAY_MS = 150;

/**
 * Report to DC 311 (lib/report311.ts; OWNER-DECISIONS 369, 370, 465): what it is, the message built from
 * the rider's place and its sending, then an optional note (v0.7.0 "Go riding fixes" item 3: the note comes
 * after, never before; the 311 button's one-tap pick is the usual way, and this fold is where "Add a note"
 * and a computer's copy land). The place is: the road ridden in the route's street names, a cross street within 500 ft, and the GPS position. On a phone a pothole or a
 * streetlight is a Text to 311 link the rider sends; anything else (a downed tree, a vehicle in a bike
 * lane, a blocked road or bikeway, which the words name first), and everything on a desktop, is the
 * same words to copy into DC 311 online, with a hint naming its request there where one is known. The place follows the rider; the message is shown as sent.
 */
function Report311({
  model,
  progressM,
  off,
  idBase,
  kind,
  onKind,
  open,
  onOpen,
  summaryRef,
  noteRef,
  serverOn = false,
  miles = null,
}: {
  model: RideModel;
  progressM: number | null;
  off: boolean;
  idBase: string;
  /** The problem chosen: here, or from the 311 button's menu (UI-CLEANUP), which opens this fold. */
  kind: ReportKind;
  onKind: (kind: ReportKind) => void;
  open: boolean;
  onOpen: (open: boolean) => void;
  summaryRef: RefObject<HTMLElement | null>;
  noteRef?: RefObject<HTMLInputElement | null>;
  /** The server sends reports to DC 311 itself (it has DC's key): the privacy line says so. */
  serverOn?: boolean;
  /** The trail mile markers (lib/trailMiles.ts): on a trail the place names its mile. */
  miles?: TrailMiles | null;
}) {
  const setKind = onKind;
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState("");
  const place = progressM === null ? null : reportPlace(model, progressM, miles);
  const outside = progressM !== null && !inDc(pointAt(model, progressM));
  // The words for DC 311 online (shown and copied), and the text message, which starts with DC's keyword.
  const text = outside ? null : reportText(kind, place, note);
  const sms = outside ? null : reportText(kind, place, note, true);
  const keyword = keywordOf(kind);
  const phone = typeof navigator !== "undefined" && canText(navigator.userAgent, navigator.maxTouchPoints ?? 0);
  const copy = async () => {
    if (!text) return;
    const done = await copyText(text, navigator.clipboard, selectionCopy);
    setCopied("");
    window.setTimeout(() => setCopied(done ? "Report copied." : "Could not copy; select the report's text instead."), COPY_REPLY_DELAY_MS);
  };
  return (
    <details className="fold ride-report" open={open} onToggle={(event) => onOpen(event.currentTarget.open)}>
      <summary ref={summaryRef}>{REPORT_SUMMARY}</summary>
      <div className="fold-body">
        <fieldset className="ride-choice">
          <legend>What is it?</legend>
          {REPORT_KINDS.map((k) => (
            <label key={k.kind} className="radio">
              <input type="radio" name={`${idBase}-report`} checked={kind === k.kind} onChange={() => setKind(k.kind)} />
              {k.label}
            </label>
          ))}
        </fieldset>
        {text === null || sms === null ? (
          <p className="hint">{outside ? REPORT_OUTSIDE_DC : off ? REPORT_OFF_ROUTE : REPORT_NO_PLACE}</p>
        ) : (
          <>
            <p className="ride-report-text">
              <span className="ride-report-label">The report: </span>
              {text}
            </p>
            {phone && keyword && <p className="hint">{`The text to 32311 starts with ${keyword}, DC's keyword for it.`}</p>}
            {/* On a phone the text first; DC 311 online always, since a tablet (or a phone) may not send texts. */}
            <div className="actions ride-report-actions">
              {phone && keyword && (
                <a
                  className="action-link"
                  href={smsHref(sms, navigator.userAgent, navigator.maxTouchPoints ?? 0)}
                  aria-label={`Text to DC 311 (${SHORT_CODE_SPOKEN})`}
                >
                  Text to DC 311 (32311)
                </a>
              )}
              <a className={`action-link${phone && keyword ? " secondary" : ""}`} href={DC_311_ONLINE} target="_blank" rel="noopener noreferrer">
                Open DC 311 online (new tab)
              </a>
              <button type="button" className="secondary" onClick={() => void copy()}>
                Copy the report
              </button>
            </div>
            <p className="hint" role="status">
              {copied}
            </p>
            {!keyword && <p className="hint">{onlineHint(kind)}</p>}
          </>
        )}
        {/* The note last: optional, and after the sending (the report above takes it in as it is typed). */}
        <label className="ride-report-note">
          Add a note (optional)
          <input ref={noteRef} type="text" value={note} maxLength={REPORT_NOTE_MAX} onChange={(event) => setNote(event.target.value)} />
        </label>
        <p className="hint">{serverOn ? REPORT_PRIVACY_SERVER : REPORT_PRIVACY}</p>
      </div>
    </details>
  );
}

/** The way back to the planned route, said: "The planned route is 300 feet to the left." */
/** Said off a fixed route, before the way back: it is not re-routed (the review of #191). */
export const FIXED_SAID = "This ride stays on its route, never re-routed.";

function wayBackSaid(back: { metres: number; direction: string }): string {
  return `The planned route is ${spokenDistance(back.metres)} to the ${back.direction}.`;
}

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
  big,
  onBig,
  onView,
  onEnd,
  water,
  trailMiles = null,
  geoEnv,
  keepLastRide = false,
  trip = null,
  onRideRest,
  fixed = false,
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
  big: boolean;
  onBig: (on: boolean) => void;
  /** The ride's route and the rider's position, for the map. */
  onView: (view: RideView) => void;
  /** End ride: with the plan the ride leaves (part way, from here; lib/navigate.ts planAfterEnd). */
  onEnd: (after: EndedPlan) => void;
  /** The water layer's points, loaded if they are not yet (App's ensureWater); for the detours. */
  water?: () => Promise<WaterPoint[] | null>;
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
}) {
  const [route, setRoute] = useState(plannedRoute);
  const routeRef = useRef(route);
  routeRef.current = route;
  // What a re-plan builds on: the plan's points at first, then the last re-plan's (never a loop: its end is sent).
  const plan = useRef({ points: plannedPoints, loop: plannedLoop });
  // The via points are not announced (v0.7.0): the model leaves them out of its cues.
  // A re-route that turns the rider round starts with "Make a U-turn." (lib/navigate.ts withUTurn).
  const uturnRoute = useRef<RouteResponse | null>(null);
  const modelOf = (r: RouteResponse, points: readonly LonLat[]) => {
    const built = rideModel(r, viaIndices(points, VIA_MARKS.isVia));
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
  const otherModel = useMemo(() => (other ? rideModel(other, viaIndices(plan.current.points, VIA_MARKS.isVia)) : null), [other]);
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
  // Each re-plan's ticket: "Keep the planned route" or a newer re-plan voids an older one's answer.
  const replanTicket = useRef(0);
  const settingsId = useId();
  // The ride's settings, opened from the top row's Settings (closed at Start).
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsPanel = useRef<HTMLDivElement>(null);
  // Opened, the panel is brought into view (the row above it is sticky; the card may be scrolled).
  useEffect(() => {
    if (settingsOpen) settingsPanel.current?.scrollIntoView?.({ block: "nearest" });
  }, [settingsOpen]);
  // The 311 button's menu (lib/ride311.ts; the owner's choice 9) and the report it continues into.
  const [reportKind, setReportKind] = useState<ReportKind>("pothole");
  const [reportOpen, setReportOpen] = useState(false);
  const [menu311, setMenu311] = useState(false);
  const menu311Id = useId();
  const menu311Heading = useRef<HTMLHeadingElement>(null);
  const button311 = useRef<HTMLButtonElement>(null);
  const reportSummary = useRef<HTMLElement>(null);
  const focusReport = useRef(false);
  useEffect(() => {
    if (menu311) menu311Heading.current?.focus();
  }, [menu311]);
  useEffect(() => {
    if (!reportOpen || !focusReport.current) return;
    focusReport.current = false;
    reportSummary.current?.focus();
    reportSummary.current?.scrollIntoView?.({ block: "start" });
  }, [reportOpen]);
  const close311 = () => {
    setMenu311(false);
    button311.current?.focus();
  };
  // The report fold opened and its summary focused (a computer's copy, a pick with no place yet).
  const openReport = () => {
    focusReport.current = true;
    if (reportOpen) {
      focusReport.current = false;
      reportSummary.current?.focus();
      reportSummary.current?.scrollIntoView?.({ block: "start" });
    } else setReportOpen(true);
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
  const noteInput = useRef<HTMLInputElement>(null);
  const focusNote = useRef(false);
  const tell311 = useCallback((text: string) => {
    setSaid311(text);
    announcer.current?.answer(text);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
  }, []);
  // One tap: the problem picked is the report (Go riding fixes item 3). Sent by the server where it can;
  // else, on a phone, the text app to 311 filled in; else the report below to copy. The focus goes back to
  // the 311 button as the menu closes, never into a form.
  const pick311 = (kind: ReportKind) => {
    setReportKind(kind);
    setMenu311(false);
    const progress = rideRef.current.off ? null : rideRef.current.progressM;
    const place = progress === null ? null : reportPlace(modelRef.current, progress, milesRef.current);
    if (!place || !inDc(place.point)) {
      openReport();
      return;
    }
    button311.current?.focus();
    const agent = typeof navigator !== "undefined" ? navigator.userAgent : "";
    const touch = typeof navigator !== "undefined" ? (navigator.maxTouchPoints ?? 0) : 0;
    const phone = canText(agent, touch);
    const toMessages = () => {
      const sms = reportText(kind, place, "", true);
      if (sms) window.location.assign(smsHref(sms, agent, touch));
    };
    const way = pickWay(serverOn311, phone);
    if (way === "server") {
      setSaid311("Sending to DC 311…");
      void sendReport311(window.location.origin, kind, place).then((sent) => {
        if (ended.current) return;
        if (sent) tell311(REPORT_SENT);
        else if (phone) {
          toMessages();
          tell311(REPORT_SEND_FAILED);
        } else {
          openReport();
          tell311(REPORT_FORM);
        }
      });
    } else if (way === "sms") {
      toMessages();
      tell311(REPORT_READY);
    } else {
      openReport();
      tell311(REPORT_FORM);
    }
  };
  // "Add a note" (after, never before): the report opens with the focus in its note field.
  const addNote = () => {
    focusNote.current = true;
    if (reportOpen) {
      focusNote.current = false;
      noteInput.current?.focus();
    } else setReportOpen(true);
  };
  useEffect(() => {
    if (!reportOpen || !focusNote.current) return;
    focusNote.current = false;
    noteInput.current?.focus();
  }, [reportOpen]);
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
  const openMenu = (which: "detour" | "dock" | "311" | null) => {
    setDetourOpen(which === "detour");
    setDockOpen(which === "dock");
    setMenu311(which === "311");
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
    if (toScreenReader(output)) (said.urgent ? setAssertive : setPolite)((s) => ({ text: said.text, count: s.count + 1 }));
    // The voice as chosen; in the phone app also "my screen reader" while the page is hidden (nativeShell.ts).
    if (speaksAloud(output, document.visibilityState === "hidden")) rideVoice.speak(said.text, said.urgent);
    // The phone app's cue notification on Android (nothing in a browser).
    showCue(said.text);
  }, []);
  const announcer = useRef<Announcer | null>(null);
  if (announcer.current === null) announcer.current = new Announcer(deliver);

  // After the page comes back from the background: say where the rider is once, on the next fix.
  const sayWhereNext = useRef(false);
  const say = useCallback((events: RideEvent[]) => {
    for (const event of events) announcer.current?.say(event.spoken, event.urgent);
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
      if (note && note !== wakeSaid.current) notify(note);
      wakeSaid.current = note;
      setWakeNote(note);
    },
    [notify, wake],
  );
  // The browser letting the lock go mid-ride (review RIDE-8): asked again, and said if it is not back.
  useEffect(() => {
    wake.whenLost(noteWake);
    return () => wake.whenLost(null);
  }, [wake, noteWake]);

  // The detour's own status (below): said like an answer, since the rider asked for it.
  const [detourStatus, setDetourStatus] = useState("");
  const [detourList, setDetourList] = useState<Found | null>(null);
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
    async (here: LonLat, via?: LonLat, asked = false, turnRound = false) => {
      if (ended.current) return;
      const current = rideRef.current;
      // The way the rider is going (the owner, 2026-10-18: "Penalize U turns", "For rerouting"): the new route sets
      // off ahead unless turning round saves half a mile. Not after Road closed, where turning round is the point.
      const heading = turnRound ? null : (current.goodFix?.headingDeg ?? null);
      const left = replanPoints(modelRef.current, current.progressM ?? 0, here, plan.current.points, plan.current.loop);
      const points = via ? detourPoints(left, via) : left;
      if (!points) {
        sayDetour(DETOUR_FULL);
        return;
      }
      if (!gate.begin(Date.now())) {
        // Only a detour is the rider's own ask; an automatic re-plan held back by the gate says nothing.
        if (via) sayDetour(DETOUR_BUSY);
        return;
      }
      const ticket = (replanTicket.current += 1);
      setReplanning(true);
      setReplanNote("");
      // The quiet level hears nothing unprompted but arrival, and the stoker only that a new route was
      // found (plan section 3, off route said once); the note stays on screen for all. A detour's outcome
      // answers the rider's ask, so it is said whatever the level (sayDetour); so is Re-plan from here's.
      const tell = (note: string) => {
        if (via) {
          sayDetour(note);
          return;
        }
        const told = replanTold(asked, prefsRef.current.verbosity, note);
        if (told === "say") announcer.current?.say(note, false);
        if (told === "answer") {
          announcer.current?.answer(note);
          if (prefsRef.current.output === "neither") setPolite((s) => ({ text: note, count: s.count + 1 }));
        }
      };
      // No answer in REPLAN_TIMEOUT_MS: the rider is told there is no signal, while the request goes on
      // (the gate stays busy until it settles, so no second one joins it at the server; a late new
      // route is still taken).
      const timer = window.setTimeout(() => {
        if (ended.current || ticket !== replanTicket.current) return;
        setReplanNote(REPLAN_NO_SIGNAL);
        tell(REPLAN_NO_SIGNAL);
      }, REPLAN_TIMEOUT_MS);
      // The rider is riding a plan already made: a long one is not asked to be confirmed again (a signed-out
      // rider's re-plan of a long ride was refused for want of it).
      const ask = (to: LonLat[]) =>
        requestRoute(to, preset, { dials: { ...dials, loop: false }, vias: viaIndices(to, VIA_MARKS.isVia), routeOnly: true, confirmLong: true, blocked: blockedRef.current, heading });
      const result = await ask(points);
      // No new route to the end: the way back to the planned route, which goes on from there (lib/rejoin.ts;
      // the owner, 2026-10-17). Not for a detour, whose place the planned route does not pass. The no-signal
      // timer runs on through it.
      let found = result.ok ? result.route : null;
      let failed = result.ok ? null : result.error.kind;
      let note = REPLAN_FOUND;
      const voided = () => ended.current || ticket !== replanTicket.current;
      if (!result.ok && !via && startsWayBack(result.error.kind) && !voided()) {
        const kept = replanKept(modelRef.current, current.progressM ?? 0, plan.current.points, plan.current.loop);
        // Never back onto a road the rider marked closed: the way back joins the route past it.
        const closed = blockedUntil.current?.model === modelRef.current ? blockedUntil.current.untilM : -Infinity;
        const back = await wayBackRoute(routeRef.current, modelRef.current, current.progressM ?? 0, here, kept, ask, voided, closed);
        if ("route" in back) found = back.route;
        else if (back.failed) failed = back.failed;
        note = REPLAN_REJOIN;
      }
      window.clearTimeout(timer);
      gate.finish(found !== null);
      // Road closed pressed while this one was under way: this answer did not leave that road out, so it is
      // dropped (the press voided it) and the ride is planned again from where the rider is now.
      if (closedPending.current && !ended.current) {
        closedPending.current = false;
        gate.online();
        void replanRef.current(rideRef.current.goodFix?.point ?? here, undefined, true, true);
        return;
      }
      if (voided()) return;
      setReplanning(false);
      if (!found) {
        const said = failed === "network" ? REPLAN_NO_SIGNAL : REPLAN_FAILED;
        setReplanNote(said);
        tell(said);
        return;
      }
      plan.current = { points, loop: false };
      // The first route, without the picker, during a ride (plan section 4).
      announcer.current?.drop();
      // Turned round (the API keeps a U-turn only where it saves half a mile): said plainly, and the first cue.
      const turned = heading !== null && setsOffBack(found.geometry.coordinates, heading);
      uturnRoute.current = turned ? found : null;
      if (turned && note === REPLAN_FOUND) note = REPLAN_UTURN;
      const model = modelOf(found, points);
      modelRef.current = model;
      setRoute(found);
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
    },
    [dials, preset, gate, sayDetour],
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
      const auto = !keepRef.current && !fixedRef.current;
      // Walking to the dock, nothing is placed on the line or taken as off route (lib/rideTrip.ts).
      const wasWalking = tripRef.current.walking;
      const stepped = tripStep(modelRef.current, trip, { ...tripRef.current, ride: rideRef.current }, fix, prefsRef.current.verbosity, auto);
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
      if (stepped.state.walking) return;
      // Off this line but on the other one (the standard way, or the detour): followed there, not re-planned.
      if (out.state.off && fix.accuracyM <= POOR_FIX_M) {
        const at = onOtherLine(otherModelRef.current, fix.point, fix.accuracyM, out.state.progressM ?? -Infinity);
        if (at !== null) {
          takeOther(at, fix);
          return;
        }
      }
      say(out.events);
      // A fixed route: leaving it says the way back, once, as Keep the planned route does.
      if (fixedRef.current && out.events.some((e) => e.kind === "off-route")) {
        const back = wayBack(modelRef.current, out.state);
        if (back) announcer.current?.answer(`${FIXED_SAID} ${wayBackSaid(back)}`);
      }
      // Back on the planned route: "Keep" has done its work; leaving it again re-plans as usual.
      if (out.events.some((e) => e.kind === "back-on-route") || (keepRef.current && !out.state.off)) setKeepPlanned(false);
      // Never from a poor fix: a re-plan from a Wi-Fi guess 300 m out would be wrong at once.
      if (out.state.off && auto && !gate.busy && fix.accuracyM <= POOR_FIX_M && out.state.goodFix) void replan(out.state.goodFix.point);
      if (sayWhereNext.current && out.state.progressM !== null) {
        sayWhereNext.current = false;
        announcer.current?.answer(whereAmI(modelRef.current, out.state, false, milesRef.current));
      }
    },
    [gate, replan, say, notify, checkCueSheet, approach, trip, takeOther],
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
      if (state.off && !keepRef.current && !fixedRef.current && state.goodFix) void replan(state.goodFix.point);
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [gate, replan]);

  // The map's view of the ride.
  const fix = ride.fix;
  // Where the next train or bus is, while the rider waits at the boarding (NextVehicleLine).
  const [vehicle, setVehicle] = useState<VehicleMark | null>(null);
  useEffect(() => {
    onView({
      route,
      other: other?.geometry.coordinates ?? null,
      rider: fix ? { point: fix.point, headingDeg: fix.headingDeg, accuracyM: fix.accuracyM } : null,
      vehicle,
    });
  }, [route, other, fix, onView, vehicle]);

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
    const spoken = walk ? walk.spoken : whereAmI(modelRef.current, rideRef.current, false, milesRef.current);
    showToast(walk ? walk.shown : whereAmI(modelRef.current, rideRef.current, true, milesRef.current));
    // On demand: through the chosen outputs; with neither chosen, through the polite region too, since
    // the rider asked (the answer is also on screen).
    announcer.current?.answer(spoken);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text: spoken, count: s.count + 1 }));
  }, [approach, showToast]);
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
    if (toVoice(prefsRef.current.output)) rideVoice.speak(RIDE_ENDED, true);
    // A Bikeshare or transit trip's riding leg is not the plan: the plan stays as it was.
    onEnd(trip && !trip.asPlanned ? null : planAfterEnd(modelRef.current, rideRef.current, plan.current.points, plan.current.loop, Date.now()));
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

  // Water or restroom on the way (the owner, 2026-10-10: "If navigating, water sources and restrooms can be
  // detours"): the three nearest by bike from the rider's position, on the ride's own settings; Detour here
  // re-plans through the chosen one. The position is the ride's own fix; nothing new is looked up.
  const detourBusy = useRef(false);
  const findDetour = async (kind: NearestKind) => {
    if (detourBusy.current) {
      sayDetour(STILL_SEARCHING);
      return;
    }
    if (!water) return;
    detourBusy.current = true;
    setDetourList(null);
    sayDetour(findingSaid(kind));
    try {
      const fix = rideRef.current.goodFix ?? rideRef.current.fix;
      if (!fix) {
        sayDetour(NO_FIX_YET);
        return;
      }
      const outcome = await searchNearest({
        kind,
        from: "location",
        locate: async () => rideLocate(fix),
        start: () => null,
        centre: () => null,
        inside: insideCoverage,
        water,
        stations: [],
        request: (from, places) => requestNearest(from, places, preset, { ...dials, loop: false }),
      });
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
    sayDetour(`Finding a way to ${item.place.title}.`);
    void replan(here, item.place.point);
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
          request: (from, places) => requestNearest(from, places, preset, { ...dials, loop: false }),
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

  // Keys while the focus is in Ride mode (outside a text field): W where am I, C re-centre. Only there
  // (WCAG 2.1.4), so speech input or a stray key elsewhere on the page fires neither.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (!target || !sectionRef.current?.contains(target)) return;
      if (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.key === "w" || event.key === "W") {
        event.preventDefault();
        askWhere();
      } else if ((event.key === "c" || event.key === "C") && !big) {
        event.preventDefault();
        onFollow(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [askWhere, onFollow, big]);

  const progress = ride.progressM;
  const cue = progress === null ? null : nextAction(model, progress);
  const togo = progress === null ? null : toGo(model, progress);
  const back = ride.off ? wayBack(model, ride) : null;
  const shape = arrowFor(cue);
  const show311 = ride311Shown({ off: ride.off, progressM: progress, insideDc: (m) => inDc(pointAt(model, m)) });
  const place311 = show311 && progress !== null ? reportPlace(model, progress, trailMiles) : null;
  // A re-plan's outcome back on the route ("New route found.") shows by the side buttons for a few seconds; off
  // the route it stays in the bottom panel with Re-plan from here. Said either way (replan's tell).
  const offNow = ride.off;
  useEffect(() => {
    if (!replanNote || offNow) return;
    showToast(replanNote);
    setReplanNote("");
  }, [replanNote, offNow, showToast]);
  const notesShown = !!((gps && ride.fix) || paused || wakeNote || (ride.off && replanNote) || corridorText);
  const sheetShown = notesShown || ride.off || restShown || reportOpen;
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
    <section ref={sectionRef} className={`ride ${big ? "ride-big" : ""}`} aria-labelledby="ride-heading">
      <LiveRegion said={polite} urgent={false} />
      <LiveRegion said={assertive} urgent />
      <div className="cue-card">
        {/* End ride (v0.7.0, "Go riding fixes" item 6): always in view, at the top of the card, which stays at
            every size and in Big text; one tap ends the ride, and the page offers Undo for a few seconds
            (RideEnded). Settings beside it opens the ride's settings just under the row (the owner, 2026-10-16). */}
        <div className="ride-top">
          <h2 id="ride-heading" ref={headingRef} tabIndex={-1} className="ride-heading">
            Ride mode
          </h2>
          <div className="ride-top-actions">
            <button
              type="button"
              className="secondary ride-settings-button"
              aria-expanded={settingsOpen}
              aria-controls={`${settingsId}-settings`}
              onClick={() => setSettingsOpen(!settingsOpen)}
            >
              <Icon name="gear" size={18} />
              {/* Shown where there is room; on the narrowest phones the gear alone, its name still "Settings". */}
              <span className="ride-settings-label">{RIDE_SETTINGS_TEXT}</span>
            </button>
            <button type="button" className="danger ride-end" onClick={end}>
              <Icon name="stop" size={18} />
              {END_RIDE_NAME}
            </button>
          </div>
        </div>
        <div ref={settingsPanel} id={`${settingsId}-settings`} className="ride-mode-settings" role="group" aria-label={RIDE_SETTINGS_TITLE} hidden={!settingsOpen}>
          <RideSettingsFields prefs={prefs} onChange={onPrefs} idBase={settingsId} />
          <p className="hint">{RIDE_SAFETY}</p>
          <label className="toggle ride-toggle">
            <input type="checkbox" checked={headingUp} onChange={(event) => onHeadingUp(event.target.checked)} />
            Turn the map to my heading
          </label>
          <BigTextField on={big} onChange={onBig} />
        </div>
        {ride.arrived ? (
          <>
            <p className="cue-text">{trip?.finish?.shown ?? cueSpoken(model.cues[model.cues.length - 1], "arrive", 0)}</p>
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
              <p className="cue-text">Off the planned route.</p>
              {replanning && <p className="cue-then">Finding a new way from here…</p>}
              {(keepPlanned || fixedRef.current) && back && (
                <p className="cue-then">
                  The planned route is {formatDistance(back.metres)} to the {back.direction}.
                </p>
              )}
            </div>
          </div>
        ) : cueSheetOn ? (
          // GPS weak for long (cueSheetShown): the turns ahead from the last good place, in order, the
          // next first; a list a screen reader reads as one, with no control of its own.
          <div className="cue-sheet">
            <p id={cueSheetId} className="cue-then">
              Turns ahead, in order:
            </p>
            <ol className="cue-sheet-list" aria-labelledby={cueSheetId}>
              {cueSheet(model, progress ?? 0).map((row, i) => (
                <li key={row.index} className={i === 0 ? "cue-sheet-next" : undefined} aria-current={i === 0 ? "step" : undefined}>
                  <span className="cue-sheet-distance">{row.distance}:</span> {row.text}
                </li>
              ))}
            </ol>
          </div>
        ) : cue && progress !== null ? (
          <div className="cue-next">
            <CueShape shape={shape} />
            <div>
              {/* Greyed while GPS is weak or lost (any GPS note): the distance is from an old fix, not where the rider is. */}
              <p className={gps ? "cue-distance cue-distance-weak" : "cue-distance"}>In {formatDistance(cue.atM - progress)}</p>
              <p className="cue-text">{cue.rideText ?? cue.text}</p>
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
                <dt>To stop {togo.stop.number}</dt>
                <dd>
                  {formatDistance(togo.stop.metres)}
                  {togo.stop.seconds !== null && `, about ${formatDuration(togo.stop.seconds)}`}
                </dd>
              </div>
            )}
            <div>
              <dt>To the end</dt>
              <dd>
                {formatDistance(togo.end.metres)}
                {togo.end.seconds !== null && `, about ${formatDuration(togo.end.seconds)}`}
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
        {!big && (
          <button type="button" className="ride-compass" aria-pressed={!headingUp} aria-label="North up" title="North up" onClick={() => onHeadingUp(!headingUp)}>
            <svg viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
              <path d="M20 5 L25 20 L20 17 L15 20 Z" className="ride-compass-north" />
              <path d="M20 35 L15 20 L20 23 L25 20 Z" className="ride-compass-south" />
            </svg>
          </button>
        )}
        {toast.text && !detourOpen && !dockOpen && !menu311 && (
          <div className="ride-toast" {...toastTimer.hold}>
            {/* Shown, not a live region: it is said through the rider's own outputs. */}
            <p key={toast.n}>{toast.text}</p>
          </div>
        )}
        <div className="ride-rail" role="group" aria-label="Ride buttons">
          <button type="button" ref={whereRef} className="ride-round" onClick={askWhere} aria-keyshortcuts="W" aria-label="Where am I?" title="Where am I?">
            <Icon name="pin" size={24} />
          </button>
          <button
            type="button"
            className={`ride-round${follow ? "" : " ride-round-alert"}`}
            onClick={() => onFollow(true)}
            aria-keyshortcuts="C"
            aria-label={follow ? "Re-centre" : "Re-centre: the map stopped following you"}
            title="Re-centre"
            hidden={big}
          >
            <Icon name="locate" size={24} />
          </button>
          {/* Road closed (v0.8.2, the owner's ask by name): one press while riding, no menu. */}
          {!walking && !ride.arrived && (
            <button type="button" className="ride-round ride-road-closed" onClick={roadClosed} aria-label={ROAD_CLOSED_NAME} title={ROAD_CLOSED_NAME}>
              <Icon name="barrier" size={24} />
            </button>
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
                aria-label={`Detour: ${DETOUR_SUMMARY.toLowerCase()}`}
                title="Detour"
                aria-expanded={detourOpen}
                aria-controls={detourId}
                onClick={() => openMenu(detourOpen ? null : "detour")}
              >
                <Icon name="detour" size={24} />
              </button>
              <div id={detourId} className="ride-menu" role="group" aria-labelledby={`${detourId}-heading`} hidden={!detourOpen}>
                <div className="ride-menu-head">
                  <h3 id={`${detourId}-heading`} ref={detourHeading} tabIndex={-1}>
                    Detour
                  </h3>
                  <button
                    type="button"
                    className="secondary ride-menu-close"
                    onClick={() => {
                      setDetourOpen(false);
                      detourButton.current?.focus();
                    }}
                  >
                    Close
                  </button>
                </div>
                <div className="actions nearest-kinds">
                  {NEAREST_KINDS.filter((k) => DETOUR_KINDS.includes(k.kind)).map(({ kind, label }) => (
                    <button key={kind} type="button" className="secondary" onClick={() => void findDetour(kind)}>
                      <Icon name={kind === "water" ? "water" : "wc"} size={20} />
                      {label}
                    </button>
                  ))}
                </div>
                {/* Shown, not a live region: what it says is said through the ride's own outputs (sayDetour). */}
                <p className="hint nearest-status">{detourStatus}</p>
                {detourList && detourList.items.length > 0 && (
                  <div className="nearest-list">
                    <h4 id={`${settingsId}-detour`}>{`Nearest ${nounOf(detourList.kind)}`}</h4>
                    <ol role="list" aria-labelledby={`${settingsId}-detour`}>
                      {detourList.items.map((item) => (
                        <li key={item.place.id}>
                          <span>{nearbyText(item)}</span>
                          <span className="actions">
                            <button
                              type="button"
                              className="secondary"
                              aria-label={`Detour here: ${item.place.title}`}
                              onClick={() => detour(item)}
                            >
                              Detour here
                            </button>
                          </span>
                        </li>
                      ))}
                    </ol>
                    <p className="hint">{WATER_CAUTION}</p>
                  </div>
                )}
                <p className="hint">{DETOUR_HELP}</p>
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
                onClick={() => openMenu(dockOpen ? null : "dock")}
              >
                <Icon name="bikeshare" size={20} />
                {undockAt !== null && <span aria-hidden="true">{docked ? DOCKED_SHOWN : undockedShown(undockedMinutes(undockAt, now))}</span>}
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
                    Close
                  </button>
                </div>
                {undockAt !== null && (
                  <p className="hint">{docked ? `Docked at ${docked}.` : `Undocked about ${undockedShown(undockedMinutes(undockAt, now))}.`}</p>
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
          {/* The 311 button (lib/ride311.ts): inside DC only; its menu beside the buttons. */}
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
                onMore={() => {
                  setMenu311(false);
                  openReport();
                }}
              />
              {said311Shown && (
                <div className="ride-311-said" {...said311Timer.hold}>
                  {/* Shown, not a live region: it is said through the rider's own outputs (tell311). */}
                  <p>{said311}</p>
                  {/* Sent by the server already: a note would be a second report of the same problem (v0.7.0 end review). */}
                  {said311 !== REPORT_SENT && (
                    <button type="button" className="secondary" onClick={addNote}>
                      Add a note
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
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
              {wakeNote && <p className="hint">{wakeNote}</p>}
              {ride.off && replanNote && <p className="hint">{replanNote}</p>}
              {paused && (
                <p className="notice">
                  {PAUSED_SAID}{" "}
                  <button type="button" onClick={resume}>
                    Resume
                  </button>
                </p>
              )}
            </div>
          )}
          {ride.off && (
            <div className="actions ride-off-actions" ref={blockOff}>
              <button type="button" onClick={replanNow} aria-disabled={replanning}>
                Re-plan from here
              </button>
              {/* A fixed route is always kept: no Keep to press. */}
              {!fixedRef.current && (
                <button type="button" className="secondary" onClick={keep} aria-pressed={keepPlanned}>
                  Keep the planned route
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
          {reportOpen && (
            <Report311
              model={model}
              progressM={ride.off ? null : progress}
              off={ride.off}
              idBase={settingsId}
              kind={reportKind}
              onKind={setReportKind}
              open={reportOpen}
              onOpen={(open) => {
                setReportOpen(open);
                // Closed, the report goes from the page: the focus goes to Where am I?, not to the page's top.
                if (!open) whereRef.current?.focus({ preventScroll: true });
              }}
              summaryRef={reportSummary}
              noteRef={noteInput}
              serverOn={serverOn311}
              miles={trailMiles}
            />
          )}
        </div>
      )}
    </section>
  );
}

/**
 * After End (v0.7.0, "Go riding fixes" item 6): "Ride ended." and Undo for UNDO_END_MS. It is said by the page's
 * polite region, which is always mounted (App says RIDE_ENDED_SAID: a region mounted with its text in it is often
 * not read; review F6), and the focus goes to Undo, as End (the button pressed) has gone. The time is held while the
 * focus or a mouse is inside it (WCAG 2.2.1), so a keyboard or screen-reader rider on Undo is not timed out of it.
 * Undo starts the same ride again.
 */
export function RideEnded({ onUndo, onGone }: { onUndo: () => void; onGone: () => void }) {
  const undo = useRef<HTMLButtonElement>(null);
  const { timer, hold } = useHoldTimer(UNDO_END_MS, onGone);
  useEffect(() => {
    // Focus is put on Undo, not taken there by the rider, so it does not hold the bar (re-check of
    // F6: a touch rider's bar would otherwise never go). Moving focus away and back does hold it.
    undo.current?.focus();
    timer.focus(false);
    timer.start();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, as it shows
  }, []);
  return (
    <div className="ride-ended" role="group" aria-label={RIDE_ENDED} {...hold}>
      <span aria-hidden="true">{RIDE_ENDED}</span>
      <button ref={undo} type="button" className="secondary" onClick={onUndo}>
        Undo
      </button>
    </div>
  );
}
