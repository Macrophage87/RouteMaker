/**
 * The route's stressful junctions as the planner shows them (OWNER-DECISIONS
 * item 172): "put markers on intersections in a route, such as an orange marker
 * for higher stress intersections and a red one for very high stress
 * intersections. That way people know where to watch out or reroute." Every
 * ride type gets them; on a Mass Ride (item 138) the colour is the busy road's
 * own LTS, orange for 3 and red for 4 or Avoid. The API decides which junctions
 * and why (src/routemaker/intersections.py); this is how they are listed,
 * worded and drawn, kept out of the components so it is tested without a DOM.
 */
import type { JunctionGroupSummary, JunctionWarning, ProfileCrossing, RatedJunction, RatedMove, RouteResponse } from "./api.ts";
import { currentPalette, relativeLuminance } from "../stressStyle.js";
import { ratedDotFill, ratedLevelText } from "./ratedDot.ts";
import { FEET_PER_MILE, KM_PER_MILE, both, formatDistance } from "./format.ts";
import { t } from "./i18n.ts";
import { corkersFor } from "./profileChart.ts";

export type Severity = JunctionWarning["severity"];

/**
 * The two colours, as the stress map's tokens do: an orange and a red that stay
 * apart on a blue line. Never the colour alone (review r1): each has its own
 * shape (an orange triangle, a red diamond) and its own word in every list row
 * (`short`).
 */
export const SEVERITY_COLOURS: Record<Severity, { fill: string; stroke: string; label: string; short: string }> = {
  // `short` is the list row's word, and says "stress" as the marker and the card
  // do: "Higher" alone was ambiguous to a screen-reader user (a11y review, int-2).
  orange: { fill: "#f59e0b", stroke: "#7c4a03", label: t("Higher stress"), short: t("Higher stress") },
  red: { fill: "#dc2626", stroke: "#7f1d1d", label: t("Very high stress"), short: t("Very high stress") },
};

/** The icon is this many CSS pixels on a side. */
export const ICON_PX = 24;

/** The most junctions drawn on the map: a long route may have hundreds, and the list still has them all. */
export const MAX_ON_MAP = 150;

/**
 * A junction's own cost in calm miles, km in brackets: "0.62 calm mi (1.00 calm km)"
 * (OWNER-DECISIONS 467: "Scale these numbers to miles, even of a fraction"; 469b(5):
 * the junction's own cost over 5,280 ft, without the ride type's intersection weight).
 * The API's figures where it gives them, else the same sum from `cost_ft`.
 */
export function junctionCalmText(junction: Pick<JunctionWarning, "cost_ft" | "calm_mi" | "calm_km">): string {
  const mi = typeof junction.calm_mi === "number" ? junction.calm_mi : junction.cost_ft / FEET_PER_MILE;
  const km = typeof junction.calm_km === "number" ? junction.calm_km : mi * KM_PER_MILE;
  return both(`${mi.toFixed(2)} calm mi`, `${km.toFixed(2)} calm km`);
}

/**
 * How the ride time moved a junction's cost, in words (468a: "shown in the panel/chart in
 * words ("rush hour")"). Only what the API says moved it: no band, no words. Never a
 * factor: night is about half in town and a little less outside it once the map data
 * says which roads are in town (469d, 469e), and a little less everywhere before then,
 * so the words say only "less" and that traffic is usually calmer (469d).
 */
export const TIME_BAND_WORDS: Record<NonNullable<JunctionWarning["time_band"]>, string> = {
  weekday_rush: "more at rush hour",
  weekend: "a little less at the weekend",
  night: "less at night, when traffic is usually calmer",
};

/** "Costs 0.62 calm mi (1.00 calm km), more at rush hour": the row's and the card's cost line. */
export function junctionCostText(junction: Pick<JunctionWarning, "cost_ft" | "calm_mi" | "calm_km" | "time_band">): string {
  const band = junction.time_band ? TIME_BAND_WORDS[junction.time_band] : undefined;
  return `Costs ${junctionCalmText(junction)}${band ? `, ${band}` : ""}`;
}

export interface JunctionItem extends JunctionWarning {
  /** Position in the route's list, which a click on the list names the marker by. */
  index: number;
  /** "At 3.2 mi (5.1 km)". */
  where: string;
  /** What a screen reader hears for the marker. */
  label: string;
  /** The severity in words, shown at the start of the list row: "Very high stress". */
  severityText: string;
  /**
   * "Costs 0.62 calm mi (1.00 calm km), more at rush hour" (467, 468a); on a Mass Ride, what the group needs there
   * instead, "Cork this junction: 2 corkers" (the 2026-10-28 audit, P6), or "" where the profile does not say.
   */
  costText: string;
}

