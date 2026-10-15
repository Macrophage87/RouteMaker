/**
 * Novice and Nervous (v0.7.0 plan): where the only way through is a busy road (LTS 3 or worse), the route says
 * which road and offers transit or bikeshare for the trip, its bike legs still planned as Novice and Nervous
 * plans them (the transit ride types' `novice_legs`). The server says when (core.routing novice_note); this
 * words it, in US units first with metric in brackets.
 */
import type { NoviceNote, RouteResponse } from "./api.ts";
import { formatDistance } from "./format.ts";
import type { PresetId } from "./presets.ts";

/** The two ways offered, in the order shown. */
export const NOVICE_TRANSIT_CHOICES: readonly { preset: PresetId; label: string }[] = [
  { preset: "bike-transit", label: "Own bike + transit" },
  { preset: "bikeshare-transit", label: "Bikeshare + transit" },
];

/** A busy level in words: "LTS 3", "LTS 4", "Avoid". */
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

/** The offer's sentence, or null where none is made (another ride type, or a calm enough route). */
export function noviceOfferText(route: Pick<RouteResponse, "novice"> | null, preset: PresetId): string | null {
  const note = route?.novice;
  if (preset !== "novice" || !note || !note.transit) return null;
  return `Only a busy road connects here: ${busiestSaid(note)}. Transit or bikeshare can carry you past it.`;
}

/** Said when a choice is taken. */
export function noviceTransitSaid(label: string): string {
  return `${label}, with the bike legs planned for a novice rider. Planning.`;
}
