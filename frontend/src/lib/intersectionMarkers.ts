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
import type { JunctionWarning, RouteResponse } from "./api.ts";
import { formatDistance } from "./format.ts";

export type Severity = JunctionWarning["severity"];

/**
 * The two colours, as the stress map's tokens do: an orange and a red that stay
 * apart on a blue line. Never the colour alone (review r1): each has its own
 * shape (an orange triangle, a red octagon) and its own word in every list row
 * (`short`).
 */
export const SEVERITY_COLOURS: Record<Severity, { fill: string; stroke: string; label: string; short: string }> = {
  orange: { fill: "#f59e0b", stroke: "#7c4a03", label: "Higher stress", short: "Higher" },
  red: { fill: "#dc2626", stroke: "#7f1d1d", label: "Very high stress", short: "Very high" },
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
  /** The severity in a word, shown at the start of the list row: "Very high". */
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

/** The two shapes: a warning triangle for orange, an octagon for red. */
export const SEVERITY_SHAPES: Record<Severity, string> = {
  orange: "M12 2.5 22.5 20.5H1.5Z",
  red: "M8.1 1.5h7.8l5.6 5.6v7.8l-5.6 5.6H8.1l-5.6-5.6V7.1Z",
};

/**
 * The warning icon with an exclamation mark, as inline SVG markup for a map
 * marker's element: nothing is fetched, so the Content-Security-Policy is
 * unchanged. Orange is a triangle and red an octagon, so the two are told apart
 * without their colours (an orange and a red are the pair colour-blind riders
 * most often confuse); the dark outline keeps either apart from the blue route
 * line and the base map.
 */
export function warningIconSvg(severity: Severity, size = ICON_PX): string {
  const { fill, stroke } = SEVERITY_COLOURS[severity];
  const mark =
    severity === "red"
      ? `<rect x="11" y="5.5" width="2" height="8" rx="1" fill="#fff"/><circle cx="12" cy="16.6" r="1.3" fill="#fff"/>`
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
 */
export const GROUP_BELOW_ZOOM = 14;
export const GROUP_RADIUS_PX = 28;

export interface JunctionGroup {
  /** In route order; the first is where the group is drawn. */
  members: JunctionItem[];
  severity: Severity;
}

/**
 * The junctions as the map draws them at a zoom: one group each at or above
 * GROUP_BELOW_ZOOM, else each joined to the first group in route order whose
 * anchor is within `radiusPx` on screen (`project` gives a junction's screen
 * position).
 */
export function groupJunctions(
  items: readonly JunctionItem[],
  zoom: number,
  project: (item: JunctionItem) => { x: number; y: number },
  radiusPx = GROUP_RADIUS_PX,
): JunctionGroup[] {
  const groups: { at: { x: number; y: number }; members: JunctionItem[] }[] = [];
  for (const item of items) {
    const at = project(item);
    const near =
      zoom < GROUP_BELOW_ZOOM ? groups.find((g) => Math.hypot(g.at.x - at.x, g.at.y - at.y) <= radiusPx) : undefined;
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
