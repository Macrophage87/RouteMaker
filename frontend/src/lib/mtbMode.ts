/**
 * The Mountain Bike ride type (docs/MTB-TOPO-PLAN.md, slice 6; OWNER-DECISIONS 90, 111, 148,
 * 454: "Mountain Goat and Mountain Bike are separate modes"). The API owns the rules
 * (src/routemaker/mtbmode.py, src/core/mtb.py); this is the level choice, what choosing the
 * ride type turns on, and the route's reading said in words.
 *
 * The owner's defaults of 2026-10-11 ("Those work for me."): hardest trail level 2 (blue),
 * a choice of 1 to 4; unrated trails count as 2; a loop from a trailhead on; the
 * mountain-bike and contour layers on.
 *
 * Second pass (the owner, 2026-10-11): "two options for difficulty: preferred difficulty and max
 * difficulty." The hardest level above is the max; the preferred level (default 2) is never above it:
 * lowering the hardest below it lowers it too, and the panel says so.
 */
import type { PresetId } from "./presets.ts";
import { formatDistance, formatSpeed } from "./format.ts";

export const MTB_PRESET: PresetId = "mountain-bike";
export const MTB_LEVELS = [1, 2, 3, 4] as const;
export type MtbLevel = (typeof MTB_LEVELS)[number];
/** `routemaker.mtbmode.DEFAULT_MAX_LEVEL`, which tests/test_mtbmode.py holds this to. */
export const DEFAULT_MTB_LEVEL: MtbLevel = 2;
/** `routemaker.mtbmode.DEFAULT_PREFERRED_LEVEL`, which tests/test_mtbmode.py holds this to. */
export const DEFAULT_MTB_PREFERRED: MtbLevel = 2;
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
export const MTB_PREFERRED_LEGEND = "Preferred trail level";

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

/** The preferred level when none is chosen: 2, or the hardest where that is lower (an old link's `level=1`). */
export function defaultMtbPreferred(hardest: MtbLevel): MtbLevel {
  return Math.min(DEFAULT_MTB_PREFERRED, hardest) as MtbLevel;
}

/** The preferred level: the rider's, or the default, never above the hardest (`mtbmode.preferred_level`). */
export function mtbPreferredOf(dials: { mtbLevel?: number; mtbPreferred?: number }): MtbLevel {
  const hardest = mtbLevelOf(dials);
  const chosen = fitMtbLevel(dials.mtbPreferred);
  return chosen === undefined ? defaultMtbPreferred(hardest) : (Math.min(chosen, hardest) as MtbLevel);
}

/** The dials with a preferred level, held to the hardest; the default left out, so a link stays short. */
function settlePreferred<D extends { mtbLevel?: number; mtbPreferred?: number }>(next: D, preferred: number | undefined): D {
  const hardest = mtbLevelOf(next);
  const fitted = fitMtbLevel(preferred);
  const held = fitted === undefined ? undefined : Math.min(fitted, hardest);
  if (held === undefined || held === defaultMtbPreferred(hardest)) delete next.mtbPreferred;
  else next.mtbPreferred = held;
  return next;
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

/**
 * The dials with a hardest level chosen: the default is left out, so a link stays as short as before.
 * A preferred level above the new hardest is lowered to it (never past the max).
 */
export function withMtbLevel<D extends { mtbLevel?: number; mtbPreferred?: number }>(dials: D, level: MtbLevel): D {
  const next = { ...dials };
  if (level === DEFAULT_MTB_LEVEL) delete next.mtbLevel;
  else next.mtbLevel = level;
  return settlePreferred(next, mtbPreferredOf(dials));
}

/** The dials with a preferred level chosen, held to the hardest; the default left out. */
export function withMtbPreferred<D extends { mtbLevel?: number; mtbPreferred?: number }>(dials: D, level: MtbLevel): D {
  return settlePreferred({ ...dials }, level);
}

/**
 * What the panel says, politely, when lowering the hardest level lowered the preferred one with it
 * (the clamp is never silent); null when the preferred level stayed.
 */
export function mtbPreferredClamped(
  before: { mtbLevel?: number; mtbPreferred?: number },
  after: { mtbLevel?: number; mtbPreferred?: number },
): string | null {
  const was = mtbPreferredOf(before);
  const now = mtbPreferredOf(after);
  if (now >= was) return null;
  return `Preferred trail level lowered to ${mtbLevelWords(now)}: it can't be harder than the hardest level.`;
}

export function mtbLevelLabel(level: number): string {
  return MTB_LEVEL_OPTIONS.find((o) => o.level === level)?.label ?? `Level ${level}`;
}

/** The level in running text: "level 2 (blue)". */
function mtbLevelWords(level: number): string {
  return mtbLevelLabel(level).replace(/^Level/, "level");
}

/** What the API says of a Mountain Bike route (`RouteBody.mtb`). */
export interface MtbReading {
  max_level: number;
  /** The preferred level used (second pass); absent from an answer made before it. */
  preferred_level?: number | null;
  limited?: "time" | "untraced" | "no_way_round" | "no_mtb_graph" | null;
  candidates?: number | null;
  rounds?: number | null;
  trail_m?: number | null;
  singletrack_m?: number | null;
  over_level_m?: number | null;
  long_lts3_m?: number | null;
  lts4_m?: number | null;
  /** Metres on trails easier, and harder (up to `max_level`), than `preferred_level`. */
  easier_m?: number | null;
  harder_m?: number | null;
  level_step?: number | null;
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
  const level = mtbLevelWords(reading.max_level);
  if (reading.limited === "no_mtb_graph") {
    warnings.push(
      "The mountain-bike trails are not available right now, so this route keeps to roads and ordinary paths. Try again later for a trail route.",
    );
    return { warnings, notes };
  }
  const over = reading.over_level_m ?? 0;
  if (over >= SAY_FROM_M) {
    warnings.push(
      `This route uses ${formatDistance(over)} of trail harder than ${level}: no way round it was found. Check the trail before you ride, or raise your hardest level.`,
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
  // The second pass: how the trails sit against the preferred level, easier or harder, in words.
  if (reading.preferred_level != null) {
    const preferred = mtbLevelWords(reading.preferred_level);
    const easier = reading.easier_m ?? 0;
    const harder = reading.harder_m ?? 0;
    if (easier >= SAY_FROM_M) notes.push(`${formatDistance(easier)} of trail is easier than your preferred ${preferred}.`);
    if (harder >= SAY_FROM_M) notes.push(`${formatDistance(harder)} of trail is harder than your preferred ${preferred}, up to ${level}.`);
    if (easier < SAY_FROM_M && harder < SAY_FROM_M && single >= SAY_FROM_M && (reading.over_level_m ?? 0) < SAY_FROM_M) {
      notes.push(`Its mountain-bike trails are at your preferred ${preferred}.`);
    }
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
