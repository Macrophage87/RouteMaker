/**
 * "Use my location" (OWNER-DECISIONS 395): one browser look-up per press, set
 * as a point like a map click. The browser's geolocation sits behind `GeoEnv`,
 * so tests stub success, each error and the insecure context; `browserEnv`
 * is the one place that reads `window`.
 *
 * No watchPosition and no tracking: `locate` asks once. The position is not
 * stored or logged here. Whether the plan's start came from it is kept in
 * memory only, by App (never in localStorage, the link hash or a GPX file).
 */
import { formatDistance } from "./format.ts";
import { pointName } from "./summary.ts";
import type { LonLat } from "./geo.ts";

/** A high-accuracy look-up, given 10 seconds, that may reuse a fix up to 30 seconds old. */
export const LOCATE_OPTIONS = { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 } as const;

/** The part of the browser's Geolocation the page uses. */
export interface GeoApi {
  getCurrentPosition(
    ok: (position: { coords: { latitude: number; longitude: number; accuracy: number } }) => void,
    fail: (error: { code: number }) => void,
    options?: { enableHighAccuracy?: boolean; timeout?: number; maximumAge?: number },
  ): void;
}

export interface GeoEnv {
  /** window.isSecureContext: HTTPS, localhost, and the beta are all secure. */
  isSecureContext: boolean;
  geolocation: GeoApi | undefined;
}

export type LocateFailure = "denied" | "unavailable" | "timeout" | "unsupported" | "insecure";

export interface Fix {
  point: LonLat;
  /** The browser's 68% radius, in metres. */
  accuracyM: number;
}

export type LocateResult = { ok: true; fix: Fix } | { ok: false; reason: LocateFailure };

/** The browser's own environment: the only reader of window and navigator for this feature. */
export function browserEnv(): GeoEnv {
  const secure = typeof window !== "undefined" && window.isSecureContext === true;
  const geolocation = typeof navigator !== "undefined" && "geolocation" in navigator ? navigator.geolocation : undefined;
  return { isSecureContext: secure, geolocation };
}

export const LOCATE_MESSAGES: Record<LocateFailure, string> = {
  denied: "Your location is blocked for this site. Allow location in the browser's site settings, or search for a place.",
  unavailable: "Your location could not be found right now. Try again, or search for a place.",
  timeout: "Finding your location took too long. Try again, or search for a place.",
  unsupported: "This browser cannot share your location. Search for a place instead.",
  insecure: "Your location can only be used on a secure (HTTPS) page. Search for a place instead.",
};

/** Whether the button can work here, and if not, why (shown as its reason). */
export function locateSupport(env: GeoEnv): { available: true } | { available: false; reason: string } {
  if (!env.isSecureContext) return { available: false, reason: LOCATE_MESSAGES.insecure };
  if (!env.geolocation) return { available: false, reason: LOCATE_MESSAGES.unsupported };
  return { available: true };
}

/** A GeolocationPositionError code: 1 denied, 2 unavailable, 3 timeout. */
export function failureFor(code: number): LocateFailure {
  if (code === 1) return "denied";
  if (code === 3) return "timeout";
  return "unavailable";
}

function usable(lat: number, lon: number): boolean {
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
}

/** One look-up. Never rejects: every outcome is a result. */
export function locate(env: GeoEnv): Promise<LocateResult> {
  if (!env.isSecureContext) return Promise.resolve({ ok: false, reason: "insecure" });
  const api = env.geolocation;
  if (!api) return Promise.resolve({ ok: false, reason: "unsupported" });
  return new Promise((resolve) => {
    try {
      api.getCurrentPosition(
        ({ coords }) => {
          if (!usable(coords.latitude, coords.longitude)) {
            resolve({ ok: false, reason: "unavailable" });
            return;
          }
          const accuracy = Number.isFinite(coords.accuracy) && coords.accuracy >= 0 ? coords.accuracy : 0;
          resolve({ ok: true, fix: { point: [coords.longitude, coords.latitude], accuracyM: accuracy } });
        },
        (error) => resolve({ ok: false, reason: failureFor(error.code) }),
        { ...LOCATE_OPTIONS },
      );
    } catch {
      resolve({ ok: false, reason: "unavailable" });
    }
  });
}

/** "about 50 ft (15 m)", or "" when the browser gave no accuracy. */
export function accuracyText(accuracyM: number): string {
  return accuracyM > 0 ? `about ${formatDistance(accuracyM)}` : "";
}

/** Whether the search box's text asks for the rider's location: empty, or the start of a phrase for it (two letters or more). */
export function locationMatches(query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return q.length >= 2 && ["your location", "my location", "current location"].some((phrase) => phrase.startsWith(q));
}

export const FINDING_LOCATION = "Finding your location…";

/**
 * What is said when the position became point `index` of a plan of `count`:
 * "Start set to your location, accurate to about 49 ft (15 m)."
 */
export function locationSaid(index: number, count: number, loop: boolean, accuracyM: number): string {
  const accuracy = accuracyText(accuracyM);
  return `${pointName(index, count, loop)} set to your location${accuracy ? `, accurate to ${accuracy}` : ""}.`;
}

/** The note under the search once a point is the rider's location: approximate, and still movable. */
export function approximateHint(accuracyM: number): string {
  const accuracy = accuracyText(accuracyM);
  return `Your location is approximate${accuracy ? `, to ${accuracy}` : ""}. Drag its marker to adjust it.`;
}

/** Copy link's one-line note (OWNER-DECISIONS 395); a location that is not the start is said as a point. */
export const LINK_HAS_LOCATION_START = "This link includes your location as the start.";
export const LINK_HAS_LOCATION_POINT = "This link includes your location as a point on the route.";

/**
 * The note for a link of `points`, given the position point objects (kept in
 * memory by App; empty if none). Identity, not equality: a moved marker is a new
 * array, so moving the start clears the note with no flag to forget.
 */
export function linkLocationNote(points: readonly LonLat[], from: readonly LonLat[]): string {
  if (points.length > 0 && from.includes(points[0])) return LINK_HAS_LOCATION_START;
  return points.some((point) => from.includes(point)) ? LINK_HAS_LOCATION_POINT : "";
}

/** A circle of `radiusM` metres round `centre` as a closed ring (the accuracy circle on the map). */
export function accuracyRing(centre: LonLat, radiusM: number, steps = 48): LonLat[] {
  const [lon, lat] = centre;
  const dLat = radiusM / 111_320;
  const dLon = radiusM / (111_320 * Math.max(0.01, Math.cos((lat * Math.PI) / 180)));
  const ring: LonLat[] = [];
  for (let i = 0; i < steps; i += 1) {
    const a = (2 * Math.PI * i) / steps;
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  ring.push(ring[0]);
  return ring;
}
