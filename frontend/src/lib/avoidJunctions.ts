/**
 * Avoid-rated junctions as the planner shows them (FOLLOWUP-ISECT-AVOID,
 * OWNER-DECISIONS 307-310, 335). Rated by a person, never by the model, and rare:
 * the list ships empty. The API decides which the route passes and what to say
 * (src/routemaker/avoid_junctions.py); this is how they are drawn, listed and
 * offered, kept out of the components so it is tested without a DOM.
 *
 * - The marker is the Noto Emoji skull and crossbones (U+2620, Apache 2.0, 310) on
 *   a dark disc with a white ring, a shape of its own beside the orange triangle
 *   and the red diamond, so colour is never the only cue.
 * - Its accessible name is "Avoid-rated junction" and the reason (309), never
 *   "skull and crossbones": the glyph and the text symbol are hidden from
 *   assistive technology wherever they are drawn.
 * - The notice leads the route panel and is announced first (335), with the way
 *   round offered beside it.
 * - The owner, 2026-10-10 15:08 UTC: "Yes, also when clicking on the intersection. Make it
 *   larger than a normal icon. Basically something to say: this is a really bad idea, please
 *   reconsider." So the marker is larger than the junction markers, every mention ends with
 *   AVOID_PLEA, and the road panel opened on one (a click on the marker, a right-click, a long
 *   press, the I key or "Road info at map center") leads with a warning (avoidCard).
 * - The owner, 2026-10-10 15:03 UTC: "For avoid markers in intersection. No need to put it in
 *   legend. You'll only see this if you really try to force things." So no legend row.
 */
import type { AvoidJunctionPass, RouteResponse } from "./api.ts";
import { candidateRoute } from "./candidates.ts";
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

/** The text surfaces' symbol (310), always drawn with aria-hidden. */
export const AVOID_SYMBOL = "☠";
/** What every assistive technology hears in its place (309). */
export const AVOID_NOUN = "Avoid-rated junction";

/**
 * What every mention says after the name and the reason (the owner, 2026-10-10: "this is a
 * really bad idea, please reconsider"). The API's notice and description end with the same
 * words (src/routemaker/avoid_junctions.py PLEA; a test holds them equal).
 */
export const AVOID_PLEA = "Riding through it is a really bad idea. Please reconsider your route.";

/**
 * The marker is this many CSS pixels on a side: larger than the junction markers' 24
 * (intersectionMarkers ICON_PX; the owner, 2026-10-10: "Make it larger than a normal icon").
 * The markers keep their size at every zoom, so it reads wherever it shows.
 */
export const AVOID_ICON_PX = 40;
/** The disc and its ring: dark under the pale glyph, white against a dark map. */
export const AVOID_DISC = { fill: "#1f2937", ring: "#ffffff" } as const;

export interface AvoidItem extends AvoidJunctionPass {
  /** "At 0.7 mi (1.1 km)". */
  where: string;
}

/** The Avoid-rated junctions a route passes, in route order; empty where none (nearly always) or from an older API. */
export function avoidItems(route: Pick<RouteResponse, "avoid_junctions"> | null): AvoidItem[] {
  const list = route?.avoid_junctions;
  if (!Array.isArray(list)) return [];
  return list.map((pass) => ({ ...pass, where: `At ${formatDistance(pass.m)}` }));
}

/** A list row's name: "Avoid-rated junction: <name>, <reason>, at 0.7 mi (1.1 km). Riding through it ...". */
export function avoidRowName(item: AvoidItem): string {
  return `${item.label}, ${item.where.toLowerCase()}. ${AVOID_PLEA}`;
}

/** The map marker's accessible name: "Avoid-rated junction: <name>, <reason>. Riding through it ...". */
export function avoidMarkerName(item: Pick<AvoidJunctionPass, "label">): string {
  return `${item.label}. ${AVOID_PLEA}`;
}

/**
 * How near the spot the road panel was opened on a junction must be for the panel to
 * warn of it, in metres (82 ft): a little more than the planner's own match
 * (MATCH_RADIUS_M, 49 ft (15 m)), since a finger or the map's centre is rarely right on
 * the point, and short of the next junction on most blocks.
 */
export const AVOID_SPOT_M = 25;

/** The Avoid-rated junction on the route nearest `point`, within AVOID_SPOT_M; null where none. */
export function avoidNearSpot(
  route: Pick<RouteResponse, "avoid_junctions"> | null,
  point: LonLat,
  within = AVOID_SPOT_M,
): AvoidItem | null {
  let best: AvoidItem | null = null;
  let bestM = within;
  for (const item of avoidItems(route)) {
    const m = haversineM([item.lon, item.lat], point);
    if (m <= bestM) {
      best = item;
      bestM = m;
    }
  }
  return best;
}

