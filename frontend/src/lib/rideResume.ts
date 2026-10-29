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

export const RIDE_RESUME_KEY = "routemaker.ride-left";
/** A ride left longer than this is not offered: a day's ride, not yesterday's. */
export const RESUME_MAX_MS = 12 * 60 * 60_000;

export const RESUME_HEADING = t("Resume your ride?");
/** The question with the ride named where its destination has a name (the UI review, 2026-10-28). */
export function resumeHeading(destination: string | null | undefined): string {
  return destination ? t("Resume your ride to {place}?", { place: destination }) : RESUME_HEADING;
}
export const RESUME_LEAD = t("The app closed during a ride. Resume picks it up from where you are.");
export const RESUME_RIDE = t("Resume ride");
export const RESUME_NOT_NOW = t("Not now");

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
}

interface Kept {
  v: 1;
  at: number;
  route: RouteResponse;
  points: LonLat[];
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
export function keepLeftRide(ride: LeftRide, marks: Pick<ViaMarks, "isVia" | "isDrawn" | "nameOf">, now: number, store: Store | null = local()): void {
  // A re-route kept mid-ride says no name: the one kept at Start goes on while the ride ends at the same place.
  const destination = ride.loop ? null : (ride.destination ?? keptDestination(ride.points[ride.points.length - 1], store));
  const was = ride.passOn === undefined ? keptFollow(store) : null;
  const passOn = was ? was.passOn : (ride.passOn ?? null);
  const follows = was ? was.follows : ride.follows === true;
  const kept: Kept = {
    v: 1,
    at: now,
    route: ride.route,
    points: ride.points.map((p) => [p[0], p[1]]),
    vias: ride.points.flatMap((p, i) => (marks.isVia(p) ? [i] : [])),
    drawn: ride.points.flatMap((p, i) => (marks.isDrawn(p) ? [i] : [])),
    names: ride.points.flatMap((p, i): [number, string][] => {
      const name = marks.nameOf(p);
      return name ? [[i, name]] : [];
    }),
    loop: ride.loop,
    preset: ride.preset,
    dials: ride.dials,
    fixed: ride.fixed,
    ...(destination ? { destination } : {}),
    ...(passOn ? { passOn } : {}),
    ...(follows ? { follows } : {}),
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

/** Taken away at End ride, at Not now, and when a ride starts that is not kept. */
export function forgetLeftRide(store: Store | null = local()): void {
  try {
    store?.removeItem(RIDE_RESUME_KEY);
  } catch {
    // Nothing to do.
  }
}

/** The ride left going, its points marked again as they were; null with none, or one too old or unreadable. */
export function leftRide(marks: Pick<ViaMarks, "via" | "drawn" | "named">, now: number, store: Store | null = local()): LeftRide | null {
  let kept: Kept;
  try {
    const raw = store?.getItem(RIDE_RESUME_KEY);
    if (!raw) return null;
    kept = JSON.parse(raw) as Kept;
  } catch {
    return null;
  }
  const fresh = kept?.v === 1 && typeof kept.at === "number" && now - kept.at >= 0 && now - kept.at <= RESUME_MAX_MS;
  const shaped = fresh && Array.isArray(kept.points) && kept.points.length >= 2 && Array.isArray(kept.route?.geometry?.coordinates);
  if (!shaped) {
    forgetLeftRide(store);
    return null;
  }
  const names = new Map(Array.isArray(kept.names) ? kept.names : []);
  const points = kept.points.map(([lon, lat], i): LonLat => {
    let p: LonLat = [lon, lat];
    p = marks.named(p, names.get(i));
    if (kept.vias?.includes(i)) p = marks.via(p);
    if (kept.drawn?.includes(i)) p = marks.drawn(p);
    return p;
  });
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
  };
}
