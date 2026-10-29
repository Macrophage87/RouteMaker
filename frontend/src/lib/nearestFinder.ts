/**
 * The planner's "Find the nearest" panel (lib/nearest.ts): a button each for water, restrooms and
 * the Metro, one persistent status line, the three nearest as a list in words, each with Ride here
 * and, for water and restrooms in a planned ride, Add as stop, then where to search from. Written
 * with createElement so a test renders it (as waterLegend.ts).
 *
 * Results first (the 2026-10-28 audit, P7): the three buttons (the one chosen marked, aria-pressed,
 * in the selected chip's style), the list, then "From: My location" as one line (it was a set of
 * radios above the list). The status line on screen says only what the rows do not (foundShort);
 * a screen reader hears the whole sentence. A Throne restroom's how-to and an approximate pin are
 * said once under the list, short, not in every row's details.
 *
 * Collapsed by default, so it does not crowd every plan. The status line is always rendered and its
 * words change (a live region inserted with its text is often not read); the buttons stay in the
 * Tab order while a search runs (aria-disabled, as Best order's does), so the focus is never lost.
 */
import { createElement as h, useState, type ReactElement } from "react";
import {
  FROM_LABEL,
  NEAREST_KINDS,
  foundSaid,
  foundShort,
  nearbyShort,
  nounOf,
  stopsOnTheWay,
  type Nearby,
  type NearestFrom,
  type NearestKind,
} from "./nearest.ts";
import { WATER_CAUTION, sheetNoteDetail } from "./waterRestrooms.ts";
import { SheetNotes } from "./waterLegend.ts";
import { placeLetter, SHOW_ALL_ON_MAP } from "./letteredPlaces.ts";
import { t } from "./i18n.ts";

export const NEAREST_SUMMARY = t("Find the nearest water, restroom or Metro");
export const NEAREST_HELP =
  t("Each place is named on the map: a tap on its name, or its letter's key (A for the first), shows what's there. Ride here plans a route from where you searched to that place, in place of the plan you have; Undo puts your plan back. Add as stop puts water or a restroom into the plan you have. Metro stations are Metrorail's; routes use the station's elevator where one is listed.");

export interface NearestList {
  kind: NearestKind;
  items: Nearby[];
  /** Where it was searched from (lib/nearest.ts Found): the status line's full sentence is told from it. */
  from?: NearestFrom;
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
  /**
   * Show on map, as Find food's (the owner, 2026-10-28): the place on the map; from a phone's popup, the popup closes
   * first so its lettered pins can be pressed, and the chip opens the same list again. Absent: no button.
   */
  onShow?: (item: Nearby, index: number) => void;
  /** Show all on map (Stephen 2026-10-29), as Find food's. Absent: no button. */
  onShowAll?: () => void;
  /** A fold of its own (the default), or the body alone, in the map's Water sheet (UI-CLEANUP), whose heading names it. */
  folded?: boolean;
}

