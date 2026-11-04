/**
 * Stop by stop on transit (Stephen, 2026-11-02: "stop by stop directions for transit"). Once the ride to a boarding
 * ends, the ride screen follows the train or bus: the stops left, the next one, and "Next stop: Union Station. Get off
 * there." one stop before the rider's, then "Get off here". A bus says to press the stop button.
 *
 * Where the rider is comes from the phone's location, rough fixes too: underground the phone often finds itself by
 * Wi-Fi (Stephen, 2026-11-02: "I often see the location, I believe through wifi"), a few hundred feet out, and Metro
 * stations are half a mile and more apart, so a fix up to ROUGH_FIX_M counts here (turn-by-turn wants POOR_FIX_M).
 * With no fix for STALE_MS, the timetable says where the train should be: the step's scheduled seconds between stops,
 * from when the rider boarded (or, never seen boarding, from the planned wait after reaching the stop). The stops
 * only ever move on, never back.
 */
import type { TransitStep, TransitStop } from "./api.ts";
import { formatDuration } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import { METRO_LINES, PENN_COLOUR } from "./railStations.ts";
import { TRANSIT_COLOUR } from "./transit.ts";
import { lineAlong, snap, type RideFix } from "./navigate.ts";

/** The roughest fix that places the rider among the stops: a Wi-Fi fix underground. */
export const ROUGH_FIX_M = 500;
/** No usable fix for this long: the timetable places the train. */
export const STALE_MS = 90_000;
/** Farther than this (or the fix's own accuracy) from the boarding stop and on the line: on board. */
export const BOARDED_M = 400;
/** A stop is reached within this of it along the line (or half the fix's accuracy, if more). */
export const AT_STOP_M = 150;
/** Farther than this (or twice the fix's accuracy) from the line: the fix is not on this ride. */
export const OFF_LINE_M = 600;

/** A transit step to follow: its stops (boarding first, the stop to get off last), its line and way. */
export interface OnBoardLeg {
  stops: TransitStop[];
  /** "Red Line", "bus B10": as the card's badge. */
  line: string;
  /** The trains that make the ride, any of them: each line and where it is signed to (one, the planned way, from an older API). */
  trains?: { line: string; toward: string | null }[];
  /** The step's own departure ("7:42 am"), where the plan names one: shown when the plan's countdown is another step's. */
  departs?: string | null;
  /** A bus taking the bike: it goes on the front rack. */
  rack?: boolean;
  toward: string | null;
  bus: boolean;
  /** The planned wait at the boarding stop (seconds), for the timetable's guess at when the rider boarded. */
  waitS: number;
  /** A frequent service's minutes between departures; null for a timed one (its departure says when). */
  everyMin?: number | null;
  /** The plan's seconds from the stop to get off to the trip's end (the walks, waits and rides after it); null: not known. */
  afterS?: number | null;
}

export interface OnBoardState {
  /** When following began (the rider reached the boarding stop, or the walk to it ended). */
  since: number;
  /** When the rider was seen on board, or the timetable's guess; null while waiting. */
  boardedAt: number | null;
  /** The last stop reached, by its place in `stops` (0: the boarding stop). */
  at: number;
  /** The last usable fix's time. */
  fixAt: number | null;
  saidNext: boolean;
  saidOff: boolean;
  /** The stop to get off at is reached: the leg is done. */
  done: boolean;
  /** The last rough fix's place, which the next must agree with (byFix's `sure`). */
  pending?: { at: number; boarded: boolean } | null;
}

/** A transit step as one to follow; null without at least two stops (an older API). `afterS`: the plan's seconds after it to the trip's end. */
export function onBoardLeg(step: TransitStep, afterS: number | null = null): OnBoardLeg | null {
  const stops = step.stops ?? [];
  if (stops.length < 2) return null;
  const line = step.lines.length > 0 ? step.lines.join(" / ") : (step.system ?? "");
  const trains = step.towards?.length
    ? step.towards.map((w) => ({ line: w.line, toward: w.toward }))
    : [{ line, toward: step.toward ?? null }];
  return { stops, line, trains, departs: step.departs ?? null, rack: step.mode === "bus" && step.with_bike, toward: step.toward ?? null, bus: step.mode === "bus", waitS: step.wait_s, everyMin: step.every_min ?? null, afterS };
}

