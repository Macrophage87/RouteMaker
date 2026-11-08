/**
 * A ride left going (Stephen 2026-10-24: "I clicked out of the app and lost the route. Allow a way to resume if that
 * happens"): the ride's route and plan are kept on this device at Start ride, and taken away at End ride. A page
 * opened again with one kept asks to resume it; the ride then starts again where the rider is, and its first fix past
 * a stop asks which stops are done (RestartStopsDialog). Kept on the device only, never sent (the owner, 2026-10-22:
 * nothing of a ride stays on the server); no fixes, no track, no figures: only what was planned.
 */
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import type { ViaMarks } from "./pointKinds.ts";
import { t } from "./i18n.ts";
import { secretFrom } from "./rideSeal.ts";
import { leadKeyFrom, rideLinkFrom, sharedIdFrom } from "./sharedRoutes.ts";
import type { OnwardState } from "./onward.ts";
import type { StopsLeft } from "./tripStops.ts";
import type { RideStats } from "./rideStats.ts";
import type { RebalanceDocked } from "./rebalanceDock.ts";

export const RIDE_RESUME_KEY = "routemaker.ride-left";
/** A ride left longer than this is not offered: a day's ride, not yesterday's. */
export const RESUME_MAX_MS = 12 * 60 * 60_000;
/**
 * Left this recently (the page put away to switch apps, then reloaded by the phone): Resume carries on as the ride was,
 * without asking which stops are done (Stephen, 2026-11-07: it says the ride started part way along "even when just
 * briefly switching off"), and after a stop as long as lunch (2026-11-07: "Can the interval increase to a longer
 * interval than 10 minutes? What if you stop for Lunch?"). Longer away, the rider may have ridden on without it, so the
 * question stays.
 */
export const RESUME_QUIET_MS = 2 * 60 * 60_000;

export const RESUME_HEADING = t("Resume your ride?");
/** The question with the ride named where its destination has a name (the UI review, 2026-10-28). */
export function resumeHeading(destination: string | null | undefined): string {
  return destination ? t("Resume your ride to {place}?", { place: destination }) : RESUME_HEADING;
}
export const RESUME_LEAD = t("The app closed during a ride. Resume picks it up from where you are.");
export const RESUME_RIDE = t("Resume ride");
export const RESUME_NOT_NOW = t("Not now");

/**
 * What the ride's re-plans have learnt, kept with it so a Resume or a Keep riding re-plans as the ride did (the hunt,
 * round 2, R2-4 and R2-5): the ride is a loop (its re-plans' points begin at the rider, so they no longer show it), the
 * stretches marked Road closed, a dirt trail ridden, a dirt trail marked closed. Before, each began again empty, so a
 * page reloaded in the background re-planned over a road the rider had marked closed, a loop's way home became the way
 * out again, and a ride that had ridden dirt stopped re-planning on it.
 */
export interface RideReplans {
  loopRide?: boolean;
  blocked?: LonLat[][];
  dirtRidden?: boolean;
  dirtClosed?: boolean;
}

/** The ride's re-plan state as kept: only what is set, so a ride with none keeps nothing. */
export function rideReplans(loopRide: boolean, blocked: readonly LonLat[][], dirtRidden: boolean, dirtClosed: boolean): RideReplans {
  return {
    ...(loopRide ? { loopRide: true } : {}),
    ...(blocked.length ? { blocked: blocked.map((line) => line.map((p): LonLat => [p[0], p[1]])) } : {}),
    ...(dirtRidden ? { dirtRidden: true } : {}),
    ...(dirtClosed ? { dirtClosed: true } : {}),
  };
}

/** Kept re-plan state that reads as one (rideReplans), else null. */
function replansOf(value: unknown): RideReplans | null {
  const r = value as RideReplans | null;
  if (!r || typeof r !== "object") return null;
  const isPoint = (p: unknown) => Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number";
  const blocked = Array.isArray(r.blocked) ? r.blocked.filter((line) => Array.isArray(line) && line.length >= 2 && line.every(isPoint)) : [];
  const out = rideReplans(r.loopRide === true, blocked, r.dirtRidden === true, r.dirtClosed === true);
  return Object.keys(out).length ? out : null;
}

