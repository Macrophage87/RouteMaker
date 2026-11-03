/**
 * Avoid stairs (Stephen, 2026-11-02: "Add the option to avoid stairs for walking"; on the card he chose a switch of its
 * own in Settings, for Go and Plan alike). On, the walks of a Bikeshare or transit trip keep off flights of steps
 * wherever a step-free way is near (the API's `avoid_stairs`, core/walk_turns.py). A walk beside the rider's own bike
 * always does, so the switch is not sent for the other ride types. Off by default; kept on this device.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { t } from "./i18n.ts";

export const AVOID_STAIRS_KEY = "routemaker.walk.avoidStairs";
export const AVOID_STAIRS_LABEL = t("Avoid stairs on walks");
export const AVOID_STAIRS_HELP = t("Walks keep off steps where a ramp or elevator is near. Kept on this device.");

export function readAvoidStairs(store: KeyValueStore | null = browserStore()): boolean {
  try {
    return store?.getItem(AVOID_STAIRS_KEY) === "1";
  } catch {
    return false;
  }
}

/** Sent on the page when the switch changes, so the plan shown is planned again with it (App.tsx). */
export const AVOID_STAIRS_EVENT = "routemaker:avoid-stairs";

export function writeAvoidStairs(on: boolean, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(AVOID_STAIRS_KEY, on ? "1" : "0");
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(AVOID_STAIRS_EVENT, { detail: on }));
}
