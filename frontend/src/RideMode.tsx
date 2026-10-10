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
 *   shows the way back. A re-plan never touches the plan in the address bar (plan Q2): it is the ride's
 *   own route, held here and in App's ride state only.
 * - Big text (map hidden), Re-centre (and the C key), heading-up, the ride's settings, End ride.
 *
 * Privacy (plan section 7): positions stay in memory for the ride; nothing is stored or logged; the only
 * one sent is a re-plan's start point, in a POST body, as planning with "Use my location" sends it.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { requestRoute, type RouteResponse } from "./lib/api.ts";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import type { PresetId } from "./lib/presets.ts";
import { formatDistance, formatDuration, spokenDistance } from "./lib/format.ts";
import { LOCATE_MESSAGES } from "./lib/geolocation.ts";
import {
  POOR_FIX_M,
  REPLAN_FAILED,
  REPLAN_FOUND,
  REPLAN_NO_SIGNAL,
  ReplanGate,
  VERBOSITY_LABELS,
  nextAction,
  replanPoints,
  rideModel,
  startState,
  step,
  toGo,
  wayBack,
  whereAmI,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideState,
  type Verbosity,
} from "./lib/navigate.ts";
import {
  Announcer,
  OUTPUT_LABELS,
  ScreenWake,
  Voice,
  WAKE_UNAVAILABLE,
  browserSpeech,
  browserWake,
  toScreenReader,
  toVoice,
  type CueOutput,
  type RidePrefs,
  type Said,
} from "./lib/rideOutput.ts";
import { WAITING_FOR_GPS, browserRideEnv, watchRide, type RideGeoEnv } from "./lib/rideWatch.ts";

/** One voice for the page: the Start ride press unlocks it (iOS speaks only after a gesture has). */
export const rideVoice = new Voice(browserSpeech());

/** Said as the ride starts, inside the Start press, so the voice is unlocked by it. */
export const RIDE_STARTED = "Ride started.";
export const RIDE_ENDED = "Ride ended.";
/** Hidden this long, the watch stops (privacy and battery) and the ride offers Resume (plan section 5). */
export const HIDDEN_STOP_MS = 10 * 60_000;
export const PAUSED_SAID = "Ride paused while the page was in the background. Press Resume to carry on.";
/** A re-plan that has not answered in this long is said as no signal (a hung connection); its answer still counts. */
export const REPLAN_TIMEOUT_MS = 25_000;
/** No fix for this long and a failure from the watch: the rider is told (once) that GPS is lost. */
export const GPS_LOST_MS = 30_000;
export const GPS_LOST_SAID = "No GPS signal: the cues are paused until it comes back.";

/** The rider's responsibility and the battery, said before the first ride (plan sections 5 and 10). */
export const RIDE_SAFETY =
  "Ride mode guides you along the planned route; you stay responsible for riding safely and obeying the rules of the road, and the route can be wrong. It needs the screen on and this page in front, and GPS with a lit screen drains the battery quickly.";

/** Called inside the Start ride press: unlock the voice with the first sentence, where the rider chose it. */
export function startRideGesture(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(RIDE_STARTED);
}

/** What App shows on the map for the ride. */
export interface RideView {
  route: RouteResponse;
  rider: { point: LonLat; headingDeg: number | null; accuracyM: number } | null;
}