export interface LeftRide {
  route: RouteResponse;
  points: LonLat[];
  loop: boolean;
  preset: PresetId;
  dials: Dials;
  fixed: boolean;
  /** The destination's name as the map gave it at Start ride, for the question (resumeHeading); none for a loop. */
  destination?: string | null;
  /**
   * Following someone else's broadcast: its link, which Share live passes on once resumed too, its sharer still the
   * leader (Stephen 2026-10-29: "A ride opened should allow sharing too"). Kept on this device only, never sent.
   * Left out by a mid-ride re-route, which keeps the one kept at Start.
   */
  passOn?: string | null;
  /** Following someone else's broadcast, its link passed on or not (one without its key is not): never the rider's own. */
  follows?: boolean;
  /**
   * Leading a broadcast of the rider's own: its link, so a resumed ride is that broadcast again and its riders still
   * see the leader (Stephen 2026-10-30). Kept on this device only, never sent. Left out by a re-route, which keeps it.
   */
  leads?: string | null;
  /**
   * A Bikeshare or transit trip (Stephen 2026-11-04: on the train, "when switching off it terminated the route without
   * offering a resume", switching apps): `route` and `points` are the whole trip's, its riding leg worked out again at
   * Resume (lib/rideTrip.ts rideLegOf).
   */
  wholeTrip?: boolean;
  /** Past the trip's line: the walk or train being followed (lib/onward.ts), so Resume carries on with it. */
  past?: OnwardState | null;
  /** A trip with stops: the stops after the trip ridden (lib/tripStops.ts), so Resume still offers "Start the next leg". */
  stopsLeft?: StopsLeft | null;
  /** When the page was last put away mid-ride (seeLeftRide), if it was. */
  seen?: number | null;
  /** The ride's figures then (distance, time, climb), so a quick Resume carries them on rather than starting at 0. */
  stats?: RideStats | null;
  /**
   * A Rebalance Ride's drop-off, chosen at the pick-up dock (lib/rebalanceDock.ts), and the ride to it: Resume rides on
   * to it rather than walking back to the crowded dock (the v0.22.0 review: the choice was lost on a reload).
   */
  docked?: RebalanceDocked | null;
  /** What the ride's re-plans have learnt (RideReplans), so Resume re-plans as the ride did. */
  replans?: RideReplans | null;
}

/** Points kept with their kinds and names, which live on the pairs (lib/pointKinds.ts). */
interface KeptPoints {
  points: LonLat[];
  /** The ride's own via points among `vias` (ViaMarks.shape); absent where there are none. */
  shapes?: number[];
  vias: number[];
  drawn: number[];
  names: [number, string][];
}

