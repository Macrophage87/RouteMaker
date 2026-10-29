/**
 * Load route's popup (the owner, 2026-10-22: "Load route should have a popup ... Basically let people load a gpx or
 * select their saved routes", and "Saved routes need a less cluttered and more intuitive interface"): Open GPX file
 * first, then one plain list of the rider's routes, saved ones first, then the ones kept on this device. A row is the
 * route's name and one short line; a tap opens it. Renaming, deleting and versions stay in Save & load.
 */
import { formatDistance } from "./format.ts";
import { rowDetails, type SavedSummary } from "./savedRoutes.ts";
import type { KeptRoute } from "./offlineRoutes.ts";
import { PRESETS, isTransit, presetSaid, type PresetId } from "./presets.ts";
import { t } from "./i18n.ts";

/** The popup's one name, on Plan's bar and on Go's More entry (the owner, 2026-10-26: "Add saved routes in the more
 * part of the go tab"); P12: Go's entry and title said "Saved routes". */
export const LOAD_ROUTE = t("Load route");
export const LOAD_GPX = t("Open GPX file");
export const LOAD_CLOSE = t("Close");
export const LOAD_NONE = t("No saved routes yet. Plan a route and press Save route.");
export const LOAD_SIGN_IN = t("Sign in to see your saved routes");
export const LOAD_FAILED = t("Your saved routes could not be read; try again shortly.");
export const LOAD_SEARCH = t("Search your routes");
/** The search box shows only once the list is longer than this: a short list is read at a glance. */
export const SEARCH_FROM = 6;

export type LoadRow =
  | { kind: "saved"; key: string; name: string; detail: string; id: number }
  | { kind: "kept"; key: string; name: string; detail: string; kept: KeptRoute };

/** "4.7 mi (7.6 km) · On this device": a kept route's line, shorter than the Save & load sheet's. */
export function keptLine(route: Pick<KeptRoute, "distanceM" | "lastRide">): string {
  return `${formatDistance(route.distanceM)} · ${route.lastRide ? "Last ride, on this device" : "On this device"}`;
}

/** The popup's rows: the saved routes as the server lists them (newest first), then the kept ones. */
export function loadRows(saved: readonly SavedSummary[], kept: readonly KeptRoute[]): LoadRow[] {
  return [
    ...saved.map((r): LoadRow => ({ kind: "saved", key: `s${r.id}`, name: r.name, detail: rowDetails(r), id: r.id })),
    ...kept.map((k): LoadRow => ({ kind: "kept", key: `k${k.id}`, name: k.title, detail: keptLine(k), kept: k })),
  ];
}

// ---- Open GPX file (the owner, 2026-10-22: "When opening gpx files, ask for ride type as well and if it should be
// identical or snap to road") ----------------------------------------------------------------------------------------

export const GPX_RIDE = t("Ride type");
export const GPX_HOW = t("Follow the file");
export const GPX_SNAP = t("Snap to roads");
export const GPX_SNAP_HINT = t("On streets and paths bikes may ride.");
export const GPX_EXACT = t("Exactly as drawn");
export const GPX_EXACT_HINT = t("Even where bikes may not ride, such as a closed parade route.");
export const GPX_CHOOSE = t("Choose file");
export const GPX_BACK = "Back";

/** What the rider chose before the file: its ride type, and whether it is followed exactly (core/follow.py EXACT). */
export interface GpxChoice {
  preset: PresetId;
  exact: boolean;
}

/** The ride types a file can be opened on: a file is one ride along its track, so not the transit ones. */
export function gpxRideTypes(): { id: PresetId; name: string }[] {
  return PRESETS.filter((p) => !isTransit(p.id)).map((p) => ({ id: p.id, name: presetSaid(p.id) }));
}

/** The ride type offered first: the page's own, or Default on a transit one. */
export function gpxStartRide(now: PresetId): PresetId {
  return isTransit(now) ? "default" : now;
}

/**
 * The opened file as the rider chose: on the ride type picked (the file's own sliders kept when it names the same
 * one), and followed exactly or not.
 */
export function withGpxChoice<P extends { preset: PresetId | null; dials?: unknown; exact?: boolean; notes?: readonly { kind: string }[] }>(plan: P, choice: GpxChoice): P {
  const same = plan.preset === choice.preset;
  // The file's own ride type no longer being offered says nothing once the rider picked one.
  const notes = plan.notes?.filter((n) => n.kind !== "preset-gone");
  return { ...plan, preset: choice.preset, dials: same ? plan.dials : undefined, exact: choice.exact, ...(notes ? { notes } : {}) };
}
