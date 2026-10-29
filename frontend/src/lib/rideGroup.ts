/**
 * Mass Ride and Group Ride links (v0.7.0 plan): see the others on the route as anonymous dots, and tap to send
 * an issue to everyone on the link. The server side is core.ride_presence (in memory only, 2 minutes).
 *
 * - A ride is the digest of the link's plan (ride type and points), so everyone who opened the same link is on
 *   the same ride and the server never holds the route. A rider is a random token made for that ride on this
 *   device; it changes each ride (a new one after 12 hours).
 * - Showing your own dot is asked once, when the link opens ("Show me as a dot to others on this ride?"), and
 *   the answer kept for that ride on this device. Seeing the others needs no answer.
 * - The same question asks the rider's role (Stephen 2026-10-16): Participant (chosen already, so one tap
 *   answers), Lead line, Sweep or Corker, kept with the answer and changeable beside "Show me as a dot". The
 *   role goes with each position and comes back on each dot; still no name. It is self-declared: a ride link
 *   has no sign-in, so a role says what the rider chose, nothing more.
 * - Your dot is sent about every 15 s while the app is open and in front (never in the background), and only
 *   while you are within a quarter mile (400 m) of the route line. Sharing ends when you turn it off, close
 *   the app, are off the route for 10 minutes, or 12 hours after the ride's start (your answer).
 * - Dots show their age: under 30 s solid (with a brief pulse ring when a new reading lands), 30-90 s faded,
 *   90 s to 2 min a hollow ring, then gone. Only dots within a quarter mile of the route are drawn.
 * - Alerts: the plan's lists, one tap to send (Medical emergency or crash, and Crash, ask first), the sender's
 *   spot sent once with it, at most 1 a minute and 10 a ride per device. Each carries its age in words.
 */
import { QUARTER_MILE, formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import type { PresetId } from "./presets.ts";
import { mergeAlerts, newRideSecret, openValue, rideSeal, sealValue, sendable, sendableLine, type OpenedAlert, type RideSeal } from "./rideSeal.ts";

export const RIDE_LINK_TYPES: readonly PresetId[] = ["mass-ride", "group-ride"];
export type RideLinkType = "mass-ride" | "group-ride";

/** A plan link that is a ride: a Mass Ride or Group Ride with a route. */
export function isRideLinkType(preset: PresetId): preset is RideLinkType {
  return preset === "mass-ride" || preset === "group-ride";
}

/**
 * The plan's ride secret after its ride type changes from `was` to `now` (Stephen 2026-10-29: Group and Mass Ride both
 * sealed). Kept: on a plan that is not a ride; a link's own (opened here); or the page's own moving into a ride type
 * from one that is not. Made new, the page's own: none yet, or the page's own moving between the two ride types, which
 * are different rides. `own`: the page made the secret, not a link opened here.
 */
export function presetSecret(
  was: PresetId,
  now: PresetId,
  secret: string | null,
  own: boolean,
  make: () => string = newRideSecret,
): { secret: string | null; own: boolean } {
  if (!isRideLinkType(now) || was === now) return { secret, own };
  if (secret !== null && (!isRideLinkType(was) || !own)) return { secret, own };
  return { secret: make(), own: true };
}

export function isRideLink(preset: PresetId, points: readonly LonLat[]): preset is RideLinkType {
  return isRideLinkType(preset) && points.length >= 2;
}

/** What the ride's digest is made from: the ride type and the points as the link writes them. */
export function rideKey(preset: PresetId, points: readonly LonLat[]): string {
  return `${preset}|${points.map(([lon, lat]) => `${lon.toFixed(5)},${lat.toFixed(5)}`).join(";")}`;
}

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The ride's id: the SHA-256 of its key, 64 hex digits. */
export async function rideId(preset: PresetId, points: readonly LonLat[]): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(rideKey(preset, points)));
  return hex(digest);
}

/**
 * A broadcast ride (Share ride or Broadcast, Stephen 2026-10-22): the ride is the shared line's id, which the sharer
 * and everyone who opens the link both hold whatever each of them rides, so the leader is always on the same ride.
 */
export async function broadcastRideId(sharedId: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`broadcast|${sharedId}`));
  return hex(digest);
}

/**
 * A broadcast from Roam (Stephen 2026-10-22: Broadcast "as a tap within roam"): a ride with no route, named by a random
 * id its link carries, and kept apart from a shared line's broadcast by its prefix.
 */
export async function roamRideId(roamId: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`roam|${roamId}`));
  return hex(digest);
}

/**
 * The ride a page is on, and its seal: a link carrying a secret (lib/rideSeal.ts) is sealed end to end and named by
 * the secret; else a broadcast by its shared line or Roam id, or a Mass Ride or Group Ride by its points, in plain
 * numbers as before. App.tsx keeps the leader's answer under the same id.
 */
export async function rideOf(at: {
  type?: PresetId;
  points?: readonly LonLat[];
  broadcast?: { id: string; roam?: boolean } | null;
  secret?: string | null;
}): Promise<{ id: string; seal: RideSeal | null }> {
  const sealed = at.secret ? await rideSeal(at.secret) : null;
  if (sealed) return { id: sealed.ride, seal: sealed };
  if (at.broadcast) return { id: await (at.broadcast.roam ? roamRideId(at.broadcast.id) : broadcastRideId(at.broadcast.id)), seal: null };
  return { id: await rideId(at.type ?? "group-ride", at.points ?? []), seal: null };
}

/**
 * The leader key a broadcast link carries (core.ride_presence.leader_key): the first 32 hex digits of the SHA-256 of
 * the sharer's token. It names the sharer's dot to the server; only the sharer, who holds the token, posts as it.
 */
export async function leaderKey(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return hex(digest).slice(0, 32);
}

/** A rider's random token for one ride: 32 hex digits. */
export function newToken(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return hex(bytes);
}

// ---- the answer, kept for the ride on this device ---------------------------------------------------