interface Kept {
  v: 1;
  at: number;
  route: RouteResponse;
  points: LonLat[];
  shapes?: number[];
  vias: number[];
  drawn: number[];
  names: [number, string][];
  loop: boolean;
  preset: PresetId;
  dials: Dials;
  fixed: boolean;
  destination?: string;
  passOn?: string;
  follows?: boolean;
  leads?: string;
  trip?: boolean;
  past?: OnwardState;
  stops?: KeptPoints & { preset: PresetId };
  seen?: number;
  stats?: RideStats;
  docked?: RebalanceDocked;
  replans?: RideReplans;
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Kept at Start ride: the plan's points with their kinds and names, which live on the pairs (lib/pointKinds.ts). */
function keptPoints(points: readonly LonLat[], marks: Pick<ViaMarks, "isVia" | "isDrawn" | "nameOf"> & Partial<Pick<ViaMarks, "isShape">>): KeptPoints {
  // A ride's own via points (a loop's way home, ViaMarks.shape) stay the ride's own when it is resumed.
  const shapes = marks.isShape ? points.flatMap((p, i) => (marks.isShape?.(p) ? [i] : [])) : [];
  return {
    points: points.map((p) => [p[0], p[1]]),
    ...(shapes.length ? { shapes } : {}),
    vias: points.flatMap((p, i) => (marks.isVia(p) ? [i] : [])),
    drawn: points.flatMap((p, i) => (marks.isDrawn(p) ? [i] : [])),
    names: points.flatMap((p, i): [number, string][] => {
      const name = marks.nameOf(p);
      return name ? [[i, name]] : [];
    }),
  };
}

/** Kept points marked again as they were. */
function markedPoints(kept: Partial<KeptPoints>, marks: Pick<ViaMarks, "via" | "drawn" | "named"> & Partial<Pick<ViaMarks, "shape">>): LonLat[] {
  const names = new Map(Array.isArray(kept.names) ? kept.names : []);
  return (kept.points ?? []).map(([lon, lat], i): LonLat => {
    let p: LonLat = [lon, lat];
    p = marks.named(p, names.get(i));
    if (Array.isArray(kept.shapes) && kept.shapes.includes(i) && marks.shape) p = marks.shape(p);
    else if (kept.vias?.includes(i)) p = marks.via(p);
    if (kept.drawn?.includes(i)) p = marks.drawn(p);
    return p;
  });
}

export function keepLeftRide(ride: LeftRide, marks: Pick<ViaMarks, "isVia" | "isDrawn" | "nameOf"> & Partial<Pick<ViaMarks, "isShape">>, now: number, store: Store | null = local()): void {
  // A re-route kept mid-ride says no name: the one kept at Start goes on while the ride ends at the same place.
  const destination = ride.loop ? null : (ride.destination ?? keptDestination(ride.points[ride.points.length - 1], store));
  const was = ride.passOn === undefined ? keptFollow(store) : null;
  const passOn = was ? was.passOn : (ride.passOn ?? null);
  const follows = was ? was.follows : ride.follows === true;
  // Kept through a re-route (which says nothing of either link), never into a new ride, which names its own.
  const leads = ride.leads !== undefined ? ride.leads : ride.passOn === undefined ? keptLeads(store) : null;
  const kept: Kept = {
    v: 1,
    at: now,
    route: ride.route,
    ...keptPoints(ride.points, marks),
    loop: ride.loop,
    preset: ride.preset,
    dials: ride.dials,
    fixed: ride.fixed,
    ...(destination ? { destination } : {}),
    ...(passOn ? { passOn } : {}),
    ...(follows ? { follows } : {}),
    ...(leads ? { leads } : {}),
    ...(ride.wholeTrip ? { trip: true } : {}),
    ...(ride.wholeTrip && ride.past ? { past: ride.past } : {}),
    ...(ride.stopsLeft && ride.stopsLeft.points.length > 0 ? { stops: { preset: ride.stopsLeft.preset, ...keptPoints(ride.stopsLeft.points, marks) } } : {}),
    ...(ride.wholeTrip && ride.docked ? { docked: plainDocked(ride.docked) } : {}),
    ...(replansOf(ride.replans) ? { replans: replansOf(ride.replans)! } : {}),
  };
  try {
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify(kept));
  } catch {
    // Full or blocked storage: the ride goes on, only not resumable.
  }
}

/** The name kept with the ride already stored, where that ride ends at `end`. */
function keptDestination(end: LonLat | undefined, store: Store | null): string | null {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    const was = raw ? (JSON.parse(raw) as Partial<Kept>) : null;
    const last = was?.points?.[was.points.length - 1];
    return end && last && last[0] === end[0] && last[1] === end[1] && typeof was?.destination === "string" ? was.destination : null;
  } catch {
    return null;
  }
}

/** The broadcast the ride already stored follows, if any, and its link to pass on. */
function keptFollow(store: Store | null): { passOn: string | null; follows: boolean } {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    const was = raw ? (JSON.parse(raw) as Partial<Kept>) : null;
    return { passOn: typeof was?.passOn === "string" ? was.passOn : null, follows: was?.follows === true };
  } catch {
    return { passOn: null, follows: false };
  }
}

/** The broadcast link the ride already stored leads, if any. */
function keptLeads(store: Store | null): string | null {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    const was = raw ? (JSON.parse(raw) as Partial<Kept>) : null;
    return typeof was?.leads === "string" ? was.leads : null;
  } catch {
    return null;
  }
}

