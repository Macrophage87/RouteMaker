/**
 * The sidebar's parts that a test renders (OWNER-DECISIONS 312): the Ride line, the route summary's
 * folds, the legend's junction markers, and the two parts built for open owner questions. Written
 * with createElement, as stressLegend.ts and federalLegend.ts are, because node's test runner reads
 * .ts and not .tsx (Sidebar.tsx re-exports them for App.tsx).
 *
 * Each is a real button or a real <details>, with its state in aria-expanded (or the element's own)
 * and its words in text; none depends on colour.
 */
import { Fragment, createElement as h, useId, useState, type ReactElement, type ReactNode } from "react";
import { RIDE_ACTION_SPOKEN, rideActionLabel } from "./sidebar.ts";
import { SEVERITY_COLOURS, warningIconSvg, type Severity } from "./intersectionMarkers.ts";
import { stressZoomNotice } from "./stressLegend.ts";
import { ACCESSIBILITY_ADDRESS_NOTE, ACCESSIBILITY_HINT, ACCESSIBILITY_LABEL } from "./accessibilitySwitch.ts";

/**
 * The Ride line: one line saying how the ride is set, and Edit, which opens the controls
 * (`children`). A heading holds the button, so a screen reader can jump to it. The controls stay in
 * the page while closed (hidden), so nothing they hold is lost. The region is named "Ride" alone:
 * the button's name holds the summary, which changes with every edit (the a11y review's N4). The
 * action is shown as Edit or Done but heard as Edit, its state in aria-expanded, so a screen reader
 * does not say "Done, expanded" (N8).
 */
export function RideSettings({ summary, spoken, children }: { summary: string; spoken: string; children?: ReactNode }): ReactElement {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return h(
    "section",
    { className: "ride-settings", "aria-label": "Ride" },
    h(
      "h2",
      { id: "ride-settings-heading", className: "ride-line" },
      h(
        "button",
        { type: "button", className: "ride-line-button", "aria-expanded": open, "aria-controls": bodyId, onClick: () => setOpen(!open) },
        h(
          "span",
          { className: "ride-line-text" },
          h("span", { className: "ride-line-label" }, "Ride"),
          h("span", { className: "ride-line-summary", "aria-hidden": "true" }, summary),
          h("span", { className: "visually-hidden" }, `: ${spoken}.`),
        ),
        h("span", { className: "ride-line-action", "aria-hidden": "true" }, rideActionLabel(open)),
        h("span", { className: "visually-hidden" }, ` ${RIDE_ACTION_SPOKEN}`),
      ),
    ),
    h("div", { id: bodyId, className: "ride-settings-body", hidden: !open }, children),
  );
}

/**
 * A collapsible section of the route summary: a native disclosure, closed unless `open`. With
 * `heading`, an h3 of that name comes first, out of sight, so a screen reader's heading list
 * reaches the fold (a summary's own content is not read as a heading; the a11y review's S5).
 * `onToggle` hears the rider open or close it (Directions remembers it).
 */
export function Fold({
  title,
  heading,
  headingId,
  open,
  className,
  onToggle,
  children,
}: {
  title: string;
  heading?: string;
  headingId?: string;
  open?: boolean;
  className?: string;
  onToggle?: (open: boolean) => void;
  children?: ReactNode;
}): ReactElement {
  const details = h(
    "details",
    {
      className: className ? `fold ${className}` : "fold",
      open,
      onToggle: onToggle ? (event: { currentTarget: { open: boolean } }) => onToggle(event.currentTarget.open) : undefined,
    },
    h("summary", null, title),
    h("div", { className: "fold-body" }, children),
  );
  if (!heading) return details;
  return h(Fragment, null, h("h3", { id: headingId, className: "visually-hidden" }, heading), details);
}

const JUNCTION_SHAPES: ReadonlyArray<{ severity: Severity; shape: string }> = [
  { severity: "orange", shape: "triangle" },
  { severity: "red", shape: "diamond" },
];

/**
 * The legend's Junctions part (mockup v3, Layers; the spec review's SF1): the two markers the map
 * draws at stressful junctions, each with its shape and its words, so neither colour nor shape is
 * needed alone. The shapes and colours are the markers' own (intersectionMarkers.ts).
 */
export function JunctionLegend(): ReactElement {
  return h(
    "div",
    { className: "junction-legend" },
    h("h4", { id: "junction-legend-heading" }, "Junctions"),
    h(
      "ul",
      { className: "junction-legend-list", "aria-labelledby": "junction-legend-heading" },
      ...JUNCTION_SHAPES.map(({ severity, shape }) =>
        h(
          "li",
          { key: severity },
          h("span", { className: "junction-icon", "aria-hidden": "true", dangerouslySetInnerHTML: { __html: warningIconSvg(severity, 20) } }),
          h("span", null, SEVERITY_COLOURS[severity].label, h("span", { className: "hint" }, ` (${shape})`)),
        ),
      ),
    ),
  );
}

/**
 * Ready to place, not placed (PLANNER_EXTRAS, an open owner question): the zoom notice in one line
 * over the planner, as well as in the Map layers sheet. A live region that stays in the page, so a
 * change of notice is said: the sheet's copy is hidden whenever the planner shows, and the planner is
 * hidden whenever the sheet shows, so only one of the two can ever speak.
 */
export function PlannerZoomNotice({ zoom, shown }: { zoom: number | null; shown: boolean }): ReactElement {
  const notice = stressZoomNotice(zoom, shown);
  return h("div", { className: "planner-zoom", role: "status" }, notice ? h("p", { className: "notice" }, notice) : null);
}

/**
 * Ready to place, not placed (PLANNER_EXTRAS, an open owner question): the Accessibility colours in
 * the planner, a toggle button doing what the Map layers sheet's switch does. No id of its own, so
 * it never shares one with the switch.
 */
export function AccessibilityShortcut({
  on,
  paletteFromAddress = false,
  onChange,
}: {
  on: boolean;
  /** The palette came from the address (palette= in the link): said as the sheet's switch says it. */
  paletteFromAddress?: boolean;
  onChange: (on: boolean) => void;
}): ReactElement {
  const hintId = useId();
  const hint = [ACCESSIBILITY_HINT, paletteFromAddress ? ACCESSIBILITY_ADDRESS_NOTE : ""].filter(Boolean).join(" ");
  return h(
    Fragment,
    null,
    h(
      "button",
      { type: "button", className: "secondary accessibility-shortcut", "aria-pressed": on, "aria-describedby": hintId, onClick: () => onChange(!on) },
      ACCESSIBILITY_LABEL,
      h("span", { "aria-hidden": "true" }, `: ${on ? "On" : "Off"}`),
    ),
    h("span", { id: hintId, className: "visually-hidden" }, hint),
  );
}
