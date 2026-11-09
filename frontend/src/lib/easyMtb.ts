/**
 * "Easy MTB trails" (the owner, 2026-11-08), on Default and Trailmaxxing: the ride is planned on the off-road map as
 * Gravel's is, and steered off mountain-bike trails rated 2 or harder (core/easy_mtb.py). What the answer's
 * `easy_mtb` says it could not hold is said to the rider in one plain line: a harder trail it found no way round, or
 * the off-road map not being there, so the route kept to the usual trails (the twin fallback in core/routing.py).
 */
import type { RouteResponse } from "./api.ts";
import { formatDistance } from "./format.ts";
import { t } from "./i18n.ts";

/** Metres of harder trail below which nothing is said (core/easy_mtb.py TOLERANCE_M). */
export const EASY_MTB_SAY_FROM_M = 1;

export const EASY_MTB_HARDER = "This route uses {distance} of mountain-bike trail rated 2 or harder: no way round was found.";
export const EASY_MTB_HARDER_SHORT = "Uses a harder MTB trail.";
export const EASY_MTB_NO_MAP = "The off-road map isn't available, so this route keeps to the usual trails.";
export const EASY_MTB_NO_MAP_SHORT = "Off-road map unavailable: usual trails.";

/** The line for an Easy MTB trails route, and its short form for Plan's one-line notes; null where nothing is said. */
export function easyMtbNote(route: Pick<RouteResponse, "easy_mtb"> | null | undefined): { text: string; short: string } | null {
  const reading = route?.easy_mtb;
  if (!reading) return null;
  if (reading.limited === "no_offroad_graph") {
    return {
      text: t("The off-road map isn't available, so this route keeps to the usual trails."),
      short: t("Off-road map unavailable: usual trails."),
    };
  }
  const harder = reading.harder_m ?? 0;
  if (harder <= EASY_MTB_SAY_FROM_M) return null;
  return {
    text: t("This route uses {distance} of mountain-bike trail rated 2 or harder: no way round was found.", { distance: formatDistance(harder) }),
    short: t("Uses a harder MTB trail."),
  };
}
