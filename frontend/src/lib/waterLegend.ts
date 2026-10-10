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
  ALONG_ROUTE_TEXT,
  WATER_CAUTION,
  waterAlongCount,
  waterAlongText,
  waterIcon,
  waterTitle,
  type WaterAlong,
  type WaterIcon,
  type WaterPrefs,
  type WaterStatus,
} from "./waterRestrooms.ts";

export const WATER_HEADING = "Water and restrooms";
export const WATER_SWITCH = "Show public water and restrooms on the map";
export const WATER_LOADING = "Loading water and restrooms…";
export const WATER_UNAVAILABLE = "Water and restrooms are unavailable for now. The map and your route are not affected.";
export const WATER_BASIC_SWITCH = "Portable, pit and composting toilets";
export const WATER_UNTREATED_SWITCH = "Untreated water sources (filter or treat first)";
export const WATER_HELP =
  "Public drinking fountains, water taps, springs and restrooms that OpenStreetMap lists, drawn from street zoom " +
  "in. Places for customers only, or private, are left out. With a route planned, the ones within " +
  `${ALONG_ROUTE_TEXT} of it are listed in riding order under the route, each with an Add as stop button. ` +
  "Your choices here are kept on this device.";
export const WATER_UNTREATED_HELP =
  "Untreated water is a spring, well or tap not marked as drinkable, or a water point marked not drinkable: carry a filter or treat it before you drink.";
export const WATER_ALONG_HEADING = "Water and restrooms along your route";
export const WATER_ALONG_NONE = `None within ${ALONG_ROUTE_TEXT} of your route.`;
export const WATER_ALONG_NO_ROUTE = "Plan a route to list the water and restrooms along it.";

/** The legend's rows, in its order: what each icon is, then its shape in words (a cue that is not colour). */
export const WATER_LEGEND: ReadonlyArray<{ icon: WaterIcon; label: string; shape: string }> = [
  { icon: "w-p", label: "Drinking water", shape: "blue drop" },
  { icon: "w-n", label: "Untreated water, filter or treat it first", shape: "brown drop struck through" },
  { icon: "t-f", label: "Flush restroom", shape: "purple diamond" },
  { icon: "t-b", label: "Portable, pit or composting toilet", shape: "green upright box" },
  { icon: "t-u", label: "Restroom, type not mapped", shape: "white diamond ringed in purple" },
  { icon: "t-f-w", label: "A restroom with drinking water", shape: "its shape with a drop inside" },
];

/** The legend's swatch: the map's own icon, as an SVG of its inked pixels. */
export function WaterSwatch({ icon }: { icon: WaterIcon }): ReactElement {
  const raster = waterIcon(icon, 1);
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

export function WaterLegend({ prefs }: { prefs: WaterPrefs }): ReactElement {
  const rows = WATER_LEGEND.filter(({ icon }) => (prefs.untreated || icon !== "w-n") && (prefs.basic || icon !== "t-b"));
  return h(
    "ul",
    { className: "legend water-legend", "aria-label": "Water and restrooms legend" },
    ...rows.map(({ icon, label, shape }) =>
      h("li", { key: icon }, h(WaterSwatch, { icon }), h("span", { className: "stress-label" }, `${label}: ${shape}`)),
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
  // The heading always, so a rider moving by headings finds the list's place even when it is empty.
  const heading = h(level, { id: headingId }, WATER_ALONG_HEADING);
  if (items === null) return h("div", { className: "water-along" }, heading, h("p", { className: "hint" }, WATER_ALONG_NO_ROUTE));
  if (items.length === 0) return h("div", { className: "water-along" }, heading, h("p", { className: "hint" }, WATER_ALONG_NONE));
  return h(
    "div",
    { className: "water-along" },
    heading,
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
                "aria-label": `Add as stop: ${waterTitle(item.point)} at ${formatDistance(item.alongM)}`,
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
  prefs: WaterPrefs;
  onChange: (prefs: WaterPrefs) => void;
  status: WaterStatus;
  items: WaterAlong[] | null;
  onAddStop?: (item: WaterAlong) => void;
}

function checkbox(checked: boolean, onChange: (on: boolean) => void, label: string, className = "toggle"): ReactElement {
  return h(
    "label",
    { className },
    h("input", { type: "checkbox", checked, onChange: (event: { target: { checked: boolean } }) => onChange(event.target.checked) }),
    label,
  );
}

/**
 * The section in the Map layers sheet: the layer's switch and, while it is on, the two kinds a rider may
 * not want (basic toilets, untreated water); one persistent status line whose words change (a live region
 * inserted with its text is often not read); the legend, the list and the help.
 */
export function WaterSection({ prefs, onChange, status, items, onAddStop }: SectionProps): ReactElement {
  const ready = prefs.on && status === "ready";
  return h(
    "section",
    { "aria-labelledby": "water-heading", className: "water-section" },
    h("h3", { id: "water-heading" }, WATER_HEADING),
    checkbox(prefs.on, (on) => onChange({ ...prefs, on }), WATER_SWITCH),
    prefs.on &&
      h(
        "fieldset",
        { className: "water-kinds" },
        h("legend", null, "Also show"),
        checkbox(prefs.basic, (basic) => onChange({ ...prefs, basic }), WATER_BASIC_SWITCH),
        checkbox(prefs.untreated, (untreated) => onChange({ ...prefs, untreated }), WATER_UNTREATED_SWITCH),
      ),
    h("p", { className: "hint water-status", role: "status" }, waterStatusText(prefs.on, status)),
    ready && h(WaterLegend, { prefs }),
    ready && h(WaterAlongList, { items, onAddStop, headingId: "water-along-layers-heading" }),
    h("p", { className: "hint" }, WATER_HELP),
    prefs.on && prefs.untreated && h("p", { className: "hint" }, WATER_UNTREATED_HELP),
  );
}