export const CONSENT_KEY = "routemaker.ride-share";
/** Sharing ends 12 hours after the ride's start; the next opening is a new ride, asked again with a new token. */
export const RIDE_LIFE_MS = 12 * 3600_000;

// ---- the rider's role -------------------------------------------------------------------------------

/** The server's core.ride_presence.ROLES, the same ids. */
export type RideRole = "participant" | "lead" | "sweep" | "corker";
export const DEFAULT_ROLE: RideRole = "participant";

/** In the order the question and the key list them. */
export const RIDE_ROLES: readonly { id: RideRole; label: string }[] = [
  { id: "participant", label: t("Participant") },
  { id: "lead", label: t("Lead line") },
  { id: "sweep", label: t("Sweep") },
  { id: "corker", label: t("Corker") },
];

export const ROLE_QUESTION = t("Riding as");

export function isRole(value: unknown): value is RideRole {
  return RIDE_ROLES.some((r) => r.id === value);
}

/** A dot's role as the server sent it; anything else (an older server) is a participant. */
export function roleOf(value: unknown): RideRole {
  return isRole(value) ? value : DEFAULT_ROLE;
}

export function roleLabel(role: RideRole): string {
  return RIDE_ROLES.find((r) => r.id === role)?.label ?? "Participant";
}

