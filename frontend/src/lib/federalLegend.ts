/**
 * The panel's Federal land section, shown only for a Mass Ride: the switch, the
 * status of the data, the legend and the standing note. Written with
 * createElement so a test renders it (as pointsList.ts, stressLegend.ts).
 *
 * The legend draws each kind with the map's own pattern and outline dash and
 * names the pattern in words, so no kind is told apart by colour alone.
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import {
  FEDERAL_KINDS,
  FEDERAL_NOTE,
  FEDERAL_STYLE,
  PATTERN_SIZE,
  federalPatternPath,
  type FederalKind,
} from "./federalLand.ts";

export type FederalStatus = "loading" | "ready" | "unavailable";

export const FEDERAL_HEADING = "Federal land";
export const FEDERAL_HELP =
  "The shading on the map marks federal land by kind, as the legend above lists them. Callouts for federal land " +
  "at each stop, and for parkways, are coming to the route description and the stop list. Pointer users can also " +
  "tap or click a shaded area for its name and manager. Shading is where land is owned or kept by the federal " +
  "government, which is not the same as who polices a road: ownership is not police jurisdiction, and in most " +
  "cases the roads are still city roads. It matters most for stopping, and for the parkways.";
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

interface Props {
  on: boolean;
  onChange: (on: boolean) => void;
  status: FederalStatus;
}

/** The section; the caller renders it for a Mass Ride only (federalShown's preset test). */
export function FederalLandSection({ on, onChange, status }: Props): ReactElement {
  return h(
    "section",
    { "aria-labelledby": "federal-heading", className: "federal-section" },
    h("h2", { id: "federal-heading" }, FEDERAL_HEADING),
    h(
      "label",
      { className: "toggle" },
      h("input", { type: "checkbox", checked: on, onChange: (event: { target: { checked: boolean } }) => onChange(event.target.checked) }),
      "Show federal land on the map",
    ),
    on &&
      h(
        Fragment,
        null,
        status === "loading" && h("p", { className: "hint", role: "status" }, FEDERAL_LOADING),
        status === "unavailable" && h("p", { className: "hint", role: "status" }, FEDERAL_UNAVAILABLE),
        status !== "unavailable" && h(FederalLegend),
      ),
    h("p", { className: "hint" }, FEDERAL_HELP),
    h("p", { className: "hint federal-note" }, `${FEDERAL_NOTE}.`),
  );
}
