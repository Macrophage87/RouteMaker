/**
 * "Use my location" (OWNER-DECISIONS 395): one browser look-up per press, set
 * as a point like a map click. The browser's geolocation sits behind `GeoEnv`,
 * so tests stub success, each error and the insecure context; `browserEnv`
 * is the one place that reads `window`.
 *
 * No watchPosition and no tracking here: `locate` asks once (and once more, less
 * precisely, after a timeout). The one watcher in the app is Ride mode's
 * (lib/rideWatch.ts), started by the rider's Start ride press and cleared at
 * End ride. Nothing here stores or logs the position. The
 * point itself goes into the plan like any clicked point, so it is in the
 * address bar, the copied link and a GPX file at full precision, by design.
 * What is never in the link, a GPX file, storage or a log is the flag that a
 * point came from the location, and its accuracy: App keeps those in memory.
 */
import { formatRadius } from "./format.ts";
import { pointName } from "./summary.ts";
import { MAX_POINTS, addPoint, insideCoverage, type LonLat } from "./geo.ts";
import { applyPlace, placeEffect, type PlaceChoice, type PlaceEffect } from "./geocode.ts";
import { language, t } from "./i18n.ts";

/** A high-accuracy look-up, given 10 seconds, that may reuse a fix up to 30 seconds old. */
export const LOCATE_OPTIONS = { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 } as const;
/** After a timeout, one more try without high accuracy (a phone's GPS is often cold at first); the same press. */
export const RETRY_OPTIONS = { enableHighAccuracy: false, timeout: 10_000, maximumAge: 30_000 } as const;
/**
 * The app's own limit on one look-up. The browser's `timeout` only runs once
 * permission is given, and some browsers never answer a prompt that was
 * dismissed or ignored; without this the button would stay busy for the visit.
 */
export const LOCATE_WATCHDOG_MS = LOCATE_OPTIONS.timeout + 20_000;
/** The retry runs only after permission was given, so its limit is close to its timeout. */
export const RETRY_WATCHDOG_MS = RETRY_OPTIONS.timeout + 5_000;
/**
 * While the browser's permission prompt is open (the Permissions API says "prompt"), the first
 * look-up's limit instead: reading the prompt is the rider's time, not the GPS's (the correctness
 * re-review's W1). When the browser reports the prompt answered (a "change" event to a state other
 * than "prompt"), LOCATE_WATCHDOG_MS starts again from then. Some browsers keep reporting "prompt"
 * after the rider allows; there this cap stays 60 s from the press. A browser without the
 * Permissions API keeps LOCATE_WATCHDOG_MS from the press.
 */
export const PROMPT_WATCHDOG_MS = 60_000;

/** The part of the browser's Geolocation the page uses. */
export interface GeoApi {
  getCurrentPosition(
    ok: (position: { coords: { latitude: number; longitude: number; accuracy: number } }) => void,
    fail: (error: { code: number }) => void,
    options?: { enableHighAccuracy?: boolean; timeout?: number; maximumAge?: number },
  ): void;
}

/** The part of a PermissionStatus the watchdog reads: whether the prompt is open, and when that changes. */
export interface PermissionLike {
  readonly state: string;
  addEventListener(type: "change", listener: () => void): void;
  removeEventListener(type: "change", listener: () => void): void;
}

export interface GeoEnv {
  /** window.isSecureContext: HTTPS, localhost, and the beta are all secure. */
  isSecureContext: boolean;
  geolocation: GeoApi | undefined;
  /** navigator.permissions.query for geolocation, when the browser has it; undefined on any failure. */
  permission?: () => Promise<PermissionLike | undefined>;
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
  const permissions = typeof navigator !== "undefined" ? navigator.permissions : undefined;
  if (typeof permissions?.query !== "function") return { isSecureContext: secure, geolocation };
  const permission = (): Promise<PermissionLike | undefined> =>
    permissions.query({ name: "geolocation" }).then(
      (status) => status,
      () => undefined,
    );
  return { isSecureContext: secure, geolocation, permission };
}

/**
 * Whether the page runs as an iPhone or iPad Home Screen web app: `navigator.standalone` exists only in
 * iOS WebKit and is true only there. Such an app has no address bar and no site settings, and iOS keeps
 * its location permission apart from Safari's: a tester's Home Screen app reported "blocked" without ever
 * asking while the same site in a Safari tab could use the location. So its denied notice names the
 * iPhone's own settings instead.
 */
export function iosHomeScreenApp(nav: unknown = typeof navigator !== "undefined" ? navigator : undefined): boolean {
  return (nav as { standalone?: unknown } | undefined)?.standalone === true;
}

