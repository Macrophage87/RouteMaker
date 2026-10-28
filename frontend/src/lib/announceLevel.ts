/**
 * How much the screen reader is told (the owner, 2026-10-11 20:23 UTC: "Things like announcements by screen
 * readers can be adjusted in settings"): Settings > Display > Announcements, Brief or Full. Unset, it is
 * Brief in Go and Full in Plan. The essentials are always said, whatever the setting: the route found, the
 * start and end of guidance, the start Go found, and every error or notice. Brief leaves out the extra
 * narration: "Finding your location…", "Planning a route to …", the view switched to, the ride type picked,
 * "The map is at your location."
 *
 * Kept on this device only (localStorage), like accessibility mode.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import type { AppMode } from "./appMode.ts";
import { t } from "./i18n.ts";

export type AnnounceLevel = "brief" | "full";
/** The stored choice: "" is unset (by view). */
export type AnnounceChoice = "" | AnnounceLevel;

export const ANNOUNCE_KEY = "routemaker.announcements";

export const ANNOUNCE_LABEL: Record<AnnounceLevel, string> = {
  brief: t("Brief: the route, guidance and errors"),
  full: t("Full: also what the app is doing"),
};

export const ANNOUNCE_HINT = t("What screen readers are told. Unset, Go is brief and Plan is full. Routes, guidance and errors are always said.");

export function readAnnounceChoice(store: KeyValueStore | null = browserStore()): AnnounceChoice {
  try {
    const raw = store?.getItem(ANNOUNCE_KEY);
    return raw === "brief" || raw === "full" ? raw : "";
  } catch {
    return "";
  }
}

export function writeAnnounceChoice(choice: AnnounceChoice, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(ANNOUNCE_KEY, choice);
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
}

/** The level in force: the rider's choice, else Brief in Go and Full in Plan. */
export function announceLevel(choice: AnnounceChoice, mode: AppMode): AnnounceLevel {
  return choice !== "" ? choice : mode === "go" ? "brief" : "full";
}

/** Whether an extra (not essential) announcement is said at this level. Essentials are always said. */
export function saysExtra(level: AnnounceLevel): boolean {
  return level === "full";
}
