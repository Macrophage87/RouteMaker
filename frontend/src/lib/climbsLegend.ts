/**
 * The Climbs switch under "Trails and terrain" in the Map layers sheet, its legend, and the list of
 * the climbs the planned route rides (lib/climbs.ts). Written with createElement so a test renders
 * it, as waterLegend.ts and mtbTrailsSwitch.ts.
 *
 * The switch is a button with role="switch", like "Mountain-bike trails" beside it, so a keyboard
 * (Space or Enter) and a screen reader (name, state, description) reach it. The list is the layer in
 * words: each climb's category, length and average grade ("Category 3 climb, 2.1 miles (3.4 km) at
 * 4.6%"), where on the route it starts and what it gains, without the map.
 */
import { createElement as h, useSyncExternalStore, type ReactElement } from "react";
import { formatDistance } from "./format.ts";
import {
  CLIMB_CAUTION,
  CLIMB_COLOUR,
  CLIMBS_LINE_MIN_ZOOM,
  CLIMBS_MIN_ZOOM,
  CLIMB_SURFACES,
  climbAlongCount,
  hideBusyClimbs,
  setHideBusyClimbs,
  trailClimbs,
  subscribeHideBusy,
  climbAlongText,
  climbIcon,
  climbShape,
  SHAPE_WORDS,
  type ClimbAlong,
  type ClimbCategory,
  type ClimbShape,
  type ClimbSurface,
  type ClimbsStatus,
} from "./climbs.ts";

export const CLIMBS_LABEL = "Climbs";
/** Read on every focus, so kept under 150 characters. */
export const CLIMBS_HINT = `From zoom ${CLIMBS_MIN_ZOOM}. Changes no route.`;
export const CLIMBS_LOADING = "Loading climbs…";
export const CLIMBS_UNAVAILABLE = "Climbs are unavailable for now. The map and your route are not affected.";
export const CLIMBS_EMPTY = "No climbs yet: the climbs are measured on the build server, and this map has not had them added.";
export const CLIMBS_HELP =
  `A climb is at least ${formatDistance(500)} long at 1% or more on average, scored as its length in metres times its ` +
  "average grade in percent (Garmin's scale, which works out to 100 times the height gained): Category 5 over " +
  "4,000, 4 over 8,000, 3 over 16,000, 2 over 32,000, 1 over 64,000, and HC (hors catégorie, beyond category) " +
  "over 80,000. Short dips and flats count as breaks inside a climb, so it is scored on its net gain. With a " +
  "route planned, the climbs it rides are listed in riding order. Your choice is kept on this device.";
export const CLIMBS_ALONG_HEADING = "Climbs on your route";
export const CLIMBS_ALONG_NONE = "Your route rides none of the climbs on the map.";
export const CLIMBS_ALONG_NO_ROUTE = "Plan a route to list the climbs it rides.";

/** The legend's shape rows, in order of steepness. */
export const CLIMB_LEGEND: ReadonlyArray<{ shape: ClimbShape; label: string }> = [
  { shape: "circle", label: "Gentle" },
  { shape: "square", label: "Moderate" },
  { shape: "diamond", label: "Steep" },
];

/** The legend's swatch: the map's own shape, as an SVG of its inked pixels, with a sample number. */
export function ClimbSwatch({ shape, number = "4", surface = "road" }: { shape: ClimbShape; number?: string; surface?: ClimbSurface }): ReactElement {
  const raster = climbIcon(shape, 1, undefined, surface);
  const colours = new Map<string, string>();
  for (let y = 0; y < raster.height; y++) {
    for (let x = 0; x < raster.width; x++) {
      const i = (y * raster.width + x) * 4;
      if (raster.data[i + 3] < 128) continue;
      const fill = `rgb(${raster.data[i]},${raster.data[i + 1]},${raster.data[i + 2]})`;
      colours.set(fill, (colours.get(fill) ?? "") + `M${x} ${y}h1v1h-1z`);
    }
  }
  return h(
    "svg",
    { width: raster.width, height: raster.height, "aria-hidden": "true", className: "climb-swatch", viewBox: `0 0 ${raster.width} ${raster.height}` },
    ...[...colours].map(([fill, path], k) => h("path", { key: k, d: path, fill })),
    h(
      "text",
      { key: "n", x: raster.width / 2, y: raster.height / 2, fill: "#ffffff", fontSize: 11, fontWeight: 600, textAnchor: "middle", dominantBaseline: "central" },
      number,
    ),
  );
}

