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
 * - Only a step that found a new route is kept; one that did not is undone, so the next press asks the same again.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { HILLS_MIN, hillsWords, seeksClimbs, stressMax, stressWords, type Dials } from "./dials.ts";
import type { PresetId } from "./presets.ts";

export type Ease = "calmer" | "flatter";

/** The traffic slider's steps, low to high (calmer); 95 is "Calmest", short of the target-distance top. */
export const CALMER_STEPS: readonly number[] = [10, 20, 40, 70, 80, 90, 95];
/** The hills slider's steps, high to low (flatter): hills matter less (or some extra climbing), fastest time, gentler
 * grades, avoids hills. */
export const FLATTER_STEPS: readonly number[] = [50, 0, -40, HILLS_MIN];

/** The words on each button: few on screen (the owner, 2026-10-20); the name says the rest. */
export const EASE_TEXT: Record<Ease, string> = { calmer: "Calmer", flatter: "Flatter" };
/** Each button's name, heard by screen readers in full. */
export const EASE_NAME: Record<Ease, string> = {
  calmer: "Calmer: less traffic, plan again from here",
  flatter: "Flatter: fewer hills, plan again from here",
};
/** Said when the slider is already at its last step: nothing is planned. */
export const EASE_AT_END: Record<Ease, string> = {
  calmer: "Already the calmest route.",
  flatter: "Already the flattest route.",
};

/** The ride's dials one step calmer or flatter, or null when there is no further step on this ride type. */
export function eased(preset: PresetId, dials: Dials, ease: Ease): Dials | null {
  if (ease === "calmer") {
    const top = stressMax(preset);
    const next = CALMER_STEPS.find((s) => s > dials.stress && s <= top);
    return next === undefined ? null : { ...dials, stress: next };
  }
  const next = FLATTER_STEPS.find((h) => h < dials.hills);
  return next === undefined ? null : { ...dials, hills: next };
}

/** What a press says while it plans: the step it took, in the sliders' own words. */
export function easeFinding(preset: PresetId, dials: Dials, ease: Ease): string {
  return ease === "calmer"
    ? `Finding a calmer route. ${stressWords(dials.stress)}.`
    : `Finding a flatter route. ${hillsWords(dials.hills, seeksClimbs(preset))}.`;
}