/** How near a Mass Ride's major junction (its profile's crossing) is to the junction it is: the profile's sample spacing. */
const CROSSING_MATCH_M = 30;

/**
 * A Mass Ride's line for a junction (the 2026-10-28 audit, P6: a group corks it, so a single rider's calm-mile cost
 * says nothing): its corkers from the profile's major junction at the same place (lib/profileChart.ts corkersFor),
 * "Cork this junction: 2 corkers", or "No corkers needed here"; "" where the profile has none there.
 */
export function junctionCorkText(crossings: readonly ProfileCrossing[] | null | undefined, m: number): string {
  let best: ProfileCrossing | null = null;
  for (const c of crossings ?? []) if (Math.abs(c.m - m) <= CROSSING_MATCH_M && (!best || Math.abs(c.m - m) < Math.abs(best.m - m))) best = c;
  if (!best) return "";
  if (!best.corkers_needed) return t("No corkers needed here");
  const count = corkersFor(best);
  return count === 1 ? t("Cork this junction: 1 corker") : t("Cork this junction: {count} corkers", { count });
}

/** The route's junctions, in route order, worded; empty when the API had none to say or is older. */
export function junctionItems(route: (Pick<RouteResponse, "intersections"> & Partial<Pick<RouteResponse, "preset" | "profile">>) | null): JunctionItem[] {
  const list = route?.intersections;
  if (!list) return [];
  const mass = route?.preset === "mass-ride";
  return list.map((junction, index) => ({
    ...junction,
    index,
    where: `At ${formatDistance(junction.m)}`,
    label: `${junction.rated ? ratedTitle(junction.rated) : SEVERITY_COLOURS[junction.severity].label}: ${junction.reason}`,
    severityText: junction.rated ? ratedTitle(junction.rated) : SEVERITY_COLOURS[junction.severity].short,
    costText: mass ? junctionCorkText(route?.profile?.crossings, junction.m) : junctionCostText(junction),
  }));
}

/**
 * A Mass Ride's group of signalized crossings as one row of the list
 * (OWNER-DECISIONS 233, 234): the API's own phrase for it, its worst severity in
 * words, and its members, each of which is still a junction of its own on the map.
 */
export interface JunctionGroupItem {
  number: number;
  severity: Severity;
  severityText: string;
  /** The API's phrase: span, how many, the first streets, how many are LTS 4. */
  text: string;
  count: number;
  members: JunctionItem[];
}

/** A row of the junction list: one junction, or a group that opens onto its junctions. */
export type JunctionRow = { kind: "item"; item: JunctionItem } | { kind: "group"; group: JunctionGroupItem };

function groupItem(summary: JunctionGroupSummary, items: readonly JunctionItem[]): JunctionGroupItem | null {
  if (typeof summary.text !== "string" || summary.text.trim() === "" || !Array.isArray(summary.members)) return null;
  const members = summary.members.map((i) => items[i]);
  // Only a group the list can show whole: every member found, in order, and its own.
  if (members.length < 2 || members.some((m) => m === undefined || m.group !== summary.group)) return null;
  const severity: Severity = members.some((m) => m.severity === "red") ? "red" : "orange";
  return {
    number: summary.group,
    severity,
    severityText: SEVERITY_COLOURS[severity].short,
    text: summary.text.trim(),
    count: members.length,
    members,
  };
}

/**
 * The junction list's rows, in route order: each junction, except that the
 * junctions of one of the API's groups are one row at the first of them (the
 * group opens onto its members). Where the API has no groups, or one that does
 * not hold together, every junction is a row of its own, as before.
 */
export function junctionRows(route: Pick<RouteResponse, "intersections" | "intersection_groups"> | null): JunctionRow[] {
  const items = junctionItems(route);
  const groups = new Map<number, JunctionGroupItem>();
  for (const summary of route?.intersection_groups ?? []) {
    const group = groupItem(summary, items);
    if (group) groups.set(group.number, group);
  }
  const rows: JunctionRow[] = [];
  const said = new Set<number>();
  for (const item of items) {
    const group = item.group == null ? undefined : groups.get(item.group);
    if (!group) {
      rows.push({ kind: "item", item });
    } else if (!said.has(group.number)) {
      said.add(group.number);
      rows.push({ kind: "group", group });
    }
  }
  return rows;
}

export interface JunctionCounts {
  orange: number;
  red: number;
  total: number;
}

export function junctionCounts(items: readonly Pick<JunctionWarning, "severity">[]): JunctionCounts {
  const red = items.filter((i) => i.severity === "red").length;
  return { orange: items.length - red, red, total: items.length };
}