/** A broadcast started during the ride (Share live): its link kept with the ride left going, so Resume leads it again. */
export function keepLeftRideLeads(link: string, store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const was = JSON.parse(raw) as Kept;
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify({ ...was, leads: link }));
  } catch {
    // Full or blocked storage: the ride goes on, only resumed without its broadcast.
  }
}

/** The dock and its ride as plain data: its two points without their marks. */
function plainDocked(docked: RebalanceDocked): RebalanceDocked {
  return { name: docked.name, route: docked.route, points: docked.points.map((p): LonLat => [p[0], p[1]]) };
}

/** A kept dock as written by keepLeftRideDocked; null for anything else. */
function dockedOf(value: unknown): RebalanceDocked | null {
  const d = value as Partial<RebalanceDocked> | null;
  const shaped = !!d && typeof d === "object" && typeof d.name === "string" && Array.isArray(d.points) && d.points.length >= 2 && Array.isArray(d.route?.geometry?.coordinates);
  return shaped ? { name: d.name!, route: d.route!, points: d.points!.map((p): LonLat => [p[0], p[1]]) } : null;
}

/** A Rebalance Ride's drop-off chosen at the pick-up dock: kept with the trip left going, so Resume rides on to it. */
export function keepLeftRideDocked(docked: RebalanceDocked, store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const was = JSON.parse(raw) as Kept;
    if (!was.trip) return;
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify({ ...was, docked: plainDocked(docked) }));
  } catch {
    // Full or blocked storage: Resume walks to the crowded dock and asks again, as before.
  }
}

/** A trip past its line: the part followed now kept with the trip left going, so Resume carries on from it. */
export function keepLeftRidePast(past: OnwardState, store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const was = JSON.parse(raw) as Kept;
    if (!was.trip) return;
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify({ ...was, past }));
  } catch {
    // Full or blocked storage: Resume starts the trip's leg again instead.
  }
}

/** What the ride's re-plans have learnt since it was last kept (a dirt trail ridden, at a fix): kept with it in place. */
export function keepLeftRideReplans(replans: RideReplans, store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const { replans: _was, ...kept } = JSON.parse(raw) as Kept;
    const now = replansOf(replans);
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify(now ? { ...kept, replans: now } : kept));
  } catch {
    // Full or blocked storage: Resume re-plans without it, as before.
  }
}

/** The walk or train a trip left going was following, as last kept (End ride reads it, so Undo carries on from it). */
export function leftRidePast(store: Store | null = local()): OnwardState | null {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    const was = raw ? (JSON.parse(raw) as Partial<Kept>) : null;
    return was?.trip === true ? pastOf(was.past) : null;
  } catch {
    return null;
  }
}

/** A kept onward state as written by keepLeftRidePast; null for anything else. */
function pastOf(value: unknown): OnwardState | null {
  const past = value as Partial<OnwardState> | null;
  if (!past || typeof past !== "object" || typeof past.index !== "number" || typeof past.since !== "number") return null;
  return { index: past.index, since: past.since, walk: past.walk ?? null, board: past.board ?? null };
}

/**
 * The broadcast a resumed ride is on again (Stephen 2026-10-30: a follower's Yes reached nobody once her page had
 * reloaded mid-ride, as a phone does to a page left in the background, and Resume brought back the route alone): the
 * link it followed, or the one it leads, read as the page reads a link it opens. Null for a ride on no broadcast, or a
 * link without its leader or key (nothing can be read or sent for it).
 */
export function resumedBroadcast(left: Pick<LeftRide, "passOn" | "follows" | "leads">): { id: string; lead: string; secret: string; own: boolean } | null {
  const own = !left.follows && !!left.leads;
  const link = own ? left.leads : left.follows ? left.passOn : null;
  if (!link) return null;
  let url: URL;
  try {
    url = new URL(link);
  } catch {
    return null;
  }
  const id = sharedIdFrom(url.hash, url.search, url.pathname);
  const lead = rideLinkFrom(url.hash, url.search) ? leadKeyFrom(url.hash, url.search) : null;
  const secret = secretFrom(url.hash);
  return id && lead && secret ? { id, lead, secret, own } : null;
}