export function NearestFinder(props: FinderProps): ReactElement {
  const { from, fromOptions, onFrom, onFind, busy, status, list, canAddStop, onRide, onAddStop, onShow, onShowAll, folded = true } = props;
  // The button last pressed, marked while its search runs (the list, once in, says which it is).
  const [asked, setAsked] = useState<NearestKind | null>(null);
  const chosen = list?.kind ?? (busy ? asked : null);
  const addStops = list !== null && canAddStop && stopsOnTheWay(list.kind);
  // The list's own status line, short on screen; the whole sentence is still what is heard.
  const short = list && list.items.length > 0 && list.from && status === foundSaid(list.kind, list.from, list.items) ? foundShort(list.items) : null;
  const wrap = (body: ReactElement) =>
    folded ? h("details", { className: "fold nearest" }, h("summary", null, NEAREST_SUMMARY), body) : h("div", { className: "nearest nearest-sheet" }, body);
  return wrap(
    h(
      "div",
      { className: "fold-body" },
      // The three choices first (the owner, 2026-10-18: "the three choices make more sense to be up front").
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
              "aria-label": t("Nearest {noun}", { noun: kind === "metro" ? label : label.toLowerCase() }),
              "aria-pressed": chosen === kind,
              "aria-disabled": busy ? true : undefined,
              onClick: () => {
                setAsked(kind);
                onFind(kind);
              },
            },
            label,
          ),
        ),
      ),
      short === null
        ? h("p", { className: "hint nearest-status", role: "status" }, status)
        : h(
            "p",
            { className: "hint nearest-status", role: "status" },
            h("span", { "aria-hidden": "true" }, short),
            h("span", { className: "visually-hidden" }, status),
          ),
      list !== null &&
        list.items.length > 1 &&
        onShowAll &&
        h("button", { type: "button", className: "secondary show-all", onClick: onShowAll }, SHOW_ALL_ON_MAP),
      list !== null &&
        list.items.length > 0 &&
        h(
          "div",
          { className: "nearest-list" },
          h("h3", { id: "nearest-list-heading" }, t("Nearest {noun}", { noun: nounOf(list.kind) })),
          h(
            "ol",
            // role="list": WebKit drops a list's role once its bullets are styled away.
            { role: "list", "aria-labelledby": "nearest-list-heading" },
            ...list.items.map((item, index) => {
              // A Throne's how-to and an approximate pin are said once, under the list (SheetNotes).
              const details = item.place.details.filter((d) => !sheetNoteDetail(d));
              return h(
                "li",
                { key: item.place.id, className: "lettered-row" },
                // The map's marker shows the name (Stephen 2026-10-29: "Named, not lettered"); the letter, its key's, is heard.
                h(
                  "div",
                  { className: "nearest-place" },
                  h("span", { className: "visually-hidden" }, `${placeLetter(index)}: `),
                  nearbyShort(item),
                  // Its details (opening hours, access) behind a native fold.
                  details.length > 0 &&
                    h("details", { className: "nearest-details" }, h("summary", null, t("Details"), h("span", { className: "visually-hidden" }, t(" of {place}", { place: item.place.title }))), h("p", { className: "hint" }, details.join(" "))),
                ),
                h(
                  "span",
                  { className: "actions" },
                  onShow &&
                    h(
                      "button",
                      { type: "button", className: "secondary", "aria-label": t("Show on map: {place}, marker {letter}", { place: item.place.title, letter: placeLetter(index) }), onClick: () => onShow(item, index) },
                      t("Show on map"),
                    ),
                  h(
                    "button",
                    { type: "button", className: "secondary", "aria-label": t("Ride here: {place}", { place: item.place.title }), onClick: () => onRide(item) },
                    t("Ride here"),
                  ),
                  addStops &&
                    h(
                      "button",
                      { type: "button", className: "secondary", "aria-label": t("Add as stop: {place}", { place: item.place.title }), onClick: () => onAddStop(item) },
                      t("Add as stop"),
                    ),
                ),
              );
            }),
          ),
          h(SheetNotes, { details: list.items.map((item) => item.place.details) }),
          stopsOnTheWay(list.kind) && h("p", { className: "hint" }, WATER_CAUTION),
        ),
      // Where from, one line under the list: "From: My location ▾".
      h(
        "label",
        { className: "nearest-from" },
        h("span", { "aria-hidden": "true" }, t("From:")),
        h("span", { className: "visually-hidden" }, t("Search from")),
        h(
          "select",
          { value: from, onChange: (event: { target: { value: string } }) => onFrom(event.target.value as NearestFrom) },
          ...fromOptions.map((option) => h("option", { key: option, value: option }, FROM_LABEL[option])),
        ),
      ),
      h("details", { className: "nearest-help" }, h("summary", null, t("How this works")), h("p", { className: "hint" }, NEAREST_HELP)),
    ),
  );
}
