/**
 * Joining a broadcast (Stephen 2026-10-28: "For joining a broadcast ride also add the ability to download the gpx, or
 * send to garmin/wahoo if connected. Have this be just a big popup when you join"): once a followed broadcast's link
 * has started the ride on its own (lib/rideGroup.ts opensIntoRide), one big sheet (BroadcastJoinDialog.tsx) offers the
 * broadcast's route as a GPX file, to Garmin and to Wahoo where the rider connected them, and Just ride.
 *
 * Shown once per joined ride: the ride's link and leader are kept on this device when it shows, so a reload or a
 * resumed ride does not show it again. Never to the leader (the page that shared it does not follow it).
 */
import type { KeyValueStore } from "./accessMode.ts";
import { formatDistance, formatDuration } from "./format.ts";
import { t } from "./i18n.ts";

export const JOINED_KEY = "routemaker.broadcast-joined";
/** A joined ride is not shown again within this long; a day's ride, as Resume keeps one (lib/rideResume.ts). */
export const JOINED_KEEP_MS = 24 * 60 * 60_000;
/** The most joined rides kept; the oldest go first. */
export const JOINED_MAX = 20;

export const JOIN_TITLE_NAMED = (name: string) => t("Joined the ride \"{name}\"", { name });
export const JOIN_TITLE = t("You joined a ride");
export const JOIN_JUST_RIDE = t("Just ride");
/** Said with the sheet (its description): what it offers, in full. */
export const JOIN_OFFER = t("Take the leader's route with you: download it as a GPX file, or send it to your bike computer.");

/** The ride a join is for: the broadcast's shared line and its leader. */
export const joinKey = (sharedId: string, lead: string): string => `${sharedId}|${lead}`;

type Joined = [key: string, at: number][];

function readJoined(store: KeyValueStore | null): Joined {
  try {
    const raw = JSON.parse(store?.getItem(JOINED_KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((e): e is [string, number] => Array.isArray(e) && typeof e[0] === "string" && typeof e[1] === "number") : [];
  } catch {
    return [];
  }
}

/** Whether this ride's sheet was shown on this device (within JOINED_KEEP_MS). */
export function joinShown(key: string, store: KeyValueStore | null, now: number): boolean {
  return readJoined(store).some(([k, at]) => k === key && now - at < JOINED_KEEP_MS);
}

/** Keep that this ride's sheet was shown; old and surplus entries go. Storage that refuses keeps nothing. */
export function keepJoinShown(key: string, store: KeyValueStore | null, now: number): void {
  const kept = readJoined(store)
    .filter(([k, at]) => k !== key && now - at < JOINED_KEEP_MS)
    .concat([[key, now]])
    .slice(-JOINED_MAX);
  try {
    store?.setItem(JOINED_KEY, JSON.stringify(kept));
  } catch {
    // Not kept: a reload may show it once more.
  }
}

export type JoinAction = "gpx" | "garmin" | "wahoo";

/**
 * The sheet's buttons, Just ride aside: Download GPX where a file can be saved or handed on here (not in a phone app
 * from before its file plugin), Send to Garmin and Send to Wahoo only where the rider has connected that account
 * (lib/garminLink.ts readGarmin, lib/wahooLink.ts readWahoo: nothing read, signed out included, is not connected).
 */
export function joinActions(at: { canHandFile: boolean; garmin: Connection | undefined; wahoo: Connection | undefined }): JoinAction[] {
  const actions: JoinAction[] = [];
  if (at.canHandFile) actions.push("gpx");
  if (connected(at.garmin)) actions.push("garmin");
  if (connected(at.wahoo)) actions.push("wahoo");
  return actions;
}

type Connection = { available: boolean; connected: boolean };
const connected = (state: Connection | undefined): boolean => state?.available === true && state.connected === true;

/**
 * Whether to show the sheet: a ride a followed broadcast started on its own (never the leader's, never one already
 * going or resumed), not shown for this ride before, with at least one thing to offer besides Just ride.
 */
export function showJoin(at: { following: boolean; started: boolean; shownBefore: boolean; actions: number }): boolean {
  return at.following && at.started && !at.shownBefore && at.actions > 0;
}

/** The sheet's title: the shared route's name where it has one. */
export function joinTitle(name: string | null | undefined): string {
  const named = name?.trim();
  return named ? JOIN_TITLE_NAMED(named) : JOIN_TITLE;
}

/** Its one line: "12.4 mi (20.0 km) · 1 h 05 min". */
export function joinLine(route: { distance_m: number; duration_s: number }): string {
  return `${formatDistance(route.distance_m)} · ${formatDuration(route.duration_s)}`;
}
