/**
 * The Water and restrooms section of the Map layers sheet, and the list of the
 * points along the planned route (lib/waterRestrooms.ts). Written with
 * createElement so a test renders it (as federalLegend.ts).
 *
 * The list is the layer in words: a screen-reader or keyboard rider hears every
 * fountain and restroom near the route, in riding order, with how far along and
 * how far off it is, and can add one as a stop without the map.
 */
import { createElement as h, type ReactElement } from "react";
import { formatDistance } from "./format.ts";
import {
  ALONG_ROUTE_M,
  KIND_LABEL,
  WATER_CAUTION,
  WATER_KINDS,
  waterAlongCount,
  waterAlongText,
  waterIcon,
  type WaterAlong,
  type WaterKind,
  type WaterStatus,
} from "./waterRestrooms.ts";

export const WATER_HEADING = "Water and restrooms";
export const WATER_SWITCH = "Show public water and restrooms on the map";
export const WATER_LOADING = "Loading water and restrooms…";
export const WATER_UNAVAILABLE = "Water and restrooms are unavailable for now. The map and your route are not affected.";
export const WATER_HELP =
  "Public drinking fountains, water taps and restrooms that OpenStreetMap lists, drawn from street zoom in. " +
  "On by default for Trailmaxxing and Gravel. Places for customers only, or private, are left out.";
export const WATER_ALONG_HEADING = "Water and restrooms along your route";
export const WATER_ALONG_NONE = `None within ${formatDistance(ALONG_ROUTE_M)} of your route.`;
export const WATER_ALONG_NO_ROUTE = "Plan a route to list the water and restrooms along it.";

const SHAPE: Record<WaterKind, string> = {
  w: "blue drop",
  t: "purple diamond",
  wt: "purple diamond with a white drop",
};

/** The legend's swatch: the map's own icon, as an SVG of its inked pixels. */
export function WaterSwatch({ kind }: { kind: WaterKind }): ReactElement {
  const raster = waterIcon(kind, 1);
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
    { width: raster.width, height: raster.height, "aria-hidden": "true", className: "water-swatch", viewBox: `0 0 ${raster.width} ${raster.height}` },
    ...[...colours].map(([fill, path], k) => h("path", { key: k, d: path, fill })),
  );
}

export function WaterLegend(): ReactElement {
  return h(
    "ul",
    { className: "legend water-legend", "aria-label": "Water and restrooms legend" },
    ...WATER_KINDS.map((kind) =>
      h("li", { key: kind }, h(WaterSwatch, { kind }), h("span", { className: "stress-label" }, `${KIND_LABEL[kind]}: ${SHAPE[kind]}`)),
    ),
  );
}

export function waterStatusText(on: boolean, status: WaterStatus): string {
  if (!on) return "";
  return status === "loading" ? WATER_LOADING : status === "unavailable" ? WATER_UNAVAILABLE : "";
}

interface AlongProps {
  /** The points along the route, or null with no route yet. */
  items: WaterAlong[] | null;
  /** Add a point as a stop; the button is left out without it. */
  onAddStop?: (item: WaterAlong) => void;
  headingId: string;
  /** The heading's level: h3 in the planner's Route section, h4 in the Map layers sheet's section. */
  level?: "h3" | "h4";
}

/** The points along the route, in words, each with an Add as stop button. */
export function WaterAlongList({ items, onAddStop, headingId, level = "h4" }: AlongProps): ReactElement {
  if (items === null) return h("p", { className: "hint water-along" }, WATER_ALONG_NO_ROUTE);
  if (items.length === 0) return h("p", { className: "hint water-along" }, WATER_ALONG_NONE);
  return h(
    "div",
    { className: "water-along" },
    h(level, { id: headingId }, WATER_ALONG_HEADING),
    h("p", { className: "hint" }, waterAlongCount(items)),
    h(
      "ul",
      { "aria-labelledby": headingId },
      ...items.map((item) => {
        const said = waterAlongText(item);
        return h(
          "li",
          { key: item.point.id },
          h("span", null, said),
          onAddStop &&
            h(
              "button",
              {
                type: "button",
                className: "secondary water-add",
                "aria-label": `Add as stop: ${KIND_LABEL[item.point.kind]} at ${formatDistance(item.alongM)}`,
                onClick: () => onAddStop(item),
              },
              "Add as stop",
            ),
        );
      }),
    ),
    h("p", { className: "hint" }, WATER_CAUTION),
  );
}

interface SectionProps {
  on: boolean;
  onChange: (on: boolean) => void;
  status: WaterStatus;
  items: WaterAlong[] | null;
  onAddStop?: (item: WaterAlong) => void;
}

/**
 * The section in the Map layers sheet: the switch, one persistent status line
 * whose words change (a live region inserted with its text is often not read),
 * the legend, the list and the help.
 */
export function WaterSection({ on, onChange, status, items, onAddStop }: SectionProps): ReactElement {
  return h(
    "section",
    { "aria-labelledby": "water-heading", className: "water-section" },
    h("h3", { id: "water-heading" }, WATER_HEADING),
    h(
      "label",
      { className: "toggle" },
      h("input", { type: "checkbox", checked: on, onChange: (event: { target: { checked: boolean } }) => onChange(event.target.checked) }),
      WATER_SWITCH,
    ),
    h("p", { className: "hint water-status", role: "status" }, waterStatusText(on, status)),
    on && status === "ready" && h(WaterLegend),
    on && status === "ready" && h(WaterAlongList, { items, onAddStop, headingId: "water-along-layers-heading" }),
    h("p", { className: "hint" }, WATER_HELP),
  );
}
