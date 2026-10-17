/**
 * Ride mode's 311 button (UI-CLEANUP, the owner's choice 9 of 2026-10-11): "only while riding inside DC, a
 * round button of about 60 px on the right edge at thumb height. One tap opens a menu of large buttons:
 * Pothole, Downed tree, Vehicle parked in a bike lane, Roadway or bikeway obstructed, Streetlight out,
 * Something else. The existing report flow then continues." The menu names the rider's place, as the
 * report will ("Check it before you send"). Since v0.7.0 ("Go riding fixes" item 3: "tap 311, tap the
 * problem, sent") a pick is the report: sent by the server where it has DC's key, else the phone's text
 * app to 311 filled in (lib/report311.ts pickWay); a computer, or a pick with no place yet, opens Report a
 * problem to DC 311 (RideMode's Report311) with that problem chosen. The note comes after ("Add a note").
 *
 * A createElement module, so a test renders it (node's runner reads .ts, not .tsx).
 */
import { createElement as h, type ReactElement, type Ref } from "react";
import { REPORT_KINDS, gpsWords, type ReportKind, type ReportPlace } from "./report311.ts";
import { ICON_PATHS, type IconName } from "./iconPaths.ts";

/** The button's visible words and the name it is heard by (the visible "311" is in it). */
export const RIDE_311_TEXT = "311";
export const RIDE_311_NAME = "Report to DC 311";
/** The menu's last button: the full report, to copy, open DC 311 online or write a note first. */
export const RIDE_311_MORE = "Write a full report";

/** Shown only while the rider's place on the route is inside DC, and on the route (off it, there is no place to report). */
export function ride311Shown(state: { off: boolean; progressM: number | null; insideDc: (progressM: number) => boolean }): boolean {
  return !state.off && state.progressM !== null && state.insideDc(state.progressM);
}

/**
 * The line under the menu's heading: where the report will say (the way ridden, a near cross street,
 * the GPS position; lib/report311.ts `reportPlace`), to check before sending.
 */
export function menuPlaceLine(place: ReportPlace | null): string {
  if (!place) return "The report names your place on the route. Check it before you send.";
  const words = place.words ? `${place.words[0].toUpperCase()}${place.words.slice(1)}, ` : "";
  return `${words}${gpsWords(place.point)}. Check it before you send.`;
}

const KIND_ICON: Record<ReportKind, IconName> = {
  pothole: "warn",
  tree: "tree",
  bikeLane: "lane",
  obstruction: "stop",
  streetlight: "star",
  other: "more",
};

function icon(name: IconName): ReactElement {
  return h("svg", {
    className: "icon",
    width: 22,
    height: 22,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    focusable: "false",
    dangerouslySetInnerHTML: { __html: ICON_PATHS[name] },
  });
}

/**
 * The menu: a heading that takes the focus when it opens, Close, the place line and the six problems as
 * large buttons, in the owner's words and order (lib/report311.ts REPORT_KINDS). Escape closes it (RideMode).
 */
export function Ride311Menu({
  id,
  open,
  place,
  headingRef,
  onPick,
  onClose,
  onMore,
}: {
  id: string;
  open: boolean;
  place: ReportPlace | null;
  headingRef?: Ref<HTMLHeadingElement>;
  onPick: (kind: ReportKind) => void;
  onClose: () => void;
  /** The full report (copy, DC 311 online, a note first): Ride mode's bottom panel no longer shows it until asked. */
  onMore?: () => void;
}): ReactElement {
  return h(
    "div",
    { id, className: "ride-311-menu", role: "group", "aria-labelledby": `${id}-heading`, hidden: !open },
    h(
      "div",
      { className: "ride-311-head" },
      h("h3", { id: `${id}-heading`, ref: headingRef, tabIndex: -1 }, RIDE_311_NAME),
      h("button", { type: "button", className: "secondary ride-311-close", onClick: onClose }, "Close"),
    ),
    h("p", { className: "hint ride-311-place" }, menuPlaceLine(place)),
    h(
      "ul",
      { className: "ride-311-kinds", role: "list" },
      REPORT_KINDS.map((k) =>
        h("li", { key: k.kind }, h("button", { type: "button", className: "ride-311-kind", onClick: () => onPick(k.kind) }, icon(KIND_ICON[k.kind]), k.label)),
      ),
    ),
    onMore ? h("button", { type: "button", className: "secondary ride-311-more", onClick: onMore }, RIDE_311_MORE) : null,
  );
}
