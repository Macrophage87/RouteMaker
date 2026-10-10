/**
 * The panel's Federal land section, shown only for a Mass Ride: the switch, the
 * status of the data, the legend and the standing note. Written with
 * createElement so a test renders it (as pointsList.ts, stressLegend.ts).
 *
 * The legend draws each kind with the map's own pattern and outline dash and
 * names the pattern in words, so no kind is told apart by colour alone.
 */
import { createElement as h, type ReactElement } from "react";
import {
  FEDERAL_KINDS,
  FEDERAL_NOTE,
  FEDERAL_STYLE,
  PATTERN_SIZE,
  federalPatternPath,
  federalShown,
  type FederalKind,
  type FederalPoint,
} from "./federalLand.ts";
import type { PresetId } from "./presets.ts";

export type FederalStatus = "loading" | "ready" | "unavailable";

export const FEDERAL_HEADING = "Federal land";
/**
 * The help, in two short paragraphs, the ownership caveat on its own (the a11y
 * review's SF6). No promise of callouts to come, and no "above": the legend is
 * hidden while the switch is off.
 */
export const FEDERAL_HELP =
  "Shading marks federal land by kind. Press I on the map, or tap or click an area, for its name and " +
  "manager; the list under the switch names the areas your points are on.";
export const FEDERAL_OWNERSHIP =
  "Shading is where land is owned or kept by the federal government. Ownership is not police jurisdiction: in most " +
  "cases the roads are still city roads. It matters most for stopping, and for the parkways.";
/**
 * What the route's own warnings look like (item 239; lib/federalStops.ts): the badge on a marker
 * and in the points list, and the Directions' lines.
 */
export const FEDERAL_BADGE =
  "A point on federal land has a ! badge on its marker and in the points list. Directions names those stops " +
  "and any National Park Service parkway the route rides on.";
export const FEDERAL_UNAVAILABLE = "Federal land shading is unavailable for now. The map and your route are not affected.";
export const FEDERAL_LOADING = "Loading federal land…";

export function FederalSwatch({ kind }: { kind: FederalKind }): ReactElement {
  const style = FEDERAL_STYLE[kind];
  const id = `federal-swatch-${kind}`;
  const size = PATTERN_SIZE;
  return h(
    "svg",
    { width: 24, height: 16, "aria-hidden": "true", className: "federal-swatch" },
    h(
      "defs",
      null,
      h(
        "pattern",
        { id, width: size, height: size, patternUnits: "userSpaceOnUse" },
        h("path", { d: federalPatternPath(kind), fill: style.colour }),
      ),
    ),
    h("rect", { x: 1, y: 1, width: 22, height: 14, fill: style.colour, fillOpacity: 0.1 }),
    h("rect", { x: 1, y: 1, width: 22, height: 14, fill: `url(#${id})`, fillOpacity: 0.45 }),
    h("rect", {
      x: 1,
      y: 1,
      width: 22,
      height: 14,
      fill: "none",
      stroke: style.colour,
      strokeWidth: 1.25,
      strokeDasharray: style.dash.length ? style.dash.map((d) => d * 1.25).join(" ") : undefined,
    }),
  );
}

export function FederalLegend(): ReactElement {
  return h(
    "ul",
    { className: "legend federal-legend", "aria-label": "Federal land legend" },
    FEDERAL_KINDS.filter((kind) => kind !== "federal").map((kind) =>
      h(
        "li",
        { key: kind },
        h(FederalSwatch, { kind }),
        h(
          "span",
          { className: "stress-label" },
          h("strong", { className: "federal-kind" }, FEDERAL_STYLE[kind].label),
          `: ${FEDERAL_STYLE[kind].describe}, shaded with ${FEDERAL_STYLE[kind].cue}`,
        ),
      ),
    ),
  );
}

/** The heading of the list of the plan's points on federal land. */
export const FEDERAL_POINTS_HEADING = "Your points on federal land:";
export const FEDERAL_POINTS_NONE = "None of your points is on federal land.";