function arrowFor(cue: Cue | null): "left" | "right" | "straight" | "stop" | "end" | "warn" {
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
}: {
  prefs: RidePrefs;
  onChange: (prefs: RidePrefs) => void;
  idBase: string;
}) {
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
  geoEnv,
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
  onEnd: () => void;
  geoEnv?: RideGeoEnv;
}) {
  const [route, setRoute] = useState(plannedRoute);
  const model = useMemo(() => rideModel(route), [route]);
  const modelRef = useRef(model);
  modelRef.current = model;
  // What a re-plan builds on: the plan's points at first, then the last re-plan's (never a loop: its end is sent).
  const plan = useRef({ points: plannedPoints, loop: plannedLoop });
  const [ride, setRide] = useState<RideState>(startState);
  const rideRef = useRef(ride);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const [polite, setPolite] = useState({ text: "", count: 0 });
  const [assertive, setAssertive] = useState({ text: "", count: 0 });
  const [where, setWhere] = useState("");
  const [gps, setGps] = useState<string>(WAITING_FOR_GPS);
  const [wakeNote, setWakeNote] = useState("");
  const [replanning, setReplanning] = useState(false);
  const [replanNote, setReplanNote] = useState("");
  // "Keep the planned route": no automatic re-plan until the rider is back on it (or presses it again).
  const [keepPlanned, setKeepPlanned] = useState(false);
  const keepRef = useRef(keepPlanned);
  keepRef.current = keepPlanned;
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const pausedSaid = useRef(false);
  // The last GPS failure and wake note said, so each is said once, not on every repeat.
  const gpsSaid = useRef<string | null>(null);
  const wakeSaid = useRef("");
  const lastFixAt = useRef(Date.now());
  const headingRef = useRef<HTMLHeadingElement>(null);
  const whereRef = useRef<HTMLButtonElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  // Ended (End ride, or unmounted): a re-plan answering late says nothing and changes nothing.
  const ended = useRef(false);
  // Each re-plan's ticket: "Keep the planned route" or a newer re-plan voids an older one's answer.
  const replanTicket = useRef(0);
  const settingsId = useId();
  const gate = useRef(new ReplanGate()).current;
  const wake = useRef(new ScreenWake(browserWake())).current;
  const env = useRef(geoEnv ?? browserRideEnv()).current;

  // The outputs: the screen reader's regions and the voice, as the rider chose; through the throttle.
  const deliver = useCallback((said: Said) => {
    const output = prefsRef.current.output;
    if (toScreenReader(output)) (said.urgent ? setAssertive : setPolite)((s) => ({ text: said.text, count: s.count + 1 }));
    if (toVoice(output)) rideVoice.speak(said.text, said.urgent);
  }, []);
  const announcer = useRef<Announcer | null>(null);
  if (announcer.current === null) announcer.current = new Announcer(deliver);

  // After the page comes back from the background: say where the rider is once, on the next fix.
  const sayWhereNext = useRef(false);
  const say = useCallback((events: RideEvent[]) => {
    for (const event of events) announcer.current?.say(event.spoken, event.urgent);
  }, []);
  // A note about the ride itself (no GPS, the screen may sleep, paused): said once, politely, and through
  // the polite region even with "neither" chosen, since it changes what the rider must do.
  const notify = useCallback((text: string) => {
    if (!text) return;
    announcer.current?.note(text);
    if (!toScreenReader(prefsRef.current.output)) setPolite((s) => ({ text, count: s.count + 1 }));
  }, []);
  const noteWake = useCallback(
    (held: boolean) => {
      const note = held ? "" : WAKE_UNAVAILABLE;
      if (note && note !== wakeSaid.current) notify(note);
      wakeSaid.current = note;
      setWakeNote(note);
    },
    [notify],
  );

  // The re-plan (plan section 4): one POST /api/route from here through the stops not yet passed to the end.
  const replan = useCallback(
    async (here: LonLat) => {
      if (ended.current || !gate.begin(Date.now())) return;
      const ticket = (replanTicket.current += 1);
      setReplanning(true);
      setReplanNote("");
      const current = rideRef.current;
      const points = replanPoints(modelRef.current, current.progressM ?? 0, here, plan.current.points, plan.current.loop);
      // The quiet level hears nothing unprompted but arrival, and the stoker only that a new route was
      // found (plan section 3, off route said once); the note stays on screen for all.
      const tell = (note: string) => {
        const level = prefsRef.current.verbosity;
        if (level === "full" || (level === "stoker" && note === REPLAN_FOUND)) announcer.current?.say(note, false);
      };
      // No answer in REPLAN_TIMEOUT_MS: the rider is told there is no signal, while the request goes on
      // (the gate stays busy until it settles, so no second one joins it at the server; a late new
      // route is still taken).
      const timer = window.setTimeout(() => {
        if (ended.current || ticket !== replanTicket.current) return;
        setReplanNote(REPLAN_NO_SIGNAL);
        tell(REPLAN_NO_SIGNAL);
      }, REPLAN_TIMEOUT_MS);
      const result = await requestRoute(points, preset, { dials: { ...dials, loop: false } });
      window.clearTimeout(timer);
      gate.finish(result.ok);
      if (ended.current || ticket !== replanTicket.current) return;
      setReplanning(false);
      if (!result.ok) {
        const note = result.error.kind === "network" ? REPLAN_NO_SIGNAL : REPLAN_FAILED;
        setReplanNote(note);
        tell(note);
        return;
      }
      plan.current = { points, loop: false };
      // The first route, without the picker, during a ride (plan section 4).
      announcer.current?.drop();
      const model = rideModel(result.route);
      modelRef.current = model;
      setRoute(result.route);
      // The rider stays where they are on the map until the next fix places them on the new route.
      const fresh = { ...startState(), fix: rideRef.current.fix, goodFix: rideRef.current.goodFix };
      rideRef.current = fresh;
      setRide(fresh);
      setKeepPlanned(false);
      setReplanNote(REPLAN_FOUND);
      tell(REPLAN_FOUND);
    },
    [dials, preset, gate],
  );

  const onFix = useCallback(
    (fix: RideFix) => {
      if (ended.current) return;
      gpsSaid.current = null;
      lastFixAt.current = Date.now();
      setGps("");
      const auto = !keepRef.current;
      const out = step(modelRef.current, rideRef.current, fix, prefsRef.current.verbosity, auto);
      rideRef.current = out.state;
      setRide(out.state);
      say(out.events);
      // Back on the planned route: "Keep" has done its work; leaving it again re-plans as usual.
      if (out.events.some((e) => e.kind === "back-on-route") || (keepRef.current && !out.state.off)) setKeepPlanned(false);
      // Never from a poor fix: a re-plan from a Wi-Fi guess 300 m out would be wrong at once.
      if (out.state.off && auto && !gate.busy && fix.accuracyM <= POOR_FIX_M && out.state.goodFix) void replan(out.state.goodFix.point);
      if (sayWhereNext.current && out.state.progressM !== null) {
        sayWhereNext.current = false;
        announcer.current?.answer(whereAmI(modelRef.current, out.state));
      }
    },
    [gate, replan, say],
  );
  const onFixRef = useRef(onFix);
  onFixRef.current = onFix;

  // The watch: started with the ride (the Start press), stopped at End ride, after a long hide, on unmount.
  const stopWatch = useRef<(() => void) | null>(null);
  const startWatch = useCallback(() => {
    stopWatch.current?.();
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
      if (state.off && !keepRef.current && state.goodFix) void replan(state.goodFix.point);
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [gate, replan]);

  // The map's view of the ride.
  const fix = ride.fix;
  useEffect(() => {
    onView({ route, rider: fix ? { point: fix.point, headingDeg: fix.headingDeg, accuracyM: fix.accuracyM } : null });
  }, [route, fix, onView]);

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
    const spoken = whereAmI(modelRef.current, rideRef.current);
    setWhere(whereAmI(modelRef.current, rideRef.current, true));
    // On demand: through the chosen outputs; with neither chosen, through the polite region too, since
    // the rider asked (the answer is also on screen).
    announcer.current?.answer(spoken);
    if (prefsRef.current.output === "neither") setPolite((s) => ({ text: spoken, count: s.count + 1 }));
  }, []);
  const end = () => {
    ended.current = true;
    stopWatch.current?.();
    stopWatch.current = null;
    announcer.current?.drop();
    rideVoice.stop();
    if (toVoice(prefsRef.current.output)) rideVoice.speak(RIDE_ENDED, true);
    onEnd();
  };
  // A toggle: pressed, no automatic re-plan (one in flight is voided) and the way back is said once;
  // pressed again, re-planning is back on.
  const keep = () => {
    if (keepPlanned) {
      setKeepPlanned(false);
      return;
    }
    replanTicket.current += 1;
    setReplanning(false);
    setKeepPlanned(true);
    setReplanNote("");
    const back = wayBack(modelRef.current, rideRef.current);
    if (back) announcer.current?.answer(`The planned route is ${spokenDistance(back.metres)} to the ${back.direction}.`);
  };
  const replanNow = () => {
    if (replanning) return;
    setKeepPlanned(false);
    gate.online();
    const here = rideRef.current.goodFix?.point ?? rideRef.current.fix?.point;
    if (here) void replan(here);
  };

  // Off route over (back on, or a new route): its buttons go; a focus inside them goes to Where am I?.
  const wasOff = useRef(false);
  useEffect(() => {
    if (wasOff.current && !ride.off) {
      const active = document.activeElement;
      if (!active || active === document.body || !active.isConnected) whereRef.current?.focus();
    }
    wasOff.current = ride.off;
  }, [ride.off]);

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

  return (
    <section ref={sectionRef} className={`ride ${big ? "ride-big" : ""}`} aria-labelledby="ride-heading">
      <LiveRegion said={polite} urgent={false} />
      <LiveRegion said={assertive} urgent />
      <div className="cue-card">
        <h2 id="ride-heading" ref={headingRef} tabIndex={-1} className="ride-heading">
          Ride mode
        </h2>
        {ride.arrived ? (
          <p className="cue-text">You have arrived at the end of the route.</p>
        ) : ride.off ? (
          <div className="cue-off">
            <CueShape shape="warn" />
            <div>
              <p className="cue-text">Off the planned route.</p>
              {replanning && <p className="cue-then">Finding a new way from here…</p>}
              {keepPlanned && back && (
                <p className="cue-then">
                  The planned route is {formatDistance(back.metres)} to the {back.direction}.
                </p>
              )}
            </div>
          </div>
        ) : cue && progress !== null ? (
          <div className="cue-next">
            <CueShape shape={shape} />
            <div>
              <p className="cue-distance">In {formatDistance(cue.atM - progress)}</p>
              <p className="cue-text">{cue.kind === "end" ? "The end of the route." : cue.text}</p>
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

      <div className="ride-controls">
        {(gps && ride.fix) || paused || wakeNote || replanNote ? (
          <div className="ride-notes">
            {gps && ride.fix && <p className="hint">{gps}</p>}
            {wakeNote && <p className="hint">{wakeNote}</p>}
            {replanNote && <p className="hint">{replanNote}</p>}
            {paused && (
              <p className="notice">
                {PAUSED_SAID}{" "}
                <button type="button" onClick={resume}>
                  Resume
                </button>
              </p>
            )}
          </div>
        ) : null}
        {ride.off && (
          <div className="actions ride-off-actions">
            <button type="button" onClick={replanNow} aria-disabled={replanning}>
              Re-plan from here
            </button>
            <button type="button" className="secondary" onClick={keep} aria-pressed={keepPlanned}>
              Keep the planned route
            </button>
          </div>
        )}
        {!follow && !big && <p className="hint">The map stopped following you. Re-centre follows again.</p>}
        {where && (
          <p className="ride-where">{where}</p>
        )}
        <div className="actions ride-actions">
          <button type="button" ref={whereRef} onClick={askWhere} aria-keyshortcuts="W">
            Where am I?
          </button>
          <button type="button" className="secondary" onClick={() => onFollow(true)} aria-keyshortcuts="C" hidden={big}>
            Re-centre
          </button>
          <button type="button" className="secondary" onClick={() => onBig(!big)} aria-pressed={big}>
            Big text
          </button>
          <button type="button" className="danger" onClick={end}>
            End ride
          </button>
        </div>
        <details className="fold ride-mode-settings">
          <summary>Ride settings</summary>
          <div className="fold-body">
            <RideSettingsFields prefs={prefs} onChange={onPrefs} idBase={settingsId} />
            <p className="hint">{RIDE_SAFETY}</p>
            <label className="toggle ride-toggle">
              <input type="checkbox" checked={headingUp} onChange={(event) => onHeadingUp(event.target.checked)} />
              Turn the map to my heading
            </label>
          </div>
        </details>
      </div>
    </section>
  );
}