export interface RideConsent {
  answer: "yes" | "no";
  token: string;
  /** When the rider answered: the ride's start, for this device. */
  since: number;
  /** The rider's role on this ride (Participant unless they chose another). */
  role: RideRole;
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function readAll(store: Store | null): Record<string, RideConsent> {
  try {
    const raw = JSON.parse(store?.getItem(CONSENT_KEY) ?? "{}") as Record<string, RideConsent>;
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

/** This ride's answer, or null: never asked, or asked more than 12 hours ago (a new ride). */
export function consentFor(ride: string, now = Date.now(), store: Store | null = local()): RideConsent | null {
  const found = readAll(store)[ride];
  if (!found || (found.answer !== "yes" && found.answer !== "no") || typeof found.token !== "string" || typeof found.since !== "number") return null;
  return now - found.since < RIDE_LIFE_MS ? { ...found, role: roleOf(found.role) } : null;
}

/**
 * Keep the rider's answer (and role, when given) for this ride; older rides' answers are dropped. Without a
 * role the one kept stays (Participant at first). Answers the record kept.
 */
export function keepConsent(
  ride: string,
  answer: "yes" | "no",
  now = Date.now(),
  store: Store | null = local(),
  token = newToken(),
  role?: RideRole,
): RideConsent {
  const all = readAll(store);
  const kept: Record<string, RideConsent> = {};
  for (const [id, c] of Object.entries(all)) if (c && typeof c.since === "number" && now - c.since < RIDE_LIFE_MS) kept[id] = c;
  const previous = kept[ride];
  const record: RideConsent = { answer, token: previous?.token ?? token, since: previous?.since ?? now, role: role ?? roleOf(previous?.role) };
  kept[ride] = record;
  try {
    store?.setItem(CONSENT_KEY, JSON.stringify(kept));
  } catch {
    // Not kept: asked again next time.
  }
  return record;
}

/**
 * The sharer's answer for the ride they broadcast: shown, as Lead line, under the token whose leader key the link
 * carries (a token kept from an earlier share of the same line is replaced, so the link's key names this dot).
 */
export function leadConsent(ride: string, token: string, now = Date.now(), store: Store | null = local()): RideConsent {
  const all = readAll(store);
  const kept: Record<string, RideConsent> = {};
  for (const [id, c] of Object.entries(all)) if (c && typeof c.since === "number" && now - c.since < RIDE_LIFE_MS) kept[id] = c;
  const record: RideConsent = { answer: "yes", token, since: kept[ride]?.since ?? now, role: "lead" };
  kept[ride] = record;
  try {
    store?.setItem(CONSENT_KEY, JSON.stringify(kept));
  } catch {
    // Not kept: the ride's page asks again.
  }
  return record;
}

export const CONSENT_QUESTION = "Show me as a dot to others on this ride?";
export const CONSENT_NOTE = `Only while the app is open and you are within ${QUARTER_MILE} of the route. No name; positions are rounded and gone after 2 minutes.`;
/**
 * Whether a broadcast link one follows, once ready (its route shown, or a Roam broadcast's leader named), goes straight
 * into Ride mode (Stephen 2026-10-26: "Opening the broadcast mode should enter ride mode with the leader's dot shown"):
 * on a phone only (a computer opening it watches the leader, as before), and not over a ride already going or a left
 * ride's Resume question. Judged once per page (App.tsx).
 */
export function opensIntoRide(at: { phone: boolean; onBike: boolean; resumeAsked: boolean }): boolean {
  return at.phone && !at.onBike && !at.resumeAsked;
}

/** Said once a followed broadcast has started the ride or Roam on its own (opensIntoRide): no press started it, so a
 * phone may keep the voice quiet until the first tap. */
export const BROADCAST_FOLLOWING = t("Following the leader live. If you hear no directions, tap the screen once.");

/** On a broadcast: shown on or off the route, so the leader and the riders can find each other. */
export const BROADCAST_CONSENT_NOTE = "Only while the app is open, on or off the route, so the leader and riders can find each other. No name; positions are rounded and gone after 2 minutes.";
/**
 * What the question shows, short (the 2026-10-28 audit, P6: asked as Start ride or Broadcast is pressed, over the
 * ride's first screen); a screen reader is given the full note (CONSENT_NOTE, BROADCAST_CONSENT_NOTE).
 */
export const CONSENT_SHORT = "Only while the app is open. No name; gone in 2 min.";
export const CONSENT_YES = "Yes";
export const CONSENT_NO = "No";

// ---- where the dots are along the route ------------------------------------------------------------

export const NEAR_ROUTE_M = 400;
export const OFF_ROUTE_STOP_MS = 10 * 60_000;
export const POST_EVERY_MS = 15_000;
export const POLL_EVERY_MS = 15_000;
/** The soonest the server takes another position from the same rider (core.ride_presence.MIN_POST_INTERVAL_S). */
export const MIN_POST_GAP_MS = 10_000;

/** After a role change: the last post moved back so the next goes as soon as the server will take it. */
export function postSoonAfter(lastPost: number): number {
  return lastPost - (POST_EVERY_MS - MIN_POST_GAP_MS);
}

const M_PER_DEG = 111_195;

/** Stretches of the line this much further off than the nearest still count as where `p` is (a 20 m grid, GPS). */
export const SAME_SPOT_M = 30;

/**
 * Where `p` is against the line: metres along it to the nearest point, metres off it, and the way the route
 * goes there (degrees clockwise from north, for the lead line's chevron). Where the line passes the spot more
 * than once (an out-and-back, a loop's overlap), `hintAlongM` picks the pass: of the stretches within
 * SAME_SPOT_M of the nearest, the one whose distance along is closest to the hint (the rider's last reading).
 */
export function project(line: readonly LonLat[], p: LonLat, hintAlongM: number | null = null): { alongM: number; offM: number; bearingDeg: number } {
  if (line.length === 0) return { alongM: 0, offM: Infinity, bearingDeg: 0 };
  const kx = M_PER_DEG * Math.cos((p[1] * Math.PI) / 180);
  const x = (q: LonLat) => q[0] * kx;
  const y = (q: LonLat) => q[1] * M_PER_DEG;
  if (line.length === 1) return { alongM: 0, offM: Math.hypot(x(line[0]) - x(p), y(line[0]) - y(p)), bearingDeg: 0 };
  const passes: { d: number; along: number; bearing: number | null }[] = [];
  let walked = 0;
  for (let i = 0; i < line.length - 1; i += 1) {
    const ax = x(line[i]);
    const ay = y(line[i]);
    const bx = x(line[i + 1]);
    const by = y(line[i + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.max(0, Math.min(1, ((x(p) - ax) * dx + (y(p) - ay) * dy) / len2)) : 0;
    const d = Math.hypot(ax + t * dx - x(p), ay + t * dy - y(p));
    const seg = Math.sqrt(len2);
    passes.push({ d, along: walked + t * seg, bearing: len2 > 0 ? ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360 : null });
    walked += seg;
  }
  const best = Math.min(...passes.map((q) => q.d));
  let chosen = passes.find((q) => q.d === best)!;
  if (hintAlongM !== null) {
    for (const q of passes) if (q.d <= best + SAME_SPOT_M && Math.abs(q.along - hintAlongM) < Math.abs(chosen.along - hintAlongM)) chosen = q;
  }
  const bearing = chosen.bearing ?? passes.find((q) => q.bearing !== null)?.bearing ?? 0;
  return { alongM: chosen.along, offM: chosen.d, bearingDeg: bearing };
}

/** Within a quarter mile of the route: where a dot is sent from, and which dots are drawn. */
export function nearRoute(line: readonly LonLat[], p: LonLat): boolean {
  return project(line, p).offM <= NEAR_ROUTE_M;
}

/**
 * A broadcast from Roam (no route to be along): how far a spot is from you in a straight line, "0.3 mi (0.5 km) away",
 * "beside you"; null without your position.
 */
export function awayWords(here: LonLat | null, p: LonLat): string | null {
  if (!here) return null;
  const m = haversineM(here, p);
  return m < 30 ? "beside you" : `${formatDistance(m)} away`;
}

/** "0.3 mi (0.5 km) behind you", "ahead of you", "beside you"; without your position, "4.2 mi (6.8 km) along the route". */
export function relativeWords(otherAlongM: number, myAlongM: number | null): string {
  if (myAlongM === null) return `${formatDistance(otherAlongM)} along the route`;
  const diff = otherAlongM - myAlongM;
  if (Math.abs(diff) < 30) return "beside you";
  return `${formatDistance(Math.abs(diff))} ${diff > 0 ? "ahead of you" : "behind you"}`;
}

// ---- freshness -------------------------------------------------------------------------------------

export type Freshness = "fresh" | "faded" | "ring" | "gone";

/** Under 30 s solid, 30-90 s faded, 90 s to 2 min a hollow ring, then gone. */
export function freshness(ageS: number): Freshness {
  if (ageS < 30) return "fresh";
  if (ageS < 90) return "faded";
  if (ageS <= 120) return "ring";
  return "gone";
}

/** An age in words: "just now", "40 s ago", "1 min ago". */
export function ageWords(ageS: number): string {
  if (ageS < 10) return "just now";
  if (ageS < 60) return `${Math.floor(ageS / 10) * 10} s ago`;
  return `${Math.floor(ageS / 60)} min ago`;
}

/**
 * A dot's name for a screen reader: its role and where it is along the route from you, "Sweep, 0.5 mi
 * (0.8 km) behind", "Lead line, 1.2 mi (1.9 km) ahead", "Corker, beside you"; without your position,
 * "Participant, 4.2 mi (6.8 km) along the route".
 */
export function dotName(role: RideRole, alongM: number, myAlongM: number | null, leader = false, away: string | null | undefined = undefined): string {
  // A broadcast from Roam has no route: where the dot is from you in a straight line, or nothing without your position.
  if (away !== undefined) return away ? `${leader ? LEADER_LABEL : roleLabel(role)}, ${away}` : leader ? LEADER_LABEL : roleLabel(role);
  const diff = myAlongM === null ? null : alongM - myAlongM;
  const where = diff === null || Math.abs(diff) < 30 ? relativeWords(alongM, myAlongM) : `${formatDistance(Math.abs(diff))} ${diff > 0 ? "ahead" : "behind"}`;
  return `${leader ? LEADER_LABEL : roleLabel(role)}, ${where}`;
}

/** The sharer of a broadcast ride, as the key and the dots name them. */
export const LEADER_LABEL = "Ride leader";

/** What tapping a dot says: "Sweep, 0.5 mi (0.8 km) behind. Seen 40 s ago." */
export function dotSaid(ageS: number, name: string | null = null): string {
  const seen = ageS < 10 ? "Seen just now" : `Seen ${ageWords(ageS)}`;
  return name ? `${name}. ${seen}.` : `${seen}.`;
}

// ---- the dots --------------------------------------------------------------------------------------

export interface Dot {
  lon: number;
  lat: number;
  age_s: number;
  /** Absent from an older server: a participant. */
  role?: RideRole;
  /** The broadcast's sharer (core.ride_presence.read with the link's leader key). */
  leader?: boolean;
}

export interface ShownDot extends Dot {
  role: RideRole;
  freshness: Exclude<Freshness, "gone">;
  alongM: number;
  /** The way the route goes at the dot, degrees clockwise from north: the lead line's chevron points so. */
  bearing: number;
  /** A new reading since the last poll: drawn with the brief pulse ring. */
  pulse: boolean;
}

/** How long the pulse ring shows after a poll brings a new reading. */
export const PULSE_S = 2;

/** What says which pass of the route a dot is on: the dots drawn last time, and the rider's own place along it. */
export interface DotHints {
  previous?: readonly ShownDot[];
  myAlongM?: number | null;
  /** A broadcast: every dot is drawn, on or off the route, so riders who get separated can find each other. */
  anywhere?: boolean;
}

/** A dot's last reading is not named (dots are anonymous): the nearest one drawn last time of the same role, within 200 m. */
const HINT_WITHIN_M = 200;

function hintFor(d: Dot, hints: DotHints): number | null {
  const role = roleOf(d.role);
  const kx = M_PER_DEG * Math.cos((d.lat * Math.PI) / 180);
  let nearest: ShownDot | null = null;
  let nearestM = HINT_WITHIN_M;
  for (const p of hints.previous ?? []) {
    if (p.role !== role) continue;
    const m = Math.hypot((p.lon - d.lon) * kx, (p.lat - d.lat) * M_PER_DEG);
    if (m <= nearestM) {
      nearest = p;
      nearestM = m;
    }
  }
  return nearest ? nearest.alongM : (hints.myAlongM ?? null);
}

/**
 * The dots to draw: within a quarter mile of the route and under 2 minutes old, aged by the seconds since the
 * poll; a reading newer than the last poll pulses for the first PULSE_S seconds. The ride leader is drawn off the
 * route too: the sharer may re-route, and those following go where the leader goes. On a broadcast every dot is
 * (`anywhere`; Stephen 2026-10-22: "Both the leader dot and any followers show up on the map, so if they get
 * separated they can find each other").
 */
export function shownDots(line: readonly LonLat[], dots: readonly Dot[], sinceS = 0, hints: DotHints = {}): ShownDot[] {
  const out: ShownDot[] = [];
  for (const d of dots) {
    const age = d.age_s + sinceS;
    const f = freshness(age);
    if (f === "gone") continue;
    const at = project(line, [d.lon, d.lat], hintFor(d, hints));
    if (at.offM > NEAR_ROUTE_M && !d.leader && !hints.anywhere) continue;
    out.push({
      ...d,
      leader: d.leader === true,
      role: roleOf(d.role),
      age_s: age,
      freshness: f,
      alongM: at.alongM,
      bearing: Math.round(at.bearingDeg),
      pulse: d.age_s < POLL_EVERY_MS / 1000 && sinceS < PULSE_S,
    });
  }
  return out;
}

/**
 * The map's key: the roles on this ride now, in RIDE_ROLES order, each with how many. None shown, none listed.
 * The ride leader is counted under "Ride leader" only (its own row in RideGroup), never under its role too.
 */
export function roleKey(dots: readonly ShownDot[]): { role: RideRole; label: string; count: number }[] {
  const others = dots.filter((d) => !d.leader);
  return RIDE_ROLES.map((r) => ({ role: r.id, label: r.label, count: others.filter((d) => d.role === r.id).length })).filter((r) => r.count > 0);
}

/**
 * "23 riders on the route", "1 rider on the route", "No riders on the route yet": everyone on the ride, the leader
 * and this rider included where shown (Stephen 2026-10-27: "the number of riders ... include the leader").
 */
export function countText(n: number, onRoute = true): string {
  // A broadcast from Roam has no route: "No riders yet", "2 riders".
  if (n === 0) return onRoute ? t("No riders on the route yet") : t("No riders yet");
  if (onRoute) return n === 1 ? t("{n} rider on the route", { n }) : t("{n} riders on the route", { n });
  return n === 1 ? t("{n} rider", { n }) : t("{n} riders", { n });
}

/** Everyone on the ride: the dots shown, and this rider where the others see them too (the leader always). */
export function riderTotal(dots: readonly ShownDot[], meShown: boolean): number {
  return dots.length + (meShown ? 1 : 0);
}

/**
 * Said on request: the count, the nearest rider ahead (else behind) with its age, then the nearest of each
 * other role on the ride by name: "Lead line, 1.2 mi (1.9 km) ahead. Sweep, 0.5 mi (0.8 km) behind."
 * The ride leader is said once, first, and left out of the nearest rider and the roles (review S4: a screen reader
 * said the one leader dot three times).
 */
export function ridersSaid(dots: readonly ShownDot[], myAlongM: number | null, around: { here: LonLat | null } | null = null, meShown = false): string {
  const count = `${countText(riderTotal(dots, meShown), around === null)}.`;
  if (!dots.length) return count;
  // No route (a broadcast from Roam): the leader and the nearest rider, each from you in a straight line.
  if (around) {
    const from = (d: ShownDot) => awayWords(around.here, [d.lon, d.lat]);
    const leader = dots.find((d) => d.leader);
    const lead = leader ? ` ${dotName(leader.role, 0, null, true, from(leader))}, seen ${ageWords(leader.age_s)}.` : "";
    const here = around.here;
    const others = dots.filter((d) => !d.leader);
    const nearest = here ? others.sort((a, b) => haversineM(here, [a.lon, a.lat]) - haversineM(here, [b.lon, b.lat]))[0] : undefined;
    const near = nearest ? ` Nearest rider ${from(nearest)}, seen ${ageWords(nearest.age_s)}.` : "";
    return `${count}${lead}${near}`;
  }
  if (myAlongM === null) {
    const leader = dots.find((d) => d.leader);
    return leader ? `${count} ${dotName(leader.role, leader.alongM, null, true)}, seen ${ageWords(leader.age_s)}.` : count;
  }
  const leader = dots.find((d) => d.leader);
  const lead = leader ? ` ${dotName(leader.role, leader.alongM, myAlongM, true)}, seen ${ageWords(leader.age_s)}.` : "";
  const others = dots.filter((d) => !d.leader);
  const ahead = others.filter((d) => d.alongM >= myAlongM).sort((a, b) => a.alongM - b.alongM)[0];
  const behind = others.filter((d) => d.alongM < myAlongM).sort((a, b) => b.alongM - a.alongM)[0];
  const nearest = ahead ?? behind;
  const which = ahead ? "ahead" : "behind";
  const near = nearest ? ` Nearest rider ${which}, ${formatDistance(Math.abs(nearest.alongM - myAlongM))}, seen ${ageWords(nearest.age_s)}.` : "";
  const roles = RIDE_ROLES.filter((r) => r.id !== DEFAULT_ROLE)
    .map((r) => others.filter((d) => d.role === r.id).sort((a, b) => Math.abs(a.alongM - myAlongM) - Math.abs(b.alongM - myAlongM))[0])
    .filter((d): d is ShownDot => d !== undefined)
    .map((d) => ` ${dotName(d.role, d.alongM, myAlongM)}.`)
    .join("");
  return `${count}${lead}${near}${roles}`;
}

// ---- following the leader -------------------------------------------------------------------------

/** The leader's path as this page saw it: kept in memory on this device only, never sent or stored. */
export const TRAIL_MAX_POINTS = 2000;
/** A reading within this of the last one adds nothing (the server's grid is 20 m). */
export const TRAIL_STEP_M = 15;

/** The trail with the leader's new reading added, or the same trail where it has not moved. */
export function extendTrail(trail: readonly LonLat[], p: LonLat): readonly LonLat[] {
  const last = trail[trail.length - 1];
  if (last) {
    const kx = M_PER_DEG * Math.cos((p[1] * Math.PI) / 180);
    if (Math.hypot((p[0] - last[0]) * kx, (p[1] - last[1]) * M_PER_DEG) < TRAIL_STEP_M) return trail;
  }
  const next = [...trail, p];
  return next.length > TRAIL_MAX_POINTS ? next.slice(next.length - TRAIL_MAX_POINTS) : next;
}

export const FOLLOW_LEADER = t("Follow the leader");
export const FOLLOWING_SAID = t("Following the ride leader on the map.");
export const NOT_FOLLOWING_SAID = t("Stopped following the ride leader. Turn on Follow the leader to follow again.");
export const LEADING_SAID = t("You lead this ride: those who open your link follow your dot while the app is open.");

// ---- sharing your own dot --------------------------------------------------------------------------

export interface ShareState {
  /** The rider's answer is yes and they have not turned it off. */
  on: boolean;
  since: number;
  /** When the rider was last within a quarter mile of the route (null: not yet). */
  lastNearAt: number | null;
  /** When sharing started this visit, for the 10-minute off-route stop before a first near fix. */
  startedAt: number;
}

export type ShareStop = "off" | "left-route" | "ride-over" | null;

/** Why sharing has stopped, or null while it goes on (the app being closed or hidden stops it outright). */
export function shareStop(state: ShareState, now: number): ShareStop {
  if (!state.on) return "off";
  if (now - state.since >= RIDE_LIFE_MS) return "ride-over";
  if (now - (state.lastNearAt ?? state.startedAt) >= OFF_ROUTE_STOP_MS) return "left-route";
  return null;
}

/**
 * A dot stays shown at a meetup and through regroup stops (Stephen 2026-10-29: groups meet at shared spots such as
 * Dupont Circle, "you'd want to see all the dots to make sure sharing is working", and "an hour of dwell time is
 * fine"), so nothing is held back at a ride's start or end. It is held back only once it has stayed within DWELL_M of
 * one spot for over DWELL_PAUSE_MS, or while it is within HOME_PAUSE_M of the rider's saved Home; it is sent again as
 * soon as it moves on.
 */
export const DWELL_PAUSE_MS = 3600_000;
export const DWELL_M = 100;
export const HOME_PAUSE_M = 150;

/** Where a rider has stayed, and since when. */
export interface Dwell {
  at: LonLat;
  since: number;
}

function metresApart(a: LonLat, b: LonLat): number {
  const kx = M_PER_DEG * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  return Math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * M_PER_DEG);
}

/** The stay after this fix: the same one while within DWELL_M of where it began, else a new one from here. */
export function nextDwell(before: Dwell | null, fix: LonLat, now: number): Dwell {
  return before && metresApart(before.at, fix) <= DWELL_M ? before : { at: fix, since: now };
}

/** Whether the dot is held back: stayed in one spot for over an hour, or at the saved Home. */
export function dotHeldBack(dwell: Dwell | null, fix: LonLat, now: number, home: LonLat | null): boolean {
  if (home && metresApart(home, fix) <= HOME_PAUSE_M) return true;
  return dwell !== null && now - dwell.since > DWELL_PAUSE_MS;
}

// ---- answers given in this tab ------------------------------------------------------------------------

/**
 * The rides answered Yes in this tab (sessionStorage). A Yes kept from another tab, or from before the browser was
 * closed, is only a starting point for the question: opening the link again asks again before any dot is sent, so a
 * link opened later never turns sharing back on by itself.
 */
export const ANSWERED_HERE_KEY = "routemaker.ride-share-here";

function session(): Store | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function answeredList(store: Store | null): string[] {
  try {
    const raw = JSON.parse(store?.getItem(ANSWERED_HERE_KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((r): r is string => typeof r === "string") : [];
  } catch {
    return [];
  }
}

export function answeredHere(ride: string, store: Store | null = session()): boolean {
  return answeredList(store).includes(ride);
}

/** Forget every ride answered in this tab: a ride ended, so the next one asks again. */
export function forgetAnsweredHere(store: Store | null = session()): void {
  try {
    store?.setItem(ANSWERED_HERE_KEY, "[]");
  } catch {
    // Nothing kept to forget.
  }
}

/** Mark (or, with false, unmark) a ride as answered Yes in this tab. */
export function markAnsweredHere(ride: string, yes: boolean, store: Store | null = session()): void {
  const list = answeredList(store).filter((r) => r !== ride);
  if (yes) list.push(ride);
  try {
    store?.setItem(ANSWERED_HERE_KEY, JSON.stringify(list.slice(-20)));
  } catch {
    // Not kept: asked again on the next opening.
  }
}

export const SHARE_STOPPED_SAID: Record<Exclude<ShareStop, null>, string> = {
  off: t("You are no longer shown as a dot."),
  "left-route": t("You have been off the route for 10 minutes, so you are no longer shown as a dot."),
  "ride-over": t("This ride started 12 hours ago, so you are no longer shown as a dot."),
};

// ---- alerts ----------------------------------------------------------------------------------------

export interface AlertKind {
  id: string;
  label: string;
  confirm?: boolean;
  call911?: boolean;
}

/** The plan's lists (the server's core.ride_presence.ALERT_KINDS, the same ids). */
export const ALERT_KINDS: Record<RideLinkType, readonly AlertKind[]> = {
  "mass-ride": [
    { id: "spread", label: t("Extensive rider spread") },
    { id: "emergency_vehicle", label: t("Emergency vehicle coming through") },
    { id: "aggressive", label: t("Aggressive person") },
    { id: "medical", label: t("Medical emergency or crash"), confirm: true, call911: true },
    { id: "reroute", label: t("Rerouting, road closed") },
    // Stephen 2026-10-22: "Followers and leaders can text between each other as well with common issues, lost, mechanical, etc".
    { id: "lost", label: t("Lost, separated from the ride") },
    { id: "other", label: t("Other") },
  ],
  "group-ride": [
    { id: "off_back", label: t("Rider off the back") },
    { id: "crash", label: t("Crash"), confirm: true, call911: true },
    { id: "mechanical", label: t("Mechanical or flat, stopping") },
    { id: "wrong_turn", label: t("Wrong turn") },
    { id: "lost", label: t("Lost, separated from the group") },
    { id: "wait", label: t("Wait up, regroup") },
    { id: "other", label: t("Other") },
  ],
};

/**
 * Roam's broadcast (a Group Ride on the server, review N3): no route, so no Wrong turn or Rider off the back; the
 * Group Ride's own ids, so the server takes them.
 */
export const ROAM_ALERT_KINDS: readonly AlertKind[] = ["lost", "wait", "mechanical", "crash", "other"].map(
  (id) => ALERT_KINDS["group-ride"].find((k) => k.id === id) as AlertKind,
);

/** Stephen 2026-10-27: "make the alert (call it send alert) a larger button". */
export const ALERT_LABEL = t("Send alert");
export const ALERT_NOTE = t("Sends your location with the alert");
/**
 * An alert needs its spot, so it always carries it, even from a rider not shown as a dot; on a ride with no key in its
 * link (an older Group or Mass Ride link, or a ride post's) the spot is in plain numbers, which anyone who has the
 * route can read. So the rider is told before sending (2026-10-29).
 */
export const ALERT_SPOT_NOTE = t("Sends your spot to everyone on this ride.");

/**
 * The alert panel's line. Seen: ALERT_SPOT_NOTE where it adds something (no key, and the rider not shown as a dot, so
 * the alert is the first time their spot goes out), else the usual short ALERT_NOTE. Heard (a screen reader, and the
 * Alert button's description): ALERT_SPOT_NOTE always, true on every ride.
 */
export function alertNote(sealed: boolean, shownAsDot: boolean): { seen: string; heard: string } {
  return { seen: !sealed && !shownAsDot ? ALERT_SPOT_NOTE : `${ALERT_NOTE}.`, heard: ALERT_SPOT_NOTE };
}
export const CONFIRM_QUESTION = t("Send to everyone on this ride?");
export const OTHER_MAX = 80;
export const ALERT_EVERY_MS = 60_000;
export const ALERTS_PER_RIDE = 10;
export const CALL_911 = t("Call 911");
export const CALL_911_HREF = "tel:911";

/** Whether this device may send another alert now; else the sentence why not. */
export function alertRefusal(sentAt: readonly number[], now: number): string | null {
  if (sentAt.length >= ALERTS_PER_RIDE) return t("You have sent {count} alerts on this ride, the most one phone sends.", { count: ALERTS_PER_RIDE });
  const last = sentAt[sentAt.length - 1];
  if (last !== undefined && now - last < ALERT_EVERY_MS) {
    const wait = Math.ceil((ALERT_EVERY_MS - (now - last)) / 1000);
    return t("One alert a minute: you can send another in {wait} s.", { wait });
  }
  return null;
}

export interface RideAlert {
  id: string;
  kind: string;
  label: string;
  text: string;
  lon: number;
  lat: number;
  age_s: number;
  count: number;
  mine: boolean;
  call_911: boolean;
}

/** The banner's words: "Rider off the back, 0.3 mi (0.5 km) behind you, just now. 2 riders reported." */
export function alertText(alert: RideAlert, line: readonly LonLat[], myAlongM: number | null, sinceS = 0, here: LonLat | null = null): string {
  const what = alert.kind === "other" && alert.text ? `${alert.label}: ${alert.text}` : alert.label;
  // No route (a broadcast from Roam): from you in a straight line, or no place words without your position.
  const where = line.length === 0 ? awayWords(here, [alert.lon, alert.lat]) : relativeWords(project(line, [alert.lon, alert.lat]).alongM, myAlongM);
  const reported = alert.count > 1 ? ` ${alert.count} riders reported.` : "";
  return `${what}${where ? `, ${where}` : ""}, ${ageWords(alert.age_s + sinceS)}.${reported}`;
}

/** Alerts not seen before: announced at once (assertive; they are essentials, said even at Brief) and vibrated. */
export function newAlerts(previous: readonly RideAlert[], next: readonly RideAlert[]): RideAlert[] {
  return next.filter((a) => !a.mine && !previous.some((p) => p.id === a.id && p.count === a.count));
}

// ---- the API ---------------------------------------------------------------------------------------

type Fetch = typeof fetch;

/** A broadcast leader's route and ridden path, as its phone last sent them (core.ride_presence.post_path). */
export interface LeaderPath {
  route: LonLat[];
  trail: LonLat[];
  age_s: number;
}

export interface RideRead {
  dots: Dot[];
  alerts: RideAlert[];
  /** With the link's leader key, while the leader's phone is sending it. */
  leaderPath?: LeaderPath;
}

const isLine = (v: unknown): v is LonLat[] =>
  Array.isArray(v) && v.every((p) => Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number" && Number.isFinite(n)));

export async function readRide(origin: string, ride: string, token: string, get: Fetch = fetch, leader: string | null = null, seal: RideSeal | null = null): Promise<RideRead | null> {
  try {
    const headers: Record<string, string> = { Accept: "application/json", "X-Ride-Token": token };
    if (leader) headers["X-Ride-Leader"] = leader;
    const response = await get(`${origin}/api/rides/${ride}`, { headers });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<RideRead> & { leader_path?: Partial<LeaderPath> & { sealed?: unknown } };
    if (seal) return await openRead(seal, body);
    const out: RideRead = { dots: Array.isArray(body.dots) ? body.dots : [], alerts: Array.isArray(body.alerts) ? body.alerts : [] };
    const path = body.leader_path;
    if (path && isLine(path.route) && isLine(path.trail)) out.leaderPath = { route: path.route, trail: path.trail, age_s: Number(path.age_s) || 0 };
    return out;
  } catch {
    return null;
  }
}

const isSpot = (v: Record<string, unknown> | null): v is { lon: number; lat: number } & Record<string, unknown> =>
  v !== null && typeof v.lon === "number" && typeof v.lat === "number" && Number.isFinite(v.lon) && Number.isFinite(v.lat);
const asRecord = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/**
 * A sealed ride's answer (lib/rideSeal.ts): each dot, alert and the leader's path opened with the link's key; any that
 * does not open is left out, a plain one too (only a phone without the link's secret, an older page, sends those).
 */
async function openRead(seal: RideSeal, body: Record<string, unknown>): Promise<RideRead> {
  const dots: Dot[] = [];
  for (const raw of Array.isArray(body.dots) ? body.dots : []) {
    const d = asRecord(raw);
    const v = asRecord(await openValue(seal, "dot", d?.sealed));
    if (!d || !isSpot(v)) continue;
    const dot: Dot = { lon: v.lon, lat: v.lat, age_s: Number(d.age_s) || 0, role: roleOf(v.role) };
    if (d.leader === true) dot.leader = true;
    dots.push(dot);
  }
  const opened: OpenedAlert[] = [];
  for (const raw of Array.isArray(body.alerts) ? body.alerts : []) {
    const a = asRecord(raw);
    const v = asRecord(await openValue(seal, "alert", a?.sealed));
    // Only the kinds the ride types send (the server checked plain ones; a sealed one it cannot).
    if (!a || typeof a.id !== "string" || !isSpot(v) || !ALERT_KIND_IDS.has(v.kind as string)) continue;
    opened.push({ id: a.id, kind: String(v.kind), text: typeof v.text === "string" ? v.text.slice(0, OTHER_MAX) : "", lon: v.lon, lat: v.lat, age_s: Number(a.age_s) || 0, mine: a.mine === true });
  }
  const out: RideRead = { dots, alerts: mergeAlerts(opened).map(asRideAlert) };
  const path = asRecord(body.leader_path);
  const p = asRecord(await openValue(seal, "path", path?.sealed));
  if (path && p && isLine(p.route) && isLine(p.trail)) out.leaderPath = { route: p.route, trail: p.trail, age_s: Number(path.age_s) || 0 };
  return out;
}

/** An opened alert as the banner takes it: its label and Call 911 from the ride types' lists, as the server answered them. */
function asRideAlert(a: OpenedAlert & { count: number }): RideAlert {
  const kind = Object.values(ALERT_KINDS).flat().find((k) => k.id === a.kind);
  return { ...a, label: kind?.label ?? "", call_911: kind?.call911 === true };
}
const ALERT_KIND_IDS = new Set(Object.values(ALERT_KINDS).flat().map((k) => k.id));

async function post(origin: string, path: string, body: unknown, send: Fetch): Promise<{ ok: boolean; body: Record<string, unknown> }> {
  try {
    const response = await send(`${origin}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const answer = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    return { ok: response.ok, body: answer };
  } catch {
    return { ok: false, body: {} };
  }
}

export async function sendPosition(origin: string, ride: string, token: string, p: LonLat, role: RideRole = DEFAULT_ROLE, send: Fetch = fetch, seal: RideSeal | null = null): Promise<boolean> {
  if (seal) {
    // Sealed: put on the grid here, as the server did; a spot outside the map's area is not sent.
    const spot = sendable(p);
    if (!spot) return false;
    const sealed = await sealValue(seal, "dot", { lon: spot[0], lat: spot[1], role });
    return (await post(origin, `/api/rides/${ride}/here`, { token, sealed }, send)).ok;
  }
  return (await post(origin, `/api/rides/${ride}/here`, { token, lon: p[0], lat: p[1], role }, send)).ok;
}

/**
 * The leader's route and ridden path (Stephen 2026-10-22: "Rebroadcast the route every 2 min or when it changes, not
 * keeping it on the server"): sent about every PATH_EVERY_MS and whenever the route changes; the server keeps each 2
 * minutes in memory, so the next must come before then.
 */
export const PATH_EVERY_MS = 100_000;
/** The soonest the server takes another (core.ride_presence.MIN_PATH_INTERVAL_S). */
export const PATH_MIN_GAP_MS = 25_000;
/** The most points the server takes in each line (core.ride_presence.PATH_MAX_POINTS). */
export const PATH_MAX_POINTS = 600;

/** A line of at most `max` points, its ends kept, the rest evenly picked; rounded to 5 decimals (about 1 m). */
export function thinLine(line: readonly LonLat[], max = PATH_MAX_POINTS): LonLat[] {
  const r = (p: LonLat): LonLat => [Math.round(p[0] * 1e5) / 1e5, Math.round(p[1] * 1e5) / 1e5];
  if (line.length <= max) return line.map(r);
  const out: LonLat[] = [];
  const step = (line.length - 1) / (max - 1);
  for (let i = 0; i < max; i += 1) out.push(r(line[Math.round(i * step)]));
  return out;
}

/** When the leader sends its path: the route changed, or the last went PATH_EVERY_MS ago (never sooner than the server takes). */
export function pathDue(lastAt: number, lastRouteKey: string, routeKey: string, now: number): boolean {
  if (now - lastAt < PATH_MIN_GAP_MS) return false;
  return routeKey !== lastRouteKey || now - lastAt >= PATH_EVERY_MS;
}

/** A route's identity for "it changed": its length and ends. */
export function routeKeyOf(line: readonly LonLat[]): string {
  if (!line.length) return "";
  const end = line[line.length - 1];
  return `${line.length}|${line[0].join(",")}|${end.join(",")}`;
}

/** The ridden path's first stretch left out (the ride often starts at home): this far from its first point. */
export const PRIVATE_START_M = 200;

/** The ridden path from where it first goes PRIVATE_START_M from its start; nothing while it has not. */
export function withoutStart(trail: readonly LonLat[]): readonly LonLat[] {
  const first = trail[0];
  if (!first) return trail;
  const kx = M_PER_DEG * Math.cos((first[1] * Math.PI) / 180);
  const away = trail.findIndex((p) => Math.hypot((p[0] - first[0]) * kx, (p[1] - first[1]) * M_PER_DEG) >= PRIVATE_START_M);
  return away < 0 ? [] : trail.slice(away);
}

export async function sendPath(origin: string, ride: string, token: string, route: readonly LonLat[], trail: readonly LonLat[], send: Fetch = fetch, seal: RideSeal | null = null): Promise<boolean> {
  if (seal) {
    const sealed = await sealValue(seal, "path", { route: sendableLine(thinLine(route), false), trail: sendableLine(thinLine(withoutStart(trail)), true) });
    return (await post(origin, `/api/rides/${ride}/path`, { token, sealed }, send)).ok;
  }
  return (await post(origin, `/api/rides/${ride}/path`, { token, route: thinLine(route), trail: thinLine(withoutStart(trail)) }, send)).ok;
}

export async function leaveRide(origin: string, ride: string, token: string, send: Fetch = fetch): Promise<boolean> {
  return (await post(origin, `/api/rides/${ride}/leave`, { token }, send)).ok;
}

export type SendOutcome = { ok: true; alert: RideAlert } | { ok: false; message: string };

export async function sendAlert(origin: string, ride: string, token: string, type: RideLinkType, kind: string, text: string, p: LonLat, send: Fetch = fetch, seal: RideSeal | null = null): Promise<SendOutcome> {
  const words = kind === "other" ? text.trim().slice(0, OTHER_MAX) : "";
  if (seal) {
    // Sealed: the checks the server made on the plain alert, made here (it sees none of it).
    const spot = sendable(p);
    const known = ALERT_KINDS[type].some((k) => k.id === kind) && (kind !== "other" || words !== "");
    if (!spot || !known) return { ok: false, message: t("The alert was not sent; try again.") };
    const sealed = await sealValue(seal, "alert", { kind, text: words, lon: spot[0], lat: spot[1] });
    const answer = await post(origin, `/api/rides/${ride}/alerts`, { token, sealed }, send);
    if (answer.ok && typeof answer.body.id === "string") {
      const alert = asRideAlert({ id: answer.body.id, kind, text: words, lon: spot[0], lat: spot[1], age_s: 0, mine: true, count: 1 });
      return { ok: true, alert };
    }
    return { ok: false, message: typeof answer.body.error === "string" ? answer.body.error : t("The alert was not sent; try again.") };
  }
  const answer = await post(origin, `/api/rides/${ride}/alerts`, { token, ride_type: type, kind, text: words, lon: p[0], lat: p[1] }, send);
  if (answer.ok) return { ok: true, alert: answer.body as unknown as RideAlert };
  return { ok: false, message: typeof answer.body.error === "string" ? answer.body.error : t("The alert was not sent; try again.") };
}

export async function clearAlert(origin: string, ride: string, token: string, id: string, send: Fetch = fetch): Promise<boolean> {
  return (await post(origin, `/api/rides/${ride}/alerts/${encodeURIComponent(id)}/clear`, { token }, send)).ok;
}
