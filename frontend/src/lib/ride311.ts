/**
 * Ride mode's 311 button (UI-CLEANUP, the owner's choice 9 of 2026-10-11): "a round button of about 60 px on
 * the right edge at thumb height. One tap opens a menu of large buttons: Pothole, Downed tree, Vehicle
 * parked in a bike lane, Roadway or bikeway obstructed, Streetlight out, Something else." The menu names the
 * rider's place, as the entry will. A pick is logged (lib/report311Log.ts; Stephen, 2026-10-20: "enable it
 * everywhere as a log with what website to go to and the description of where"), so the button shows
 * anywhere on the route, not only in DC; the checklist in Reports says which website takes each one. One tap
 * logs it, with no note (Stephen, 2026-10-21: "Don't bother with a note as people use it riding").
 *
 * A createElement module, so a test renders it (node's runner reads .ts, not .tsx).
 */
import { createElement as h, type ReactElement, type Ref } from "react";
import { REPORT_KINDS, gpsWords, type ReportKind, type ReportPlace } from "./report311.ts";
import { ICON_PATHS, type IconName } from "./iconPaths.ts";
import { t } from "./i18n.ts";

/** The button's visible words and the name it is heard by (the visible "311" is in it). */
export const RIDE_311_TEXT = "311";
export const RIDE_311_NAME = t("Log for 311");

/** Shown while the rider is on the route (off it, there is no place to log), anywhere the map covers. */
export function ride311Shown(state: { off: boolean; progressM: number | null }): boolean {
  return !state.off && state.progressM !== null;
}

/** The line under the menu's heading: where the entry will say (the way ridden, a near cross street, the GPS position). */
export function menuPlaceLine(place: ReportPlace | null): string {
  if (!place) return t("The entry names your place on the route.");
  const words = place.words ? `${place.words[0].toUpperCase()}${place.words.slice(1)}, ` : "";
  return `${words}${gpsWords(place.point)}.`;
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
}: {
  id: string;
  open: boolean;
  place: ReportPlace | null;
  headingRef?: Ref<HTMLHeadingElement>;
  onPick: (kind: ReportKind) => void;
  onClose: () => void;
}): ReactElement {
  return h(
    "div",
    { id, className: "ride-311-menu", role: "group", "aria-labelledby": `${id}-heading`, hidden: !open },
    h(
      "div",
      { className: "ride-311-head" },
      h("h3", { id: `${id}-heading`, ref: headingRef, tabIndex: -1 }, RIDE_311_NAME),
      h("button", { type: "button", className: "secondary ride-311-close", onClick: onClose }, t("Close")),
    ),
    h("p", { className: "hint ride-311-place" }, menuPlaceLine(place)),
    h(
      "ul",
      { className: "ride-311-kinds", role: "list" },
      REPORT_KINDS.map((k) =>
        h("li", { key: k.kind }, h("button", { type: "button", className: "ride-311-kind", onClick: () => onPick(k.kind) }, icon(KIND_ICON[k.kind]), t(k.label))),
      ),
    ),
  );
}