/** "Stop 2 – The Mall (National Park Service)"; "Stop 2 – next to The Mall (...)" within 20 m of its edge. */
export function federalPointText(point: FederalPoint, name: string): string {
  return `${name} – ${point.near ? "next to " : ""}${point.name} (${point.manager})`;
}

/**
 * The plan's points on federal land, in words (lib/federalLand.ts federalPoints):
 * read by a screen reader and a keyboard user without the map. Null until the
 * data has come, or with no points.
 */
export function FederalPointsList({
  found,
  count,
  nameOf,
  headingId = "federal-points-heading",
}: {
  found: FederalPoint[] | null;
  count: number;
  nameOf: (index: number) => string;
  /** The list's heading id: the planner's copy (App.tsx, Points) and the Map layers sheet's each have their own. */
  headingId?: string;
}): ReactElement | null {
  if (found === null || count === 0) return null;
  if (found.length === 0) return h("p", { className: "hint federal-points" }, FEDERAL_POINTS_NONE);
  return h(
    "div",
    { className: "federal-points" },
    h("p", { id: headingId }, FEDERAL_POINTS_HEADING),
    h(
      "ul",
      { "aria-labelledby": headingId },
      ...found.map((point) => h("li", { key: point.index }, federalPointText(point, nameOf(point.index)))),
    ),
  );
}

/** What the one status line says: loading or unavailable while the switch is on, else nothing. */
export function federalStatusText(on: boolean, status: FederalStatus): string {
  if (!on) return "";
  return status === "loading" ? FEDERAL_LOADING : status === "unavailable" ? FEDERAL_UNAVAILABLE : "";
}

interface Props {
  on: boolean;
  onChange: (on: boolean) => void;
  status: FederalStatus;
  /** The plan's points on federal land, or null until the data has come. */
  points?: FederalPoint[] | null;
  /** How many points the plan has. */
  pointCount?: number;
  /** A point's name in the plan (Start, Stop 1, ..., End). */
  nameOf?: (index: number) => string;
}

/**
 * The section; the caller renders it for a Mass Ride only (federalShown's preset test).
 * Its status line is one persistent role="status" element whose words change (the a11y
 * review's N8): a live region inserted with its text is often not read.
 */
export function FederalLandSection({ on, onChange, status, points = null, pointCount = 0, nameOf = (i) => `Point ${i + 1}` }: Props): ReactElement {
  return h(
    "section",
    { "aria-labelledby": "federal-heading", className: "federal-section" },
    // An h3: the section sits in the Map layers sheet, under its h2 (OWNER-DECISIONS 312).
    h("h3", { id: "federal-heading" }, FEDERAL_HEADING),
    h(
      "label",
      { className: "toggle" },
      h("input", { type: "checkbox", checked: on, onChange: (event: { target: { checked: boolean } }) => onChange(event.target.checked) }),
      "Show federal land on the map",
    ),
    h("p", { className: "hint federal-status", role: "status" }, federalStatusText(on, status)),
    on && status !== "unavailable" && h(FederalLegend),
    h(FederalPointsList, { found: points, count: pointCount, nameOf }),
    h("p", { className: "hint federal-badge" }, FEDERAL_BADGE),
    h("p", { className: "hint" }, FEDERAL_HELP),
    h("p", { className: "hint" }, FEDERAL_OWNERSHIP),
    h("p", { className: "hint federal-note" }, `${FEDERAL_NOTE}.`),
  );
}

/**
 * The section for the ride type in use: Mass Ride's alone, null for every other
 * (OWNER-DECISIONS 324: "Federal land is probably only relevant in mass ride mode").
 * The switch's state is kept while another ride type is chosen, but nothing of it, its
 * legend, its help or the points list is shown there, and the map's layers follow
 * federalShown (federalLand.ts).
 */
export function FederalLandFor({ preset, ...props }: Props & { preset: PresetId }): ReactElement | null {
  return federalShown(preset, true) ? h(FederalLandSection, props) : null;
}