/** The list's heading: how many of each colour, red first. */
export function junctionHeadline(counts: JunctionCounts): string {
  if (counts.total === 0) return "No stressful junctions on this route";
  const parts: string[] = [];
  if (counts.red > 0) parts.push(`${counts.red} very high stress (red)`);
  if (counts.orange > 0) parts.push(`${counts.orange} higher stress (orange)`);
  return `Watch for ${parts.join(" and ")} ${counts.total === 1 ? "junction" : "junctions"}`;
}

/** What the list says beside it: how to get away from one. */
export const JUNCTION_HINT =
  "Drag the route away from a marker to plan around the junction. A stop sign on a quiet street is never marked.";

/**
 * The two shapes: a warning triangle for orange, a diamond (the road-warning
 * shape) for red. Red was an octagon until the owner: "It looks too much like an
 * ordinary stop sign" ... "Or something else, a diamond perhaps?" (OWNER-DECISIONS 311).
 */
export const SEVERITY_SHAPES: Record<Severity, string> = {
  orange: "M12 2.5 22.5 20.5H1.5Z",
  red: "M12 1.5 22.5 12 12 22.5 1.5 12Z",
};

/**
 * The warning icon with an exclamation mark, as inline SVG markup for a map
 * marker's element: nothing is fetched, so the Content-Security-Policy is
 * unchanged. Orange is a triangle and red a diamond, so the two are told apart
 * without their colours (an orange and a red are the pair colour-blind riders
 * most often confuse); the dark outline keeps either apart from the blue route
 * line and the base map.
 */
export function warningIconSvg(severity: Severity, size = ICON_PX): string {
  const { fill, stroke } = SEVERITY_COLOURS[severity];
  const mark =
    severity === "red"
      ? `<rect x="11" y="7" width="2" height="7" rx="1" fill="#fff"/><circle cx="12" cy="16.6" r="1.3" fill="#fff"/>`
      : `<rect x="11" y="8.5" width="2" height="6" rx="1" fill="${stroke}"/><circle cx="12" cy="17" r="1.2" fill="${stroke}"/>`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">` +
    `<path d="${SEVERITY_SHAPES[severity]}" fill="${fill}" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round"/>` +
    mark +
    "</svg>"
  );
}

/**
 * The route's junction markers are drawn from this zoom up, each its own marker, and none below it (the owner,
 * 2026-11-22: "Any level that would show an intersection marker should show the one taken ... If you zoom out past
 * the point where you'd see the arrows, then just omit junction markers"). Markers merged into one showed the hardest
 * of them, "way too much alarm" where a junction is fine for the movement the route makes. 14 is where markers
 * stopped being merged (review r1: three to five triangles overlapped at one interchange zoomed out); the list keeps
 * every junction at every zoom. Where two still overlap, the focused or hovered one is drawn on top (styles.css).
 */
export const MARKERS_FROM_ZOOM = 14;
/** The map's last zoom (MapView.tsx maxZoom). */
export const MAP_MAX_ZOOM = 18;

export interface JunctionGroup {
  /** The one junction the marker is drawn for. */
  members: JunctionItem[];
  severity: Severity;
}

/** The markers the map draws at a zoom: one for each junction from MARKERS_FROM_ZOOM up, none below it. */
export function groupJunctions(items: readonly JunctionItem[], zoom: number): JunctionGroup[] {
  if (zoom < MARKERS_FROM_ZOOM) return [];
  return items.map((item) => ({ members: [item], severity: item.severity }));
}

/** The junctions to draw: all of them up to MAX_ON_MAP, the worst kept past it. */
export function junctionsOnMap(items: readonly JunctionItem[]): JunctionItem[] {
  if (items.length <= MAX_ON_MAP) return [...items];
  const worst = [...items].sort((a, b) => b.cost_ft - a.cost_ft).slice(0, MAX_ON_MAP);
  return worst.sort((a, b) => a.index - b.index);
}

/**
 * A row's name as one string: "Very high stress, At 1.2 mi (2.0 km): ..." and, on
 * a junction's row, its cost after (". Costs 0.62 calm mi (1.00 calm km)"). Each
 * span of a row is a grid item, so a name computed from the spans puts a space
 * before every comma and colon ("Very high stress , At 1.2 mi (2.0 km) : ..."; a11y
 * re-check of 2b0cf00). The visible words still begin the name (2.5.3).
 */
export function rowName(severity: string, where: string, reason: string, cost?: string): string {
  return `${severity}, ${where}: ${reason}${cost ? `. ${cost}` : ""}`;
}

