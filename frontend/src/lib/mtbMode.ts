/**
 * The Mountain Bike ride type (docs/MTB-TOPO-PLAN.md, slice 6; OWNER-DECISIONS 90, 111, 148,
 * 454: "Mountain Goat and Mountain Bike are separate modes"). The API owns the rules
 * (src/routemaker/mtbmode.py, src/core/mtb.py); this is the level choice, what choosing the
 * ride type turns on, and the route's reading said in words.
 *
 * The owner's defaults of 2026-10-11 ("Those work for me."): hardest trail level 2 (blue),
 * a choice of 1 to 4; unrated trails count as 2; a loop from a trailhead on; the
 * mountain-bike and contour layers on.
 */
import type { PresetId } from "./presets.ts";
import { formatDistance, formatSpeed } from "./format.ts";

export const MTB_PRESET: PresetId = "mountain-bike";
export const MTB_LEVELS = [1, 2, 3, 4] as const;
export type MtbLevel = (typeof MTB_LEVELS)[number];
/** `routemaker.mtbmode.DEFAULT_MAX_LEVEL`, which tests/test_mtbmode.py holds this to. */
export const DEFAULT_MTB_LEVEL: MtbLevel = 2;
/** `routemaker.mtbmode.UNRATED_LEVEL`. */
export const UNRATED_MTB_LEVEL: MtbLevel = 2;
/** `routemaker.mtbmode.SINGLETRACK_SPEED_KMH`. */
export const SINGLETRACK_SPEED_KMH = 10;

/** Each level's colour (the mountain-bike layer's, OWNER-DECISIONS 456) and words: never colour alone. */
export const MTB_LEVEL_OPTIONS: readonly { level: MtbLevel; label: string; hint: string }[] = [
  { level: 1, label: "Level 1 (green)", hint: "Easiest trails only: wide, smooth, gentle." },
  { level: 2, label: "Level 2 (blue)", hint: "Intermediate: roots, rocks and short steep pitches. Unrated trails count here." },
  { level: 3, label: "Level 3 (black)", hint: "Difficult: technical, steep, with obstacles to ride over." },
  { level: 4, label: "Level 4 (red)", hint: "Very difficult and above: expert features, drops and exposure." },
];

export const MTB_LEVEL_LEGEND = "Hardest trail level";

export function isMtb(preset: PresetId): boolean {
  return preset === MTB_PRESET;
}

/** A level the API will take (a whole number, 1 to 4), or undefined. */
export function fitMtbLevel(value: unknown): MtbLevel | undefined {
  if (typeof value !== "number" || !Number.isInteger(value)) return undefined;
  return (MTB_LEVELS as readonly number[]).includes(value) ? (value as MtbLevel) : undefined;
}

export function mtbLevelOf(dials: { mtbLevel?: number }): MtbLevel {
  return fitMtbLevel(dials.mtbLevel) ?? DEFAULT_MTB_LEVEL;
}

/**
 * The dials a ride type starts with, as the ride-type dialog chose them, with Mountain Bike's own
 * start on top when the rider comes to it from another ride type: Make it a loop on (a loop from a
 * trailhead). The same object when nothing changes, so the caller can tell (App turns the layers on).
 */
export function mtbChosen<D extends { loop?: boolean }>(from: PresetId, to: PresetId, chosen: D): D {
  if (!isMtb(to) || isMtb(from) || chosen.loop === true) return chosen;
  return { ...chosen, loop: true };
}

/** The dials with a level chosen: the default is left out, so a link stays as short as before. */
export function withMtbLevel<D extends { mtbLevel?: number }>(dials: D, level: MtbLevel): D {
  const next = { ...dials };
  if (level === DEFAULT_MTB_LEVEL) delete next.mtbLevel;
  else next.mtbLevel = level;
  return next;
}

export function mtbLevelLabel(level: number): string {
  return MTB_LEVEL_OPTIONS.find((o) => o.level === level)?.label ?? `Level ${level}`;
}

/** What the API says of a Mountain Bike route (`RouteBody.mtb`). */
export interface MtbReading {
  max_level: number;
  limited?: "time" | "untraced" | "no_way_round" | "no_mtb_graph" | null;
  candidates?: number | null;
  rounds?: number | null;
  trail_m?: number | null;
  singletrack_m?: number | null;
  over_level_m?: number | null;
  long_lts3_m?: number | null;
  lts4_m?: number | null;
  trail_weight?: number | null;
  singletrack_speed_kmh?: number | null;
  router_duration_s?: number | null;
}

/** Below this many metres a figure is not worth saying (a crossing, a driveway). */
const SAY_FROM_M = 20;

/**
 * The route's reading in sentences, in the order a rider needs them: first anything the rules
 * could not hold (a harder trail, a busy road, no mountain-bike graph), then how much is trail,
 * and the time's basis. Words only: no colour, no icon carries any of it.
 */
export function mtbNotes(reading: MtbReading | null | undefined): { warnings: string[]; notes: string[] } {
  const warnings: string[] = [];
  const notes: string[] = [];
  if (!reading) return { warnings, notes };
  const level = mtbLevelLabel(reading.max_level).replace(/^Level/, "level");
  if (reading.limited === "no_mtb_graph") {
    warnings.push(
      "The mountain-bike trails are not available right now, so this route keeps to roads and ordinary paths. Try again later for a trail route.",
    );
    return { warnings, notes };
  }
  const over = reading.over_level_m ?? 0;
  if (over >= SAY_FROM_M) {
    warnings.push(
      `This route uses ${formatDistance(over)} of trail harder than ${level}: no way round it was found. Check the trail before you ride, or choose a higher level.`,
    );
  }
  const busy = reading.lts4_m ?? 0;
  if (busy >= SAY_FROM_M) {
    warnings.push(`It uses ${formatDistance(busy)} of busy road (LTS 4 or Avoid): no calmer connection was found.`);
  }
  const long3 = reading.long_lts3_m ?? 0;
  if (long3 >= SAY_FROM_M) {
    warnings.push(`It has ${formatDistance(long3)} of LTS 3 road in stretches of a half mile or more.`);
  }
  if (reading.limited === "time" || reading.limited === "untraced") {
    notes.push("The trail search ran short of time, so this may not be the most trail-rich route.");
  }
  const trail = reading.trail_m ?? 0;
  const single = reading.singletrack_m ?? 0;
  if (trail >= SAY_FROM_M) {
    notes.push(
      single >= SAY_FROM_M
        ? `${formatDistance(trail)} on trail, ${formatDistance(single)} of it mountain-bike singletrack, up to ${level}.`
        : `${formatDistance(trail)} on trail, up to ${level}.`,
    );
  } else {
    notes.push("No trail was found on this route; it keeps to calm roads and paths.");
  }
  if (single >= SAY_FROM_M) {
    notes.push(`The time counts singletrack at about ${formatSpeed(reading.singletrack_speed_kmh ?? SINGLETRACK_SPEED_KMH)}.`);
  }
  return { warnings, notes };
}

/** The one polite announcement for a new Mountain Bike route: its warnings, or nothing. */
export function mtbSaid(reading: MtbReading | null | undefined): string {
  return mtbNotes(reading).warnings.join(" ");
}