/** Taken away at End ride, at Not now, and when a ride starts that is not kept. */
export function forgetLeftRide(store: Store | null = local()): void {
  try {
    store?.removeItem(RIDE_RESUME_KEY);
  } catch {
    // Nothing to do.
  }
}

/** The ride left going, its points marked again as they were; null with none, or one too old or unreadable. */
export function leftRide(marks: Pick<ViaMarks, "via" | "drawn" | "named"> & Partial<Pick<ViaMarks, "shape">>, now: number, store: Store | null = local()): LeftRide | null {
  let kept: Kept;
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return null;
    kept = JSON.parse(raw) as Kept;
  } catch {
    return null;
  }
  const fresh = kept?.v === 1 && typeof kept.at === "number" && now - kept.at >= 0 && now - kept.at <= RESUME_MAX_MS;
  // A loop planned from its start alone (a run by distance, kept whole as a trip) has that one point.
  const fewest = kept?.loop === true ? 1 : 2;
  const shaped = fresh && Array.isArray(kept.points) && kept.points.length >= fewest && Array.isArray(kept.route?.geometry?.coordinates);
  if (!shaped) {
    forgetLeftRide(store);
    return null;
  }
  const points = markedPoints(kept, marks);
  const docked = kept.trip === true ? dockedOf(kept.docked) : null;
  const stops = kept.stops && Array.isArray(kept.stops.points) && kept.stops.points.length > 0 && typeof kept.stops.preset === "string" ? kept.stops : null;
  return {
    route: kept.route,
    points,
    loop: kept.loop === true,
    preset: kept.preset,
    dials: kept.dials,
    fixed: kept.fixed === true,
    ...(typeof kept.destination === "string" ? { destination: kept.destination } : {}),
    ...(typeof kept.passOn === "string" ? { passOn: kept.passOn } : {}),
    ...(kept.follows === true ? { follows: true } : {}),
    ...(typeof kept.leads === "string" ? { leads: kept.leads } : {}),
    ...(kept.trip === true ? { wholeTrip: true, past: pastOf(kept.past) } : {}),
    ...(stops ? { stopsLeft: { preset: stops.preset, points: markedPoints(stops, marks) } } : {}),
    ...(typeof kept.seen === "number" ? { seen: kept.seen } : {}),
    ...(statsOf(kept.stats) ? { stats: kept.stats } : {}),
    ...(docked ? { docked } : {}),
    ...(replansOf(kept.replans) ? { replans: replansOf(kept.replans) } : {}),
  };
}

/** Kept figures that read as the ride's own (RideStats), else null. */
function statsOf(value: unknown): RideStats | null {
  const s = value as Partial<RideStats> | null;
  return s && typeof s === "object" && typeof s.startedAt === "number" && typeof s.distanceM === "number" && typeof s.movingMs === "number" ? (s as RideStats) : null;
}

/**
 * The page put away mid-ride (another app, the screen off): when, and the ride's figures then, on the kept ride, for a
 * quiet Resume (Stephen 2026-11-07: switching off "resets progress"). Kept on this device only, as the ride is; the
 * last fix and its line are left out (the next fix starts again, as after a pause).
 */
export function seeLeftRide(now: number, stats: RideStats | null = null, store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const figures = stats ? { ...stats, last: null } : undefined;
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify({ ...(JSON.parse(raw) as Kept), seen: now, ...(figures ? { stats: figures } : {}) }));
  } catch {
    // Full or blocked storage: Resume asks which stops are done, as before.
  }
}

/** Back on the page: the note of it put away is dropped, so a reload later (the figures by then older) asks as before. */
export function unseeLeftRide(store: Store | null = local()): void {
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return;
    const { seen: _seen, stats: _stats, ...kept } = JSON.parse(raw) as Kept;
    store?.setItem(RIDE_RESUME_KEY, JSON.stringify(kept));
  } catch {
    // Full or blocked storage: nothing kept to drop.
  }
}

/** Resumed within RESUME_QUIET_MS of the page being put away: the ride carries on without "Already done?". */
export function resumesQuietly(left: Pick<LeftRide, "seen">, now: number): boolean {
  return typeof left.seen === "number" && now - left.seen >= 0 && now - left.seen <= RESUME_QUIET_MS;
}
