/**
 * Ride's "Done with MTB" (the owner, 2026-11-08: "On MTB trails ... make a button under the trail closure for 'i don't
 * want to mountain bike anymore', but make it concise. Basically that will route you off mtb trails and onto something
 * easier").
 *
 * One press, under Go round, while the route still has a mountain-bike trail ahead (`trail_levels`). The ride is
 * planned again from the rider, and every re-plan after it sends `mtb_done`: the API plans on the standard graph
 * (where the mountain-bike trails are closed), with Easy MTB trails off and no dirt trail ridden (core/presets.py
 * variant_for_ride). Kept with the ride for a Resume (lib/rideResume.ts). Not undone: the rider who wants the trails
 * back plans a new ride.
 *
 * Pure, so it is tested without a map or a DOM.
 */
import type { RouteResponse } from "./api.ts";
import { t } from "./i18n.ts";

/** Its shown words, short for the 20 languages Ride is in. */
export const MTB_DONE_TEXT = t("Done with MTB");
/** Its name for screen readers and its tooltip: the shown words first (WCAG 2.5.3), then what it does. */
export const MTB_DONE_NAME = t("Done with MTB: route off mountain-bike trails");
/** Said on the press, while the easier way is looked for. */
export const MTB_DONE_FINDING = t("Finding a way off the mountain-bike trails.");
/** Said where the ride has no fix yet to plan from: the button stays, to press again. */
export const MTB_DONE_NO_PLACE = t("Not sure where you are yet. Try again once moving.");

/**
 * Whether the button shows: a mountain-bike trail on the route at or past `progressM` (metres along the route, as the
 * ride's ribbon reads `trail_levels`). Off the route (`progressM` null), any trail on it counts.
 */
export function mtbTrailAhead(route: Pick<RouteResponse, "trail_levels"> | null | undefined, progressM: number | null): boolean {
  const spans = route?.trail_levels ?? [];
  if (!spans.length) return false;
  if (progressM === null || !Number.isFinite(progressM)) return true;
  return spans.some((span) => span.to_m > progressM);
}
