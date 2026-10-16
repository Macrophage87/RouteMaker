/**
 * Where the keyboard focus goes when part of Ride mode or the planner goes away under it, as decisions
 * a test can run without a browser (RideMode.tsx and App.tsx do the focusing).
 */

/** The Ride mode blocks that can go while they hold the focus: the 311 button's block, the off-route buttons. */
export type RideBlock = "311" | "off";

/** Which block `target` is in, if any; `blocks` are the blocks' elements (null while not on the page). */
export function blockOf(target: unknown, blocks: Record<RideBlock, { contains(node: unknown): boolean } | null>): RideBlock | null {
  if (!target) return null;
  if (blocks["311"]?.contains(target)) return "311";
  if (blocks.off?.contains(target)) return "off";
  return null;
}

/**
 * Review a11y-3: after going off route, back on, or in or out of DC, whether the focus goes to Where am
 * I?. Only when it was in a block that has just gone and is now lost (on the page's body, or on an
 * element no longer in it): never otherwise, so going off route does not move a focus that is fine,
 * which would talk over the urgent off-route cue.
 */
export function rescueRideFocus(change: {
  focusWasIn: RideBlock | null;
  before: { off: boolean; show311: boolean };
  now: { off: boolean; show311: boolean };
  focusLost: boolean;
}): boolean {
  if (!change.focusLost) return false;
  if (change.focusWasIn === "311") return change.before.show311 && !change.now.show311;
  if (change.focusWasIn === "off") return change.before.off && !change.now.off;
  return false;
}

/**
 * Review a11y-2: after Undo or Redo was pressed, where the focus goes. "stay" while the pressed button
 * still works or the focus is somewhere else that is fine; else the other button if it works, else the
 * Points heading.
 */
export function afterHistoryStep<E>(press: { button: E; other: E | null }, now: E | null, body: E, usable: (element: E) => boolean): "stay" | "other" | "heading" {
  if (usable(press.button)) return "stay";
  if (now !== null && now !== body && now !== press.button) return "stay";
  return press.other !== null && usable(press.other) ? "other" : "heading";
}