/** The denied notice in a browser tab. */
export const DENIED_IN_BROWSER = t("Your location is blocked for this site. Allow location in the browser's site settings, or search for a place.");
/** The denied notice in an iPhone Home Screen app (see iosHomeScreenApp); the tester steps are in docs/OPERATIONS.md. */
export const DENIED_IN_IOS_APP = t("Your location is blocked for this Home Screen app. Check Location in iPhone Settings, or search for a place.");

/**
 * The fold under that notice (IosLocationHelp.tsx). A web app cannot open iPhone Settings, so tapping the notice
 * went nowhere (a tester, 2026-10-28); the fold says where to go instead. In-App Web Browsing first: the tester's
 * Home Screen app stayed blocked while it was off, though Safari tabs worked.
 */
export const IOS_LOCATION_HELP_TITLE = t("How to turn location on");
export const IOS_LOCATION_STEPS: readonly string[] = [
  t("Open the **Settings** app, then **Privacy & Security**, then **Location Services**."),
  t("Turn **Location Services** on. Open **System Services** and turn on **In-App Web Browsing**."),
  t("Back in **Location Services**, open **Safari Websites** and choose **While Using the App**."),
  t("Still blocked? Delete this app's icon, open the site in Safari and add it to the Home Screen again."),
];

/** Whether a notice holds the Home Screen app's denied notice (Go's version ends "type a start." instead). */
export function showsIosLocationHelp(notice: string | null | undefined): boolean {
  const lead = DENIED_IN_IOS_APP.slice(0, DENIED_IN_IOS_APP.indexOf(". ") + 1);
  return !!notice && notice.includes(lead);
}

/** The denied notice for where the page runs (isStandalone in installOffer.ts also counts Android's installed app, which has site settings). */
export function deniedNotice(nav: unknown = typeof navigator !== "undefined" ? navigator : undefined): string {
  return iosHomeScreenApp(nav) ? DENIED_IN_IOS_APP : DENIED_IN_BROWSER;
}

export const LOCATE_MESSAGES: Record<LocateFailure, string> = {
  denied: deniedNotice(),
  unavailable: t("Your location could not be found right now. Try again, or search for a place."),
  timeout: t("Finding your location took too long. Try again, or search for a place."),
  unsupported: t("This browser cannot share your location. Search for a place instead."),
  insecure: t("Your location can only be used on a secure (HTTPS) page. Search for a place instead."),
};

/** The notice when the fix is outside the map (the correctness review's N1: said as the rider's location). */
export const LOCATION_OUTSIDE = t("Your location is outside the area this map covers (the DC region to Baltimore).");
/** The notice when the plan has no room for another point (the same words as a map click's). */
export const maxPointsNotice = (): string => t("A route can have at most {max} points.", { max: MAX_POINTS });

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

/** The browser's accuracy as a usable radius: a missing, infinite, NaN or negative one is 0 (no circle, no figure). */
export function cleanAccuracy(accuracy: number): number {
  return Number.isFinite(accuracy) && accuracy >= 0 ? accuracy : 0;
}

/**
 * One call of getCurrentPosition, settled once: by the browser, or by the watchdog if the browser never answers.
 * With `prompt` (the first call only), a permission prompt still open gets `prompt.ms` instead, and when the
 * browser reports it answered the watchdog starts again from then (a browser that keeps saying "prompt" leaves
 * `prompt.ms` from the press). The call itself is never delayed by the permission query.
 */
function attempt(
  api: GeoApi,
  options: typeof LOCATE_OPTIONS | typeof RETRY_OPTIONS,
  watchdogMs: number,
  prompt?: { status: Promise<PermissionLike | undefined>; ms: number },
): Promise<{ result: LocateResult; watchdog: boolean }> {
  return new Promise((resolve) => {
    let settled = false;
    let status: PermissionLike | undefined;
    const fire = () => settle({ ok: false, reason: "timeout" }, true);
    let timer = setTimeout(fire, watchdogMs);
    const restart = (ms: number) => {
      clearTimeout(timer);
      timer = setTimeout(fire, ms);
    };
    const answered = () => {
      if (settled || !status || status.state === "prompt") return;
      status.removeEventListener("change", answered);
      restart(watchdogMs);
    };
    const settle = (result: LocateResult, watchdog = false) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      status?.removeEventListener("change", answered);
      resolve({ result, watchdog });
    };
    prompt?.status.then(
      (found) => {
        if (settled || !found || found.state !== "prompt") return;
        status = found;
        restart(prompt.ms);
        found.addEventListener("change", answered);
      },
      () => undefined,
    );
    try {
      api.getCurrentPosition(
        ({ coords }) => {
          if (!usable(coords.latitude, coords.longitude)) {
            settle({ ok: false, reason: "unavailable" });
            return;
          }
          settle({ ok: true, fix: { point: [coords.longitude, coords.latitude], accuracyM: cleanAccuracy(coords.accuracy) } });
        },
        (error) => settle({ ok: false, reason: failureFor(error.code) }),
        { ...options },
      );
    } catch {
      settle({ ok: false, reason: "unavailable" });
    }
  });
}

