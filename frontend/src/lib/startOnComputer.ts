/**
 * Start ride on a computer (the owner, 2026-10-21: "When you tap start route on something that doesn't look like a
 * phone, send a warning ... that this might not make sense and let them go back, or continue"). A device looks like
 * a phone (or a tablet) when its main pointer is a finger. Start anyway is remembered for this tab only.
 */
import type { StorageLike } from "./signIn.ts";

export const COMPUTER_HEADING = "This looks like a computer";
export const COMPUTER_LEAD = "Start ride gives turn-by-turn directions as you ride, for a phone on your bike. On a computer it may not make sense.";
export const COMPUTER_BACK = "Go back";
export const COMPUTER_ANYWAY = "Start anyway";
export const COMPUTER_OK_KEY = "routemaker.start-on-computer";

/** Whether the device looks like a phone or tablet: a finger as its main pointer. */
export function looksLikePhone(match: ((query: string) => { matches: boolean }) | null = typeof matchMedia === "function" ? matchMedia : null): boolean {
  return !!match && match("(pointer: coarse)").matches;
}

/** Whether to ask before Start ride: not a phone, and Start anyway not chosen in this tab. */
export function askBeforeStart(phone: boolean, storage: StorageLike | null): boolean {
  if (phone) return false;
  try {
    return storage?.getItem(COMPUTER_OK_KEY) !== "yes";
  } catch {
    return true;
  }
}

/** Start anyway: not asked again in this tab. */
export function rememberStartAnyway(storage: StorageLike | null): void {
  try {
    storage?.setItem(COMPUTER_OK_KEY, "yes");
  } catch {
    // A refused storage asks again next time.
  }
}