export function ClimbsLegend(): ReactElement {
  return h(
    "ul",
    { className: "legend climbs-legend", "aria-label": "Climbs legend" },
    h(
      "li",
      { key: "number" },
      h(ClimbSwatch, { shape: "circle", number: "3" }),
      h("span", { className: "stress-label" }, "The number at a climb's top is its category, 5 (smallest) to 1, then HC (the biggest); the shape around it is its steepness"),
    ),
    ...CLIMB_LEGEND.map(({ shape, label }) =>
      h("li", { key: shape }, h(ClimbSwatch, { shape }), h("span", { className: "stress-label" }, `${label}: ${SHAPE_WORDS[shape]}`)),
    ),
    h(
      "li",
      { key: "line" },
      h(
        "svg",
        { width: 24, height: 12, "aria-hidden": "true", className: "climb-swatch", viewBox: "0 0 24 12" },
        h("line", { x1: 1, y1: 6, x2: 23, y2: 6, stroke: CLIMB_COLOUR, strokeWidth: 4, strokeDasharray: "4 4" }),
      ),
      h("span", { className: "stress-label" }, `The climb itself, from zoom ${CLIMBS_LINE_MIN_ZOOM}: a dashed line from its start to the top`),
    ),
    // The colour is what most of the climb is ridden on (the owner, 2026-10-19), said in words here.
    ...CLIMB_SURFACES.map(({ surface, label }) =>
      h("li", { key: `surface-${surface}` }, h(ClimbSwatch, { shape: "square", surface }), h("span", { className: "stress-label" }, `Colour: ${label}`)),
    ),
  );
}

export const CLIMBS_HIDE_BUSY_LABEL = "Hide climbs on busy roads";
export const CLIMBS_HIDE_BUSY_HINT = "Climbs mostly on LTS 3 or higher roads.";

/** "Hide climbs on busy roads", for a render to follow (lib/climbs.ts hideBusyClimbs). */
export function useHideBusyClimbs(): boolean {
  return useSyncExternalStore(subscribeHideBusy, hideBusyClimbs, hideBusyClimbs);
}

/** Whether climbs on mountain-bike trails show, for a render to follow (lib/climbs.ts trailClimbs). */
export function useTrailClimbs(): boolean {
  return useSyncExternalStore(subscribeHideBusy, trailClimbs, trailClimbs);
}

/**
 * The switch (the owner, 2026-10-19: "optionally (default on) hide climbs on LTS 3+ roads"), beside "Show climbs
 * from" while the layer is on: a button with role="switch", as the layer's own.
 */
export function ClimbsHideBusySwitch(): ReactElement {
  const on = useHideBusyClimbs();
  return h(
    "div",
    { className: "a11y-setting climbs-hide-busy" },
    h(
      "button",
      {
        type: "button",
        role: "switch",
        id: "climbs-hide-busy-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "climbs-hide-busy-label",
        "aria-describedby": "climbs-hide-busy-hint",
        onClick: () => setHideBusyClimbs(!on),
      },
      h("span", { id: "climbs-hide-busy-label", className: "switch-label" }, CLIMBS_HIDE_BUSY_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: "climbs-hide-busy-hint" }, CLIMBS_HIDE_BUSY_HINT),
  );
}

export function climbsStatusText(on: boolean, status: ClimbsStatus): string {
  if (!on) return "";
  if (status === "loading") return CLIMBS_LOADING;
  if (status === "unavailable") return CLIMBS_UNAVAILABLE;
  if (status === "empty") return CLIMBS_EMPTY;
  return "";
}

interface AlongProps {
  /** The climbs the route rides, or null with no route yet. */
  items: ClimbAlong[] | null;
  headingId: string;
  /** h3 in the planner's Route section, h4 in the Map layers sheet. */
  level?: "h3" | "h4";
}