/** The permission state, if the browser can say. A query that throws is no answer; one that rejects is
 * handled where it is read (attempt's `then`). */
function permissionOf(env: GeoEnv): Promise<PermissionLike | undefined> | undefined {
  if (!env.permission) return undefined;
  try {
    return env.permission();
  } catch {
    return undefined;
  }
}

/**
 * One look-up. Never rejects: every outcome is a result. A browser timeout is
 * tried once more without high accuracy; a look-up the browser never answers
 * (a dismissed prompt) ends as a timeout when the watchdog fires, with no retry,
 * and any later answer is ignored. While the permission prompt is open the first
 * watchdog allows `promptMs`, then restarts when the prompt is answered.
 */
export async function locate(
  env: GeoEnv,
  watchdog: { first: number; retry: number } = { first: LOCATE_WATCHDOG_MS, retry: RETRY_WATCHDOG_MS },
  promptMs: number = PROMPT_WATCHDOG_MS,
): Promise<LocateResult> {
  if (!env.isSecureContext) return { ok: false, reason: "insecure" };
  const api = env.geolocation;
  if (!api) return { ok: false, reason: "unsupported" };
  const status = permissionOf(env);
  const first = await attempt(api, LOCATE_OPTIONS, watchdog.first, status && { status, ms: promptMs });
  if (first.result.ok || first.result.reason !== "timeout" || first.watchdog) return first.result;
  return (await attempt(api, RETRY_OPTIONS, watchdog.retry)).result;
}

/**
 * "about 50 ft (15 m)", or "" when the browser gave no accuracy: a friendly
 * figure (formatRadius), so 15 m is "about 50 ft", not a falsely precise "49 ft".
 */
export function accuracyText(accuracyM: number): string {
  return accuracyM > 0 ? t("about {radius}", { radius: formatRadius(accuracyM) }) : "";
}

/** Coarser than this (about 330 ft), the announcement warns that the point is rough (a laptop's Wi-Fi fix). */
export const ROUGH_ACCURACY_M = 100;
export const ROUGH_SAID = t("That is rough; search for the exact place if you can.");

/** Whether the search box's text asks for the rider's location: empty, or the start of a phrase for it (two letters or more). */
export function locationMatches(query: string): boolean {
  const plain = (text: string) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "");
  const q = plain(query.trim().toLowerCase());
  if (q === "") return true;
  const own = language() === "es" ? ["su ubicacion", "mi ubicacion", "ubicacion actual"] : language() !== "en" ? [t("your location"), t("my location"), t("current location")] : [];
  const phrases = ["your location", "my location", "current location", ...own.map((phrase) => plain(phrase.toLowerCase()))];
  return q.length >= 2 && phrases.some((phrase) => phrase.startsWith(q));
}

export const FINDING_LOCATION = t("Finding your location…");

/**
 * What is said when the position became point `index` of a plan of `count`:
 * "Start set to your location, accurate to about 50 ft (15 m)." A coarse fix
 * (over about 330 ft (100 m)) adds a warning, since the circle is not heard.
 */
export function locationSaid(index: number, count: number, loop: boolean, accuracyM: number): string {
  const accuracy = accuracyText(accuracyM);
  const rough = accuracyM > ROUGH_ACCURACY_M ? ` ${ROUGH_SAID}` : "";
  const point = pointName(index, count, loop);
  return (accuracy ? t("{point} set to your location, accurate to {accuracy}.", { point, accuracy }) : t("{point} set to your location.", { point })) + rough;
}

/** The note under the search once a point is the rider's location: approximate, and how to adjust it without a pointer too. */
export function approximateHint(accuracyM: number): string {
  const accuracy = accuracyText(accuracyM);
  return accuracy
    ? t("Your location is approximate, to {accuracy}. Drag its marker, or search for the exact place, to adjust it.", { accuracy })
    : t("Your location is approximate. Drag its marker, or search for the exact place, to adjust it.");
}

/** The "Your location" choice's second line: what it will do, by the Start / Destination / Stop choice in force. */
export function hereEffectLine(effect: PlaceEffect, loop = false): string {
  switch (effect) {
    case "start":
      return loop ? t("Sets the start and finish.") : t("Sets the start.");
    case "replace-start":
      return loop ? t("Replaces the start and finish.") : t("Replaces the start.");
    case "end":
      return t("Adds it as the destination.");
    case "replace-end":
      return t("Replaces the destination.");
    case "via":
      return t("Adds it as a stop.");
  }
}

/**
 * The search's spoken result count when the list also holds "Your location",
 * so the count heard matches the options ("3 places found, plus Your location.",
 * then "1 of 4"); the accessibility review's N5.
 */