export function onBoardStart(now: number): OnBoardState {
  return { since: now, boardedAt: null, at: 0, fixAt: null, saidNext: false, saidOff: false, done: false };
}

function along(leg: OnBoardLeg): { coordinates: LonLat[]; along: Float64Array } {
  const coordinates = leg.stops.map((s) => s.point);
  return { coordinates, along: lineAlong(coordinates) };
}

/** The fastest a train is taken to go between fixes, for the window a fix is looked for in (metres a second). */
export const TRAIN_MS = 30;
/** The window reaches this far ahead of the last stop reached, plus TRAIN_MS for every second since the last fix. */
const AHEAD_M = 1000;
/** And this far behind it. */
const BEHIND_M = 300;

interface Placed {
  at: number;
  boarded: boolean;
  /** A fix good enough to act on alone; a rougher one moves the stops on only where the one before agrees. */
  sure: boolean;
}

/**
 * Where a fix puts the rider: the last stop reached and whether on board; null for a fix that says nothing here. It is
 * looked for near where the rider was (a window from the last stop reached, growing with the time since the last fix),
 * so a stray Wi-Fi fix far down the line, or on a bus's way back along the same street, is not taken.
 */
function byFix(leg: OnBoardLeg, state: OnBoardState, fix: RideFix, now: number): Placed | null {
  const accuracy = fix.accuracyM > 0 ? fix.accuracyM : 0;
  if (accuracy > ROUGH_FIX_M) return null;
  const line = along(leg);
  const from = line.along[state.at];
  const gapS = Math.max(0, (now - (state.fixAt ?? state.since)) / 1000);
  const found = snap(line, fix.point, from - BEHIND_M, from + AHEAD_M + TRAIN_MS * gapS, 15, from);
  if (!found || found.offM > Math.max(OFF_LINE_M, 2 * accuracy)) return null;
  let at = 0;
  line.along.forEach((m, i) => {
    // A stop is reached within AT_STOP_M of it (half a rough fix's accuracy), never more than 40% of the way from the
    // stop before: stops a block apart are not all reached at once.
    const gap = i > 0 ? m - line.along[i - 1] : Infinity;
    if (m <= found.alongM + Math.min(Math.max(AT_STOP_M, accuracy / 2), 0.4 * gap)) at = i;
  });
  const boarded = at >= 1 || (haversineM(fix.point, leg.stops[0].point) > Math.max(BOARDED_M, accuracy) && found.alongM > 0);
  return { at, boarded, sure: accuracy <= AT_STOP_M };
}

/** Where the timetable puts the train `now`: the last stop it has left or reached. */
function byClock(leg: OnBoardLeg, boardedAt: number, now: number): number {
  const s = (now - boardedAt) / 1000;
  let at = 0;
  leg.stops.forEach((stop, i) => {
    if (stop.after_s <= s) at = i;
  });
  return at;
}

/**
 * A fix (or none: the clock alone, from the ride screen's timer) into the leg. `said`: what the ride says now, in
 * order, through the rider's outputs (the voice, a screen reader). A rough fix alone never brings the stop to get off
 * nearer than two stops: the next one must agree before "Next stop" or "Get off here" is said.
 */
export function onBoardStep(leg: OnBoardLeg, state: OnBoardState, now: number, fix: RideFix | null = null): { state: OnBoardState; said: string[] } {
  if (state.done) return { state, said: [] };
  const next: OnBoardState = { ...state };
  const said: string[] = [];
  const last = leg.stops.length - 1;
  const placed = fix ? byFix(leg, state, fix, now) : null;
  let estimated = false;
  if (placed) {
    next.fixAt = now;
    const pending = state.pending ?? null;
    const agreed = placed.sure || (pending !== null && pending.boarded && placed.boarded);
    const at = placed.sure ? placed.at : pending && agreed ? Math.min(pending.at, placed.at) : Math.min(placed.at, last - 2);
    if (placed.boarded && agreed && next.boardedAt === null) next.boardedAt = now;
    if (next.boardedAt !== null) next.at = Math.max(next.at, at);
    next.pending = placed.sure ? null : { at: placed.at, boarded: placed.boarded };
  } else if (now - (next.fixAt ?? next.since) >= STALE_MS) {
    // No fix that places the rider for a while (underground with no Wi-Fi): the timetable, from the boarding seen,
    // else from the planned wait at the stop, or the last fix there if later (a train missed).
    const planned = next.since + leg.waitS * 1000;
    if (next.boardedAt === null && now - planned >= STALE_MS) next.boardedAt = Math.max(planned, next.fixAt ?? 0);
    if (next.boardedAt !== null) {
      const clock = byClock(leg, next.boardedAt, now);
      if (clock > next.at) {
        next.at = clock;
        estimated = true;
      }
    }
  }
  const off = leg.stops[last].name;
  if (next.boardedAt !== null && next.at >= last - 1 && !next.saidNext && next.at < last) {
    next.saidNext = true;
    if (estimated) said.push(t("Next stop should be {name}, by the timetable. Get off there.", { name: off }));
    else said.push(leg.bus ? t("Next stop: {name}. Press the stop button to get off there.", { name: off }) : t("Next stop: {name}. Get off there.", { name: off }));
  }
  if (next.boardedAt !== null && next.at >= last) {
    next.done = true;
    next.saidNext = true;
    if (!next.saidOff) {
      next.saidOff = true;
      said.push(estimated ? t("{name} should be about now, by the timetable. Get off there.", { name: off }) : t("Get off here: {name}.", { name: off }));
    }
  }
  return { state: next, said };
}

