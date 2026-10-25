/**
 * Ride mode's Calmer and Flatter buttons (the owner, 2026-10-23: "Add two button on ride that would reduce stress
 * tolerance and reroute when pressed. Do this for both traffic and hill stress.").
 *
 * - Calmer moves the ride's traffic slider one step toward calm, Flatter its hills slider one step toward flat, and
 *   each re-plans from where the rider is, as Re-plan from here does (the way ahead first, the U-turn rules). A
 *   second press takes the next step, until the last one.
 * - The steps are where the sliders' words change (lib/dials.ts stressWords, hillsWords), so each press is a
 *   difference the rider would see in Plan. Calmer stops at 95: the top of the slider is the target-distance
 *   search, which is Plan's to choose, not a way to the end.
 * - The steps are kept for this ride only: Plan's sliders are as they were after End ride.
 * - Only a step that found a route is kept; one that found none, or only the way back to the line the ride was on, is
 *   undone, so the next press asks the same again. A route that keeps to the rider's line says so (EASE_SAME): on a
 *   ride with only gentle climbs a flatter step may change nothing (the hill cost prices grades past the rider's
 *   LT1 grade only, the "Hill stress above LT1" proposal).
 * - A press is not counted as riding past a U-turn (lib/navigate.ts uturnStep): presses come close together.
 * - Since 2026-10-24 the two are in the ride's More panel with Skip this stop and the settings (Stephen: "Let's put
 *   options like skip a stop, lower traffic and hills in an expansion with settings"), not round side buttons.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { HILLS_MIN, hillsWords, seeksClimbs, stressMax, stressWords, type Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";

export type Ease = "calmer" | "flatter";

/** The traffic slider's steps, low to high (calmer); 95 is "Calmest", short of the target-distance top. */
export const CALMER_STEPS: readonly number[] = [10, 20, 40, 70, 80, 90, 95];
/** The hills slider's steps, high to low (flatter): easy up to 12% (Mountain Goat: some extra climbing), 8%, 5%
 * and 1%, the grades the slider sets there (`lt1GradePct`). */
export const FLATTER_STEPS: readonly number[] = [50, 0, -40, HILLS_MIN];

/** Each button's name, heard by screen readers in full; on screen the symbol alone (a car or a mountain, each with a
 * down arrow; the owner, 2026-10-23: "Take the words out. Symbol should be clear"). */
export const EASE_NAME: Record<Ease, string> = {
  calmer: "Less traffic: plan again from here",
  flatter: "Fewer hills: plan again from here",
};
/** Their words in the ride's More panel (Stephen 2026-10-24: "lower traffic and hills"), each within its name above. */
export const EASE_SHOWN: Record<Ease, string> = {
  calmer: "Less traffic",
  flatter: "Fewer hills",
};
/** Said when the slider is already at its last step: nothing is planned. */
export const EASE_AT_END: Record<Ease, string> = {
  calmer: "Already the calmest route.",
  flatter: "Already the flattest route.",
};

/**
 * The ride's dials one step calmer or flatter, or null when there is no further step on this ride type. A step whose
 * words are the slider's words now is passed over (a ride at 76 goes to 90, not to 80, which reads the same).
 */
export function eased(preset: PresetId, dials: Dials, ease: Ease): Dials | null {
  if (ease === "calmer") {
    const top = stressMax(preset);
    const now = stressWords(dials.stress);
    const next = CALMER_STEPS.find((s) => s > dials.stress && s <= top && stressWords(s) !== now);
    return next === undefined ? null : { ...dials, stress: next };
  }
  const climbs = seeksClimbs(preset);
  const now = hillsWords(dials.hills, climbs);
  const next = FLATTER_STEPS.find((h) => h < dials.hills && hillsWords(h, climbs) !== now);
  return next === undefined ? null : { ...dials, hills: next };
}

/** Said in place of "New route found." when the press found the line the rider is on: nothing calmer or flatter here. */
export const EASE_SAME: Record<Ease, string> = {
  calmer: "Same route: no calmer way from here.",
  flatter: "Same route: no less steep way from here.",
};

/** Whether a new route keeps to the line the rider was on: nearly all its points are that line's own (one router). */
export function sameLine(next: readonly LonLat[], before: readonly LonLat[]): boolean {
  if (next.length === 0) return false;
  const key = (p: LonLat) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
  const had = new Set(before.map(key));
  return next.filter((p) => had.has(key(p))).length / next.length >= SAME_SHARE;
}
export const SAME_SHARE = 0.9;

/** What a press says while it plans: the step it took, in the sliders' own words. */
export function easeFinding(preset: PresetId, dials: Dials, ease: Ease): string {
  return ease === "calmer"
    ? `Finding a calmer route. ${stressWords(dials.stress)}.`
    : `Finding a flatter route. ${hillsWords(dials.hills, seeksClimbs(preset))}.`;
}