/** The climbs the route rides, in words, in riding order. */
export function ClimbsAlongList({ items, headingId, level = "h4" }: AlongProps): ReactElement {
  // The heading always, so a rider moving by headings finds the list's place even when it is empty.
  const heading = h(level, { id: headingId }, CLIMBS_ALONG_HEADING);
  if (items === null) return h("div", { className: "climbs-along" }, heading, h("p", { className: "hint" }, CLIMBS_ALONG_NO_ROUTE));
  if (items.length === 0) return h("div", { className: "climbs-along" }, heading, h("p", { className: "hint" }, CLIMBS_ALONG_NONE));
  return h(
    "div",
    { className: "climbs-along" },
    heading,
    h("p", { className: "hint" }, climbAlongCount(items)),
    h(
      "ul",
      { "aria-labelledby": headingId, className: "climbs-along-list" },
      ...items.map((item) =>
        h(
          "li",
          { key: item.climb.id },
          h(ClimbSwatch, { shape: climbShapeOf(item), number: item.climb.category }),
          h("span", null, climbAlongText(item)),
        ),
      ),
    ),
    h("p", { className: "hint" }, CLIMB_CAUTION),
  );
}

const climbShapeOf = (item: ClimbAlong): ClimbShape => climbShape(item.climb.gradePct);

/** The switch, a button with role="switch" (as MtbTrailsSwitch). */
export function ClimbsSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }): ReactElement {
  return h(
    "div",
    { className: "a11y-setting" },
    h(
      "button",
      {
        type: "button",
        role: "switch",
        id: "climbs-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "climbs-label",
        "aria-describedby": "climbs-hint",
        onClick: () => onChange(!on),
      },
      h("span", { id: "climbs-label", className: "switch-label" }, CLIMBS_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: "climbs-hint" }, CLIMBS_HINT),
  );
}

export const CLIMBS_FROM_LABEL = "Show climbs from";

/** "Show climbs from"'s choices, easiest first; HC spelled out, as a screen reader would say "H C". */
export const CLIMBS_FROM_OPTIONS: ReadonlyArray<{ value: ClimbCategory; text: string }> = [
  { value: "5", text: "All (Category 5 and up)" },
  { value: "4", text: "Category 4 and up" },
  { value: "3", text: "Category 3 and up" },
  { value: "2", text: "Category 2 and up" },
  { value: "1", text: "Category 1 and up" },
  { value: "HC", text: "Hors catégorie (HC) only" },
];

/**
 * "Show climbs from" (the owner, 2026-10-12): one native select beside the switch, labelled, so a keyboard
 * and a screen reader reach it as any select; the map, the list and the road panel follow it. Nothing is
 * announced on a change, as for the other layer settings: the select says its own new value.
 */
export function ClimbsFromSelect({ from, onChange }: { from: ClimbCategory; onChange: (from: ClimbCategory) => void }): ReactElement {
  return h(
    "div",
    { className: "climbs-from" },
    h("label", { htmlFor: "climbs-from" }, CLIMBS_FROM_LABEL),
    h(
      "select",
      {
        id: "climbs-from",
        value: from,
        onChange: (event: { target: { value: string } }) => onChange(event.target.value as ClimbCategory),
      },
      ...CLIMBS_FROM_OPTIONS.map((o) => h("option", { key: o.value, value: o.value }, o.text)),
    ),
  );
}

interface SectionProps {
  on: boolean;
  onChange: (on: boolean) => void;
  status: ClimbsStatus;
  items: ClimbAlong[] | null;
  /** "Show climbs from", shown while the layer is on; absent where the caller does not offer it. */
  from?: ClimbCategory;
  onFromChange?: (from: ClimbCategory) => void;
}

/**
 * The switch and, while it is on, one persistent status line whose words change (a live region
 * inserted with its text is often not read), the legend, the list and the help. Sits inside the
 * "Trails and terrain" section, so it has no heading of its own above the list's.
 */
export function ClimbsLayerControls({ on, onChange, status, items, from, onFromChange, along = true, legend = true }: SectionProps & { along?: boolean; legend?: boolean }): ReactElement {
  // UI-CLEANUP: the climbs on the route are in the Elevation and climbs fold (along false in Layers), with
  // CLIMBS_HELP behind Layers' Legend button. The key is under the switch in Layers too (the owner, 2026-10-19:
  // "Make sure there's a key in layers" and "shapes should have a key too").
  const ready = on && status === "ready";
  return h(
    "div",
    { className: "climbs-controls" },
    h(ClimbsSwitch, { on, onChange }),
    on && from !== undefined && onFromChange && h(ClimbsFromSelect, { from, onChange: onFromChange }),
    on && from !== undefined && onFromChange && h(ClimbsHideBusySwitch, null),
    h("p", { className: "hint climbs-status", role: "status" }, climbsStatusText(on, status)),
    ready && legend && h(ClimbsLegend, null),
    ready && along && h(ClimbsAlongList, { items, headingId: "climbs-along-layers-heading" }),
  );
}
