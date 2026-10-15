/**
 * Novice and Nervous (v0.7.0 plan): where the only way through is a busy road (LTS 3 or worse), or a calm route
 * would pass the 1.4 times cap, the route shows "Own bike + transit" and "Bikeshare + transit" beside it at once,
 * each found in the background with its bike legs planned as Novice and Nervous plans them (the transit ride
 * types' `novice_legs`), each with a line naming the busy stretch it avoids. The server says when (core.routing
 * novice_note); this words it, in US units first with metric in brackets.
 */
import type { NoviceNote, RouteResponse } from "./api.ts";
import { fitDials, startDials, type Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { PresetId } from "./presets.ts";

/** The two ways offered, in the order shown. */
export const NOVICE_TRANSIT_CHOICES: readonly { preset: PresetId; label: string }[] = [
  { preset: "bike-transit", label: "Own bike + transit" },
  { preset: "bikeshare-transit", label: "Bikeshare + transit" },
];

/** A transit ride type's dials for the offer: its own starting sliders, its bike legs as Novice and Nervous's. */
export function noviceTransitDials(preset: PresetId): Dials {
  return fitDials(preset, { ...startDials(preset), noviceLegs: true });
}

/** The points a transit trip is asked through: its start and its end only (a transit ride type takes two). */
export function noviceTripPoints<P>(points: readonly P[]): P[] {
  return points.length >= 2 ? [points[0], points[points.length - 1]] : [...points];
}

/** A level in words: "LTS 3", "LTS 4", "Avoid". */
function levelWords(level: number): string {
  return level >= 5 ? "Avoid" : `LTS ${level}`;
}

/** The busy road the route cannot avoid, in words: "16th St (LTS 3) for 0.4 mi (0.6 km)". */
export function busiestSaid(note: NoviceNote): string {
  const b = note.busiest;
  if (!b) return `busy roads for ${formatDistance(note.busy_m)}`;
  const road = b.name ?? "a busy road";
  return `${road} (${levelWords(b.level)}) for ${formatDistance(b.metres)}`;
}

/** What each option avoids: the busy stretch, or the long way round where the cap was the reason. */
function avoidedSaid(note: NoviceNote): string {
  return note.busiest || note.busy_m > 0 ? busiestSaid(note) : "the long way round a calm route takes here";
}

/** Whether the offer shows: Novice and Nervous, and the server's word that only busy roads (or the cap) are left. */
export function noviceOfferShown(route: Pick<RouteResponse, "novice" | "provisional"> | null, preset: PresetId): boolean {
  // Not on Go's first route (v0.7.0, "Faster routing"): the offer is decided on the full plan, so it does not show
  // and then go as the better route arrives (the API sends no `novice` on a first route either).
  return preset === "novice" && route?.provisional !== true && route?.novice?.transit === true;
}

/** The offer's lead sentence, or null where none is made. */
export function noviceOfferText(route: Pick<RouteResponse, "novice"> | null, preset: PresetId): string | null {
  const note = route?.novice;
  if (!noviceOfferShown(route ?? null, preset) || !note) return null;
  if (!note.busiest && note.busy_m <= 0) return "A calm route here would be more than 1.4 times as long. Transit or bikeshare can shorten it.";
  return `Only a busy road connects here: ${busiestSaid(note)}. Transit or bikeshare can carry you past it.`;
}

/** Each option's trip, found in the background as the offer shows. */
export type NoviceTrip = { kind: "finding" } | { kind: "found"; minutes: number } | { kind: "none" };

/** An option's one line: "about 34 min door to door, avoiding 16th Street Northwest (LTS 3) for 0.4 mi (0.6 km)." */
export function noviceTripLine(trip: NoviceTrip | undefined, note: NoviceNote): string {
  const avoiding = `avoiding ${avoidedSaid(note)}`;
  if (!trip || trip.kind === "finding") return `Finding a trip, ${avoiding}.`;
  if (trip.kind === "none") return `No trip found just now; it would avoid ${avoidedSaid(note)}.`;
  return `About ${trip.minutes} min door to door, ${avoiding}.`;
}

/** An answer as the option's trip: its door-to-door minutes, or none. */
export function noviceTripOf(answer: { ok: true; route: RouteResponse } | { ok: false }): NoviceTrip {
  const minutes = answer.ok ? answer.route.transit?.minutes : undefined;
  return typeof minutes === "number" ? { kind: "found", minutes } : { kind: "none" };
}

/** Said when a choice is taken. */
export function noviceTransitSaid(label: string): string {
  return `${label}, with the bike legs planned for a novice rider.`;
}
