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
import type { JunctionGroupSummary, JunctionWarning, RouteResponse } from "./api.ts";
import { formatDistance } from "./format.ts";

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
  orange: { fill: "#f59e0b", stroke: "#7c4a03", label: "Higher stress", short: "Higher stress" },
  red: { fill: "#dc2626", stroke: "#7f1d1d", label: "Very high stress", short: "Very high stress" },
};

/** The icon is this many CSS pixels on a side. */
export const ICON_PX = 24;

/** The most junctions drawn on the map: a long route may have hundreds, and the list still has them all. */
export const MAX_ON_MAP = 150;

export interface JunctionItem extends JunctionWarning {
  /** Position in the route's list, which a click on the list names the marker by. */
  index: number;
  /** "At 3.2 mi (5.1 km)". */
  where: string;
  /** What a screen reader hears for the marker. */
  label: string;
  /** The severity in words, shown at the start of the list row: "Very high stress". */
  severityText: string;
}

/** The route's junctions, in route order, worded; empty when the API had none to say or is older. */
export function junctionItems(route: Pick<RouteResponse, "intersections"> | null): JunctionItem[] {
  const list = route?.intersections;
  if (!list) return [];
  return list.map((junction, index) => ({
    ...junction,
    index,
    where: `At ${formatDistance(junction.m)}`,
    label: `${SEVERITY_COLOURS[junction.severity].label}: ${junction.reason}`,
    severityText: SEVERITY_COLOURS[junction.severity].short,
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
 * Below this zoom, markers closer than GROUP_RADIUS_PX on screen are drawn as
 * one (review r1: three to five triangles overlapped at one interchange on a
 * zoomed-out calm route). A group shows the worst severity's shape and how many
 * junctions it holds, and a click on it zooms in until they come apart.
 *
 * At and above it, markers that would overlap (centres closer than an icon,
 * OVERLAP_RADIUS_PX) are still one group (a11y review, int-2: two reds 10 m
 * apart sat 2 px apart at zoom 14 and up), except at the map's last zoom, where
 * zooming in cannot part them: there each is its own marker, and the focused
 * one is drawn on top (styles.css).
 */
export const GROUP_BELOW_ZOOM = 14;
export const GROUP_RADIUS_PX = 28;
export const OVERLAP_RADIUS_PX = ICON_PX;
/** The map's last zoom (MapView.tsx maxZoom). */
export const MAP_MAX_ZOOM = 18;

export interface JunctionGroup {
  /** In route order; the first is where the group is drawn. */
  members: JunctionItem[];
  severity: Severity;
}

/** How near on screen two junctions are drawn as one at `zoom`; 0 at the map's last zoom. */
export function groupRadius(zoom: number, maxZoom = MAP_MAX_ZOOM): number {
  if (zoom >= maxZoom) return 0;
  return zoom < GROUP_BELOW_ZOOM ? GROUP_RADIUS_PX : OVERLAP_RADIUS_PX;
}

/**
 * The junctions as the map draws them at a zoom: each joined to the first
 * group in route order whose anchor is within the radius on screen (`project`
 * gives a junction's screen position; the radius is groupRadius's unless
 * given), or a group of its own.
 */
export function groupJunctions(
  items: readonly JunctionItem[],
  zoom: number,
  project: (item: JunctionItem) => { x: number; y: number },
  radiusPx?: number,
  maxZoom = MAP_MAX_ZOOM,
): JunctionGroup[] {
  const radius = zoom >= maxZoom ? 0 : (radiusPx ?? groupRadius(zoom, maxZoom));
  const groups: { at: { x: number; y: number }; members: JunctionItem[] }[] = [];
  for (const item of items) {
    const at = project(item);
    const near = radius > 0 ? groups.find((g) => Math.hypot(g.at.x - at.x, g.at.y - at.y) <= radius) : undefined;
    if (near) near.members.push(item);
    else groups.push({ at, members: [item] });
  }
  return groups.map(({ members }) => ({
    members,
    severity: members.some((m) => m.severity === "red") ? "red" : "orange",
  }));
}

/** What a screen reader hears for a group's marker. */
export function groupLabel(group: JunctionGroup): string {
  const red = group.members.filter((m) => m.severity === "red").length;
  const parts = [`${group.members.length} stressful junctions here`];
  if (red > 0) parts.push(`${red} very high stress`);
  return `${parts.join(", ")}: zoom in to see them`;
}

/** The junctions to draw: all of them up to MAX_ON_MAP, the worst kept past it. */
export function junctionsOnMap(items: readonly JunctionItem[]): JunctionItem[] {
  if (items.length <= MAX_ON_MAP) return [...items];
  const worst = [...items].sort((a, b) => b.cost_ft - a.cost_ft).slice(0, MAX_ON_MAP);
  return worst.sort((a, b) => a.index - b.index);
}

/**
 * A row's name as one string: "Very high stress, At 1.2 mi (2.0 km): ...". Each
 * span of a row is a grid item, so a name computed from the spans puts a space
 * before every comma and colon ("Very high stress , At 1.2 mi (2.0 km) : ..."; a11y
 * re-check of 2b0cf00). The visible words still begin the name (2.5.3).
 */
export function rowName(severity: string, where: string, reason: string): string {
  return `${severity}, ${where}: ${reason}`;
}