/** The road panel's warning heading, on an Avoid-rated junction. */
export const AVOID_CARD_HEADING = "Avoid this intersection";

/**
 * The road panel's warning, plain and direct (the owner, 2026-10-10, with the coordinator's
 * example: "Avoid this intersection. It's rated as dangerous for bikes. Please reconsider your
 * route."): the junction, the stored reason where there is one, and the plea.
 */
export function avoidCardText(item: Pick<AvoidJunctionPass, "name" | "reason">): string {
  const name = item.name?.trim() ? `${item.name.trim()} is` : "It is";
  const reason = item.reason?.trim() ? `: ${item.reason.trim()}` : "";
  return `${name} rated as dangerous for bikes${reason}. ${AVOID_PLEA}`;
}

/** The whole warning as one sentence for the panel's announcement. */
export function avoidCardSaid(item: Pick<AvoidJunctionPass, "name" | "reason">): string {
  return `${AVOID_CARD_HEADING}. ${avoidCardText(item)}`;
}

/**
 * The way round, as the notice offers it (335: "the best route that avoids it, even if
 * much longer"): "Show the route that avoids it: 3.7 mi (6.0 km), 2.4 mi (3.8 km) longer".
 * Null where the plan found none.
 */
export function avoidOffer(answer: Pick<RouteResponse, "avoid_alternate"> | null): string | null {
  const around = answer?.avoid_alternate;
  if (!around) return null;
  const extra = around.extra_distance_m;
  const longer = extra >= 80 ? `, ${formatDistance(extra)} longer` : "";
  return `Show the route that avoids it: ${formatDistance(around.distance_m)}${longer}`;
}

/**
 * The notice for the route the rider has chosen (the answer, or one of the routes to
 * choose from): its own `avoid_notice`, so a candidate that avoids the junction has none
 * and one that passes it has its own. The way round (`avoid_alternate`) is the answer's,
 * so it is offered only while the answer is chosen. Null where the route passes none.
 */
export function avoidNoticeFor(
  answer: RouteResponse | null,
  choice: number,
): { notice: string; offer: string | null; none: string | null } | null {
  const planned = candidateRoute(answer, choice);
  const notice = planned?.avoid_notice;
  if (!answer || !notice) return null;
  const own = planned === answer;
  return { notice, offer: own ? avoidOffer(answer) : null, none: own ? avoidNoAlternate(answer) : null };
}

/**
 * The route to show: the way round in place of the planned route while it is asked for
 * and the answer is chosen, else the route chosen.
 */
export function shownRoute(answer: RouteResponse | null, choice: number, around: boolean): RouteResponse | null {
  const planned = candidateRoute(answer, choice);
  const way = answer?.avoid_alternate;
  return around && way && planned === answer ? way : planned;
}

/** What the notice says while the way round is shown in place of the planned route. */
export const AVOID_SHOWING_AROUND =
  "Showing the route that avoids the Avoid-rated junction. The planned route goes through it.";
export const AVOID_BACK = "Show the planned route";

/** Why there is no way round to offer, where the plan says. */
export function avoidNoAlternate(answer: Pick<RouteResponse, "avoid_search"> | null): string | null {
  const search = answer?.avoid_search;
  if (!search || search.decision !== "kept") return null;
  if (search.alternate === "no_route") return "No route round it was found.";
  if (search.alternate === "time") return "There was no time left to look for a route round it.";
  return null;
}

/**
 * The glyph's own SVG, ready to nest inside the marker: its XML declaration and
 * comments dropped, its document id and position dropped (several markers share a
 * page), and the size and place in the marker set. Nothing else in the file is
 * touched: it was checked to hold only shapes and fills (fixtures/icons/README.md).
 */
export function nestedGlyph(raw: string, x: number, y: number, size: number): string {
  const body = raw
    .replace(/<\?xml[^>]*\?>/g, "")
    .replace(/<!--[\s\S]*?-->/g, "")
    .trim();
  return body.replace(/<svg\b[^>]*>/, (open) => {
    const viewBox = /viewBox="([^"]+)"/.exec(open)?.[1] ?? "0 0 128 128";
    return `<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="${viewBox}" aria-hidden="true" focusable="false">`;
  });
}

/**
 * The marker: the skull on a dark disc ringed in white (the halo of 310, for 3:1
 * against any map), as inline SVG markup. Nothing is fetched, so the
 * Content-Security-Policy is unchanged.
 */
export function avoidIconSvg(glyphRaw: string, size = AVOID_ICON_PX): string {
  const inset = 4;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">` +
    `<circle cx="12" cy="12" r="11" fill="${AVOID_DISC.fill}" stroke="${AVOID_DISC.ring}" stroke-width="1.6"/>` +
    nestedGlyph(glyphRaw, inset, inset, 24 - 2 * inset) +
    "</svg>"
  );
}