export function searchStatusWithHere(status: string, here: boolean): string {
  if (!here || status === "") return status;
  if (/(places? found|lugar(es)? encontrados?)\.$/.test(status)) return status.replace(/\.$/, t(", plus Your location."));
  return t("{status} Your location is also listed.", { status });
}

/**
 * One look-up at a time, and which press is the latest: `begin` refuses while
 * one is under way (a second press from the list and the button in the same
 * tick too), and `latest` tells a press's answer or notice whether a newer
 * press has replaced it. Plain state, so it is set before any await.
 */
export function locateGate() {
  let busy = false;
  let presses = 0;
  return {
    /** A new press: its number, or null while a look-up is under way. */
    begin(): number | null {
      if (busy) return null;
      busy = true;
      presses += 1;
      return presses;
    },
    /** The look-up of `press` answered: no longer busy; whether it is still the latest press. */
    finish(press: number): boolean {
      busy = false;
      return press === presses;
    },
    latest(press: number): boolean {
      return press === presses;
    },
    get busy(): boolean {
      return busy;
    },
  };
}

/** What the plan does with a fix: refuse it with a notice, or the new points and what is said. */
export type FixPlacement = { refuse: string } | { next: LonLat[]; point: LonLat; said: string };

/**
 * The decision after a look-up, App's only logic for it: a failure's message;
 * outside the map; no room for another point; or the plan with the fix in it.
 * With no `choice` (the button) the fix goes in like a map click (addPoint,
 * loop-aware); with one (the "Your location" choice in the search list) it goes
 * in like a place picked from search, as Start, Destination or Stop. The point
 * is the fix's own object, so the link note can follow it by identity.
 */
export function placeFix(
  result: LocateResult,
  points: readonly LonLat[],
  options: { loop: boolean; choice?: PlaceChoice },
): FixPlacement {
  if (!result.ok) return { refuse: LOCATE_MESSAGES[result.reason] };
  const { point, accuracyM } = result.fix;
  if (!insideCoverage(point)) return { refuse: LOCATION_OUTSIDE };
  const { loop, choice } = options;
  const adds = choice === undefined || !placeEffect(points.length, choice, loop).startsWith("replace");
  if (adds && points.length >= MAX_POINTS) return { refuse: maxPointsNotice() };
  const next = choice === undefined ? addPoint(points, point, loop) : applyPlace(points, point, choice, loop);
  return { next, point, said: locationSaid(next.indexOf(point), next.length, loop, accuracyM) };
}

/**
 * The location-derived points after a marker drag: a point that came from the
 * location keeps the Copy link note when moved (erring toward telling the
 * rider), so the moved point joins the list. The old one stays, for undo.
 */
export function movedFromHere(fromHere: readonly LonLat[], before: LonLat | undefined, after: LonLat): LonLat[] {
  return before !== undefined && fromHere.includes(before) ? [...fromHere, after] : [...fromHere];
}

/** Copy link's one-line note (OWNER-DECISIONS 395); a location that is not the start is said as a point (a dev extension of 395). */
export const LINK_HAS_LOCATION_START = t("This link includes your location as the start.");
export const LINK_HAS_LOCATION_POINT = t("This link includes your location as a point on the route.");

/** The same note for the rider's Home (review privacy-2): Go's Home chip makes it a plan point, so it is in the link. */
export const LINK_HAS_HOME_END = t("This link includes your Home as the destination.");
export const LINK_HAS_HOME_START = t("This link includes your Home as the start.");
export const LINK_HAS_HOME_POINT = t("This link includes your Home as a point on the route.");

/**
 * The note for a link of `points`, given the position point objects (kept in
 * memory by App; empty if none). Identity, not equality: a moved marker is a new
 * array, and only a drag of a location point adds it to the list (movedFromHere).
 * With the rider's `home`, a point at it is said too. Equality here, not identity:
 * a point at the Home's own coordinates is the Home however it came into the plan
 * (the Home chip, Undo, a reload of the address bar).
 */
export function linkLocationNote(points: readonly LonLat[], from: readonly LonLat[], home: LonLat | null = null): string {
  const location =
    points.length > 0 && from.includes(points[0]) ? LINK_HAS_LOCATION_START : points.some((point) => from.includes(point)) ? LINK_HAS_LOCATION_POINT : "";
  return [location, linkHomeNote(points, home)].filter(Boolean).join(" ");
}

function linkHomeNote(points: readonly LonLat[], home: LonLat | null): string {
  if (!home) return "";
  const isHome = (point: LonLat | undefined) => point !== undefined && point[0] === home[0] && point[1] === home[1];
  if (points.length > 1 && isHome(points[points.length - 1])) return LINK_HAS_HOME_END;
  if (isHome(points[0])) return LINK_HAS_HOME_START;
  return points.some(isHome) ? LINK_HAS_HOME_POINT : "";
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