/** The card's lines: the stops still ahead, the next one marked; and how many are left. */
export function onBoardRows(leg: OnBoardLeg, state: OnBoardState): { name: string; passed: boolean; next: boolean; off: boolean }[] {
  const last = leg.stops.length - 1;
  const boarded = state.boardedAt !== null;
  return leg.stops.map((stop, i) => ({
    name: stop.name,
    passed: boarded ? i <= state.at && i < last : false,
    next: boarded && i === state.at + 1,
    off: i === last,
  }));
}

/** "3 stops left" from where the rider is (from the boarding stop while waiting). */
export function stopsLeftText(leg: OnBoardLeg, state: Pick<OnBoardState, "at">): string {
  const left = leg.stops.length - 1 - state.at;
  return left === 1 ? t("1 stop left") : t("{count} stops left", { count: left });
}

/**
 * The seconds to the stop to get off, on board (Stephen, 2026-11-04: "When on transit, put the approximate time left
 * to arrival"): the timetable's run from the last stop reached, less the time the train has been going since by the
 * clock, but never past the next stop, which is not reached yet (a late train holds there, an early one is taken
 * from the stop the fix says). Null while waiting to board.
 */
export function onBoardSecondsLeft(leg: Pick<OnBoardLeg, "stops">, state: Pick<OnBoardState, "at" | "boardedAt">, nowMs: number): number | null {
  if (state.boardedAt === null) return null;
  const last = leg.stops.length - 1;
  const at = Math.min(Math.max(0, state.at), last);
  const reached = leg.stops[at].after_s;
  const next = leg.stops[Math.min(at + 1, last)].after_s;
  const ridden = Math.min(Math.max((nowMs - state.boardedAt) / 1000, reached), next);
  return Math.max(0, leg.stops[last].after_s - ridden);
}

/**
 * Where am I? on transit (Stephen, 2026-11-04: it said "You have arrived at the end of the route" on the train): the
 * line and its way, the stop to get off and, on board, the stops and time left. `shown` as short lines, `spoken` whole.
 */
export function onBoardWhere(leg: OnBoardLeg, state: Pick<OnBoardState, "at" | "boardedAt">, nowMs: number, clock: (nowMs: number, seconds: number) => string): { shown: string[]; spoken: string } {
  const off = leg.stops[leg.stops.length - 1].name;
  const way = leg.toward && leg.toward !== off ? t("{line} toward {place}", { line: leg.line, place: leg.toward }) : leg.line;
  const getOff = t("Get off at {name}", { name: off });
  const left = onBoardSecondsLeft(leg, state, nowMs);
  if (left === null) return { shown: [way, getOff], spoken: `${way}. ${getOff}.` };
  const stops = stopsLeftText(leg, state);
  const time = `${formatDuration(left)} · ${clock(nowMs, left)}`;
  const said = `${stops}, ${t("about")} ${formatDuration(left)}${t(", arriving about")} ${clock(nowMs, left)}`;
  return { shown: [`${getOff}`, `${stops} · ${time}`], spoken: `${way}. ${getOff}. ${said}.` };
}