// --- Rated junctions: a dot in the stress colour (the owner, 2026-11-15) ---------------

export { ratedDotFill, ratedLevelText };

/** The dot, as inline SVG markup: a white-ringed, dark-edged small disc in the level's colour, nothing written
 * on it (the owner, 2026-11-20: "Just colors as small dots"). */
export function ratedDotSvg(level: number, size = ICON_PX, palette: string = currentPalette()): string {
  const fill = ratedDotFill(level, palette);
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">` +
    `<circle cx="12" cy="12" r="6.6" fill="#ffffff" stroke="#111111" stroke-width="1.2"/>` +
    `<circle cx="12" cy="12" r="4.8" fill="${fill}"/>` +
    "</svg>"
  );
}

export type Movement = JunctionWarning["movement"];

/** A turn arrow on the marker's disc, for a left (a right is its mirror): up the middle, then off to the side. */
const TURN_ARROW = `<path d="M14.5 17.5 V11.5 H10" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M10.8 7.6 L6.4 11.5 L10.8 15.4 Z"/>`;

/**
 * The movement the route makes at a junction, as its marker (the owner, 2026-11-22: "show the movement done at each
 * intersection colored by the movement when LtS >=3. Dots for riding through"): a dot for straight through, a turn
 * arrow for a left or a right, in that movement's stress colour where `level` is 3 or more. Below that, or with no
 * level, it is drawn without a stress colour: white with dark ink.
 */
export function movementIconSvg(movement: Movement, level: number | null, size = ICON_PX, palette: string = currentPalette()): string {
  const coloured = level !== null && level >= 3;
  const open = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">`;
  if (movement === "straight") {
    if (coloured) return ratedDotSvg(level, size, palette);
    return `${open}<circle cx="12" cy="12" r="6.6" fill="#ffffff" stroke="#111111" stroke-width="1.2"/><circle cx="12" cy="12" r="2.4" fill="#111111"/></svg>`;
  }
  const fill = coloured ? ratedDotFill(level, palette) : "#ffffff";
  const l = relativeLuminance(fill);
  // Near-black on a light colour, white on a dark one (the higher contrast of the two).
  const ink = (l + 0.05) / 0.056 >= 1.05 / (l + 0.05) ? "#111111" : "#ffffff";
  const flip = movement === "right" ? ` transform="matrix(-1 0 0 1 24 0)"` : "";
  return (
    `${open}<circle cx="12" cy="12" r="9.4" fill="#ffffff" stroke="#111111" stroke-width="1.2"/>` +
    `<circle cx="12" cy="12" r="7.8" fill="${fill}"/>` +
    `<g fill="${ink}" stroke="${ink}"${flip}>${TURN_ARROW}</g></svg>`
  );
}

/** A junction's icon: where the raters set its cost, the movement the route makes there in its level's colour
 * (`movementIconSvg`), else the warning shape. */
export function junctionIconSvg(junction: Pick<JunctionWarning, "severity" | "rated" | "movement">, size = ICON_PX): string {
  return junction.rated ? movementIconSvg(junction.movement, junction.rated.level, size) : warningIconSvg(junction.severity, size);
}

const RATED_MOVE_WORDS: Record<RatedMove["move"], string> = {
  cross: "Crossing",
  left: "Turning left",
  along: "Riding along",
};

/** "about 40 s": a rated wait, to the nearest 5 seconds from 10 up; "" where none is given or it is nothing. */
export function ratedWaitText(wait_s: number | null | undefined): string {
  if (typeof wait_s !== "number" || wait_s < 1) return "";
  return `about ${wait_s >= 10 ? Math.round(wait_s / 5) * 5 : Math.round(wait_s)} s`;
}

export interface RatedLine {
  /** "Crossing: LTS 4, about 40 s". */
  text: string;
  /** The movement this route makes. */
  yours: boolean;
}

/** The junction panel's lines, one for each movement that can be made there, in the raters' order. */
export function ratedLines(rated: Pick<RatedJunction, "moves"> & { move?: RatedJunction["move"] }): RatedLine[] {
  return rated.moves.map((move) => {
    const wait = ratedWaitText(move.wait_s);
    return {
      text: `${RATED_MOVE_WORDS[move.move]}: ${ratedLevelText(move.level)}${wait ? `, ${wait}` : ""}`,
      yours: move.move === rated.move,
    };
  });
}

/** "Rated LTS 4 crossing": what a rated junction's marker and card are called. */
export function ratedTitle(rated: RatedJunction): string {
  const what = { cross: "crossing", left: "left turn", along: "junction to ride through" }[rated.move];
  return `Rated ${ratedLevelText(rated.level)} ${what}`;
}
