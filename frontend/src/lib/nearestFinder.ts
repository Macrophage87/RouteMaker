/**
 * The planner's "Find the nearest" panel (lib/nearest.ts): where to search from,
 * a button each for water, restrooms and the Metro, one persistent status line,
 * and the three nearest as a list in words, each with Ride here and, for water
 * and restrooms in a planned ride, Add as stop. Written with createElement so a
 * test renders it (as waterLegend.ts).
 *
 * Collapsed by default, so it does not crowd every plan. The status line is
 * always rendered and its words change (a live region inserted with its text is
 * often not read); the buttons stay in the Tab order while a search runs
 * (aria-disabled, as Best order's does), so the focus is never lost.
 */
import { createElement as h, type ReactElement } from "react";
import {
  FROM_LABEL,
  NEAREST_KINDS,
  nearbyText,
  nounOf,
  stopsOnTheWay,
  type Nearby,
  type NearestFrom,
  type NearestKind,
} from "./nearest.ts";
import { WATER_CAUTION } from "./waterRestrooms.ts";

export const NEAREST_SUMMARY = "Find the nearest water, restroom or Metro";
export const NEAREST_HELP =
  "Ride here plans a route from where you searched to that place, in place of the plan you have; Undo puts your plan back. " +
  "Add as stop puts water or a restroom into the plan you have. Metro stations are Metrorail's; routes use the station's elevator where one is listed.";

export interface NearestList {
  kind: NearestKind;
  items: Nearby[];
}

export interface FinderProps {
  from: NearestFrom;
  /** The choices of where to search from that make sense now, in order. */
  fromOptions: readonly NearestFrom[];
  onFrom: (from: NearestFrom) => void;
  onFind: (kind: NearestKind) => void;
  busy: boolean;
  status: string;
  list: NearestList | null;
  /** Whether there is a plan to add a stop to. */
  canAddStop: boolean;
  onRide: (item: Nearby) => void;
  onAddStop: (item: Nearby) => void;
}

export function NearestFinder(props: FinderProps): ReactElement {
  const { from, fromOptions, onFrom, onFind, busy, status, list, canAddStop, onRide, onAddStop } = props;
  const addStops = list !== null && canAddStop && stopsOnTheWay(list.kind);
  return h(
    "details",
    { className: "fold nearest" },
    h("summary", null, NEAREST_SUMMARY),
    h(
      "div",
      { className: "fold-body" },
    h(
      "fieldset",
      { className: "nearest-from" },
      h("legend", null, "Search from"),
      ...fromOptions.map((option) =>
        h(
          "label",
          { key: option, className: "toggle" },
          h("input", {
            type: "radio",
            name: "nearest-from",
            value: option,
            checked: option === from,
            onChange: () => onFrom(option),
          }),
          FROM_LABEL[option],
        ),
      ),
    ),
    h(
      "div",
      { className: "actions nearest-kinds" },
      ...NEAREST_KINDS.map(({ kind, label }) =>
        h(
          "button",
          {
            key: kind,
            type: "button",
            className: "secondary",
            "aria-disabled": busy ? true : undefined,
            onClick: () => onFind(kind),
          },
          label,
        ),
      ),
    ),
    h("p", { className: "hint nearest-status", role: "status" }, status),
    list !== null &&
      list.items.length > 0 &&
      h(
        "div",
        { className: "nearest-list" },
        h("h3", { id: "nearest-list-heading" }, `Nearest ${nounOf(list.kind)}`),
        h(
          "ol",
          // role="list": WebKit drops a list's role once its bullets are styled away.
          { role: "list", "aria-labelledby": "nearest-list-heading" },
          ...list.items.map((item) =>
            h(
              "li",
              { key: item.place.id },
              h("span", null, nearbyText(item)),
              h(
                "span",
                { className: "actions" },
                h(
                  "button",
                  { type: "button", className: "secondary", "aria-label": `Ride here: ${item.place.title}`, onClick: () => onRide(item) },
                  "Ride here",
                ),
                addStops &&
                  h(
                    "button",
                    { type: "button", className: "secondary", "aria-label": `Add as stop: ${item.place.title}`, onClick: () => onAddStop(item) },
                    "Add as stop",
                  ),
              ),
            ),
          ),
        ),
        stopsOnTheWay(list.kind) && h("p", { className: "hint" }, WATER_CAUTION),
      ),
    h("p", { className: "hint" }, NEAREST_HELP),
    ),
  );
}
