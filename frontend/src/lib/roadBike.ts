/**
 * Road Bike's own maps (the paved-only graph, `Variant.PAVED`, and its weekend twin,
 * `Variant.PAVED_WEEKEND`): where a router is not running or its map not yet built, the API plans the
 * ride on the map it falls back to (core/routing.py, `twin_fallback`). A weekend ride falls back from
 * the weekend map to the paved-only one, where the car-free parkways are roads with cars again; the
 * paved-only map falls back to the standard map, where gravel is packed gravel and winding trails are
 * not held off. The answer's `variant` says which map answered; this says it to the rider (the
 * v0.18.0 release review; the owner, 2026-11-08, "New weekend graph"). A ride with "Keep to roads,
 * not trails" on rides the roads-only map by choice and is not told.
 */
import type { RouteResponse } from "./api.ts";
import { t } from "./i18n.ts";

// Said through t() in every catalog, as lib/easyMtb.ts's lines are, in plain words (hunt 3, 2026-11-08, R3-2: Go and
// the spoken summary gave them in English in every language, and "Weekend map down" is jargon). The English is the
// catalog key; the 45-character limit on the short lines is Claude's default, not measured.
export const ROAD_BIKE_NO_PAVED_MAP = "There is no road bike map right now, so this route may use gravel and trails.";

/** Plan shows note lines on one line; this is the one that fits, the whole line is behind it. */
export const ROAD_BIKE_NO_PAVED_MAP_SHORT = "No road bike map: may use gravel.";

export const ROAD_BIKE_NO_WEEKEND_MAP =
  "There is no weekend road bike map right now, so this route counts parkways like Beach Drive as roads with cars.";

export const ROAD_BIKE_NO_WEEKEND_MAP_SHORT = "No weekend map: parkways may have cars.";

type Routed = Pick<RouteResponse, "preset" | "variant"> & { dials?: Pick<NonNullable<RouteResponse["dials"]>, "when"> };

/** The warning for a Road Bike route a fallback map answered, with its one-line form, or null. */
export function roadBikeNotice(route: Routed | null | undefined): { text: string; short: string } | null {
  if (!route || route.preset !== "road-bike") return null;
  if (route.variant === "standard") {
    return {
      text: t("There is no road bike map right now, so this route may use gravel and trails."),
      short: t("No road bike map: may use gravel."),
    };
  }
  if (route.variant === "paved" && route.dials?.when === "weekend") {
    return {
      text: t("There is no weekend road bike map right now, so this route counts parkways like Beach Drive as roads with cars."),
      short: t("No weekend map: parkways may have cars."),
    };
  }
  return null;
}

/** The warning for a Road Bike route a fallback map answered, or null. */
export function roadBikeNote(route: Routed | null | undefined): string | null {
  return roadBikeNotice(route)?.text ?? null;
}
