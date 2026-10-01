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

/** The two colours, as the stress map's tokens do: an orange and a red that stay apart on a blue line. */
export const SEVERITY_COLOURS: Record<Severity, { fill: string; stroke: string; label: string }> = {
  orange: { fill: "#f59e0b", stroke: "#7c4a03", label: "Higher stress" },
  red: { fill: "#dc2626", stroke: "#7f1d1d", label: "Very high stress" },
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

/**
 * A warning triangle with an exclamation mark, as inline SVG markup for a map
 * marker's element: nothing is fetched, so the Content-Security-Policy is
 * unchanged. The same icon for both colours; only the fill differs, and the
 * dark outline keeps either apart from the blue route line and the base map.
 */
export function warningIconSvg(severity: Severity, size = ICON_PX): string {
  const { fill, stroke } = SEVERITY_COLOURS[severity];
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">` +
    `<path d="M12 2.5 22.5 20.5H1.5Z" fill="${fill}" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round"/>` +
    `<rect x="11" y="8.5" width="2" height="6" rx="1" fill="${stroke}"/>` +
    `<circle cx="12" cy="17" r="1.2" fill="${stroke}"/>` +
    "</svg>"
  );
}

/** The junctions to draw: all of them up to MAX_ON_MAP, the worst kept past it. */
export function junctionsOnMap(items: readonly JunctionItem[]): JunctionItem[] {
  if (items.length <= MAX_ON_MAP) return [...items];
  const worst = [...items].sort((a, b) => b.cost_ft - a.cost_ft).slice(0, MAX_ON_MAP);
  return worst.sort((a, b) => a.index - b.index);
}