/** The line's colour on the map: its badge's (a Metro line's, the Penn Line's), else null for the map's transit colour. */
export function lineColour(lines: readonly string[]): string | null {
  for (const line of lines) {
    const badge = lineBadge(line);
    if (badge) return badge.background;
  }
  return null;
}

/** The train or bus's way on the ride's map: the stops still ahead joined in order, the one to get off marked. */
export interface OnBoardPath {
  coordinates: LonLat[];
  /** The line's colour (lineColour); null: the map's transit colour. */
  colour: string | null;
  stops: { point: LonLat; name: string; off: boolean }[];
  /** A bus's stops are not on the base map: the stop to get off is named on the line. */
  bus: boolean;
}

/**
 * The path drawn while waiting for the train or bus and on it (Stephen, 2026-11-04: "if you can show the path too"):
 * from the last stop reached (the boarding stop while waiting) to the stop to get off, through every stop between, so
 * a Metro line goes station to station. The timetable has no track shapes, so between two stops it is a straight line.
 */
export function onBoardPath(leg: Pick<OnBoardLeg, "stops" | "line" | "trains" | "bus">, at: number): OnBoardPath | null {
  const last = leg.stops.length - 1;
  const ahead = leg.stops.slice(Math.min(Math.max(0, at), Math.max(0, last - 1)));
  if (ahead.length < 2) return null;
  return {
    coordinates: ahead.map((stop) => stop.point),
    colour: lineColour([...(leg.trains ?? []).map((train) => train.line), leg.line]),
    stops: ahead.map((stop, i) => ({ point: stop.point, name: stop.name, off: i === ahead.length - 1 })),
    bus: leg.bus,
  };
}

/** The train or bus's path as the map's features: its line, then a point at each stop ahead. */
export function onBoardFeatures(path: OnBoardPath | null): { type: "FeatureCollection"; features: unknown[] } {
  if (!path) return { type: "FeatureCollection", features: [] };
  const colour = path.colour ?? TRANSIT_COLOUR;
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { colour }, geometry: { type: "LineString", coordinates: path.coordinates } },
      ...path.stops.map((stop) => ({ type: "Feature", properties: { colour, off: stop.off, bus: path.bus, name: stop.name }, geometry: { type: "Point", coordinates: stop.point } })),
    ],
  };
}

/**
 * The boarding card's "Next train" (Stephen, 2026-11-03: "Line, final destination, actual destination, next train"): a
 * timed departure as the minutes to it ("7 min"; Stephen, 2026-11-03: "7 min works fine too instead of being verbose"),
 * its time when an hour or more off, "Now" once due; a frequent service as how
 * often it runs ("every 5 min"); null where the plan says neither.
 */
export function nextDepartureText(leg: Pick<OnBoardLeg, "everyMin" | "departs">, departure: { departs: string; departs_at: string } | null, nowMs: number): string | null {
  if (departure) return timeAndMinutes(departure.departs, departure.departs_at, nowMs);
  if (leg.everyMin) return t("every {min} min", { min: String(leg.everyMin) });
  // The plan's countdown is another step's: the step's own time, as planned.
  return leg.departs ?? null;
}

/** The one after it, in case the rider can't make it (Stephen, 2026-11-03: "put the train after too"); null with none. */
export function laterDepartureText(departure: { next?: string | null; next_at?: string | null } | null, nowMs: number): string | null {
  if (!departure?.next) return null;
  return departure.next_at ? timeAndMinutes(departure.next, departure.next_at, nowMs) : departure.next;
}

function timeAndMinutes(time: string, iso: string, nowMs: number): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return time;
  const min = Math.ceil((at - nowMs) / 60_000);
  // Due: "Now" for two minutes, then the time alone (it may have left).
  if (min <= 0) return min > -2 ? t("Now") : time;
  return min < 60 ? t("{min} min", { min: String(min) }) : time;
}


/** A line's colour for its badge (WMATA's, the Penn Line's gold), and the text colour that reads on it; null for others. */
export function lineBadge(line: string): { background: string; color: string } | null {
  const name = line.toLowerCase();
  if (/\bpenn line$/.test(name)) return { background: PENN_COLOUR, color: "#ffffff" };
  for (const style of Object.values(METRO_LINES)) {
    if (name === `${style.label.toLowerCase()} line`) {
      // White reads at 4.5:1 only on Red (6.3:1); every other line's colour takes dark text (5.7:1 and up).
      return { background: style.color, color: style.key === "red" ? "#ffffff" : "#111827" };
    }
  }
  return null;
}

