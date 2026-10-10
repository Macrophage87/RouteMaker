/**
 * The ride-type dialog's decisions, kept out of the component so they can be
 * tested without a browser (the lane has no DOM harness).
 *
 * The owner, 2026-09-27: "Have the ability to change route modes in a modal
 * dialog instead of a radio button. Selecting a preset will change the
 * sliders."
 */
import { PRESETS, type PresetId } from "./presets.ts";
import { startDials, type Carrying, type Dials } from "./dials.ts";

/** A focusable element as the Tab trap sees it: a radio has a type, a group name and a state. */
export type TabCandidate = { type?: string; name?: string; checked?: boolean };

/**
 * The Tab stops among a dialog's focusable elements, as the browser's own Tab order has them: a
 * group of radios (one name) is one stop, its checked radio (or its first, when none is checked);
 * the arrow keys move within the group. A trap that walked every radio would make each a stop.
 */
export function tabStops<T extends TabCandidate>(items: T[]): T[] {
  const checked = new Set(items.filter((i) => i.type === "radio" && i.name && i.checked).map((i) => i.name));
  const seen = new Set<string>();
  return items.filter((i) => {
    if (i.type !== "radio" || !i.name) return true;
    if (checked.has(i.name)) return i.checked === true;
    if (seen.has(i.name)) return false;
    seen.add(i.name);
    return true;
  });
}

/** Tab and Shift+Tab inside the dialog wrap around; focus never leaves it. */
export function nextFocus(index: number, count: number, backwards: boolean): number {
  if (count <= 0) return -1;
  if (index < 0 || index >= count) return backwards ? count - 1 : 0;
  return (index + (backwards ? count - 1 : 1)) % count;
}

/** The key that closes the dialog without choosing. */
export function closesDialog(key: string): boolean {
  return key === "Escape" || key === "Esc";
}

/** Which card takes the focus when the dialog opens: the ride type in use. */
export function initialCard(current: PresetId): number {
  const index = PRESETS.findIndex((p) => p.id === current);
  return index < 0 ? 0 : index;
}

/**
 * Choosing a ride type: its sliders move to where it starts them; the ride
 * time the rider picked stays, since it is about the ride and not the bike.
 * Avoid gravel and Keep to roads stay, and so does Make it a loop (OWNER-DECISIONS 374): every
 * point after the start was placed as a loop's stop. Mass Ride has no loop
 * (loop.loopStops), so there the flag is kept unused, and the next ride type
 * brings the loop back.
 */
export function choose(preset: PresetId, carrying: Carrying | null, current: Dials): Dials {
  const start = startDials(preset, carrying, current.when, current.assist, current.bike ?? null);
  return {
    ...start,
    ...(current.avoidGravel ? { avoidGravel: true } : {}),
    ...(current.trailsOff ? { trailsOff: true } : {}),
    ...(current.loop === true ? { loop: true } : {}),
  };
}

/** Whether the rider has moved a slider away from the ride type's start. */
export function isCustom(preset: PresetId, dials: Dials): boolean {
  const start = startDials(preset, dials.carrying, dials.when, dials.assist, dials.bike ?? null);
  return start.stress !== dials.stress || start.hills !== dials.hills;
}
