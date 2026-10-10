/**
 * Ride mode's position watch (WEB-NAV-plan.md section 2): the one `watchPosition` in the app. Started
 * by the rider's Start ride press, cleared at End ride, after a long page hide and on unmount
 * (RideMode.tsx). Outside Ride mode the app still asks for the location once per press and never
 * watches (lib/geolocation.ts, OWNER-DECISIONS 395).
 *
 * The browser sits behind `RideGeoEnv`, as geolocation.ts keeps it behind `GeoEnv`, so tests stub it.
 * Nothing here stores, logs or sends a fix: each goes to the caller's handler and is forgotten.
 */
import { LOCATE_MESSAGES, cleanAccuracy, failureFor, type LocateFailure } from "./geolocation.ts";
import type { RideFix } from "./navigate.ts";

/** High accuracy, a fix at most 2 s old, and 15 s before the browser reports a timeout (plan section 2). */
export const WATCH_OPTIONS = { enableHighAccuracy: true, maximumAge: 2_000, timeout: 15_000 } as const;

export interface WatchPosition {
  coords: { latitude: number; longitude: number; accuracy: number; speed?: number | null; heading?: number | null };
  timestamp?: number;
}

export interface WatchApi {
  watchPosition(ok: (position: WatchPosition) => void, fail: (error: { code: number }) => void, options?: typeof WATCH_OPTIONS): number;
  clearWatch(id: number): void;
}

export interface RideGeoEnv {
  isSecureContext: boolean;
  geolocation: WatchApi | undefined;
}

export function browserRideEnv(): RideGeoEnv {
  const secure = typeof window !== "undefined" && window.isSecureContext === true;
  const geolocation = typeof navigator !== "undefined" && "geolocation" in navigator ? (navigator.geolocation as unknown as WatchApi) : undefined;
  return { isSecureContext: secure, geolocation };
}

/** Why a ride cannot watch here, or null where it can: the same sentences as "Use my location". */
export function watchUnavailable(env: RideGeoEnv): string | null {
  if (!env.isSecureContext) return LOCATE_MESSAGES.insecure;
  if (!env.geolocation) return LOCATE_MESSAGES.unsupported;
  return null;
}

/** Shown while the browser has no fix (a timeout keeps the watch going: GPS may come back). */
export const WAITING_FOR_GPS = "Waiting for a GPS fix.";

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Watch the position: each usable fix to `onFix`; a failure to `onFail` (a timeout is not the end of
 * the watch, a refusal is, and the caller stops it). Answers the stop function.
 */
export function watchRide(
  env: RideGeoEnv,
  onFix: (fix: RideFix) => void,
  onFail: (reason: LocateFailure) => void,
  now: () => number = () => Date.now(),
): () => void {
  const api = env.geolocation;
  if (!api || !env.isSecureContext) {
    onFail(env.isSecureContext ? "unsupported" : "insecure");
    return () => undefined;
  }
  let live = true;
  const id = api.watchPosition(
    (position) => {
      if (!live) return;
      const { latitude, longitude } = position.coords;
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return;
      const speed = finite(position.coords.speed);
      const heading = finite(position.coords.heading);
      onFix({
        point: [longitude, latitude],
        accuracyM: cleanAccuracy(position.coords.accuracy),
        speedMs: speed !== null && speed >= 0 ? speed : null,
        headingDeg: heading !== null && speed !== null && speed > 0.5 ? heading : null,
        at: now(),
      });
    },
    (error) => {
      if (live) onFail(failureFor(error.code));
    },
    WATCH_OPTIONS,
  );
  return () => {
    if (!live) return;
    live = false;
    api.clearWatch(id);
  };
}