/**
 * The trains grouped by where they are signed to, in first-seen order, each with its lines in order: Orange and Silver
 * to New Carrollton, Blue and Silver to Downtown Largo. A train signed to the stop the rider gets off at shows no end.
 */
export function boardingGroups(trains: readonly { line: string; toward: string | null }[], off: string): { lines: string[]; toward: string | null }[] {
  const groups: { lines: string[]; toward: string | null }[] = [];
  for (const { line, toward } of trains) {
    const end = toward && toward !== off ? toward : null;
    const group = groups.find((g) => g.toward === end);
    if (!group) groups.push({ lines: [line], toward: end });
    else if (!group.lines.includes(line)) group.lines.push(line);
  }
  return groups;
}

/** A Metro station's live trains (core.transit_live.station): each line and way's next minutes, and where it ends. */
export interface LiveTrain {
  line: string;
  toward: string;
  /** WMATA's place for the train's last station; null where WMATA gave no code. */
  end?: LonLat | null;
  minutes: number[];
}

/** A live reading this old says nothing (core.transit_live.LIVE_FRESH_S). */
export const LIVE_FRESH_MS = 180_000;
/** A train's end station this much nearer the boarding than the rider's stop still counts as going there. */
const SHORT_TURN_SLACK_M = 400;

function colour(line: string): string {
  return line.toLowerCase().replace(/ line$/, "").trim();
}

/** A station's name to compare: "Vienna/Fairfax-GMU", "vienna fairfax gmu" alike. */
function nameKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Whether a train ending at `end` takes the rider from `board` to `alight`: it heads that way and goes at least that far. */
function goesTo(end: LonLat, board: LonLat, alight: LonLat): boolean {
  return haversineM(end, alight) < haversineM(end, board) && haversineM(board, end) >= haversineM(board, alight) - SHORT_TURN_SLACK_M;
}

/**
 * The boarding's live next trains, soonest first (Stephen, 2026-11-03: "Show the next train though", "If the next
 * train is orange show that one. If the one after is silver show that", "Skip the ones that don't go to the right
 * place"): only trains of the ride's lines that take the rider to the stop to get off, never one the other way, one
 * that turns back short of it, nor a line that does not make the ride. Where WMATA gave the train's end station, its
 * place decides; else its name must be one of that line's ends, or the stop to get off. Minutes count down from the
 * reading's time (`asOf`); a reading over LIVE_FRESH_MS old says nothing.
 */
export function liveForBoarding(
  live: readonly LiveTrain[],
  groups: readonly { lines: string[]; toward: string | null }[],
  stops: readonly { name: string; point?: LonLat | null }[],
  clock: { asOf?: string | null; nowMs?: number } = {},
): { line: string; toward: string; minutes: number }[] {
  if (stops.length === 0) return [];
  const board = stops[0].point ?? null;
  const last = stops[stops.length - 1];
  const off = nameKey(last.name);
  const asOf = clock.asOf ? Date.parse(clock.asOf) : NaN;
  const gone = Number.isFinite(asOf) && clock.nowMs != null ? Math.max(0, clock.nowMs - asOf) : 0;
  if (gone > LIVE_FRESH_MS) return [];
  const ends = new Map<string, Set<string>>();
  for (const group of groups) {
    for (const line of group.lines) {
      const set = ends.get(colour(line)) ?? new Set<string>();
      if (group.toward) set.add(nameKey(group.toward));
      ends.set(colour(line), set);
    }
  }
  const takes = (train: LiveTrain): boolean => {
    const lineEnds = ends.get(colour(train.line));
    if (!lineEnds) return false;
    if (train.end && board && last.point) return goesTo(train.end, board, last.point);
    const end = nameKey(train.toward);
    return lineEnds.has(end) || end === off;
  };
  return live
    .filter(takes)
    .flatMap((train) => train.minutes.map((minutes) => ({ line: train.line, toward: train.toward, minutes: Math.round(minutes - gone / 60_000) })))
    .filter((train) => train.minutes >= 0)
    .sort((a, b) => a.minutes - b.minutes);
}

/** A live train's minutes on the card: "3 min", "Arriving". */
export function liveNextText(minutes: number): string {
  return minutes <= 0 ? t("Arriving") : t("{min} min", { min: String(minutes) });
}
