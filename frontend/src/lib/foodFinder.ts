/**
 * The planner's "Find food" panel (lib/food.ts): a search box for a food or a name (blank for all
 * food), the cuisine chips, one persistent status line, and the results as a lettered list whose
 * letters are the map's markers. Each result has Show on map and, with a plan to add it to, Add as
 * stop; a website where one is mapped. Written with createElement so a test renders it (as
 * nearestFinder.ts).
 *
 * Results first (the 2026-10-28 audit, P7: "Food's first result starts at the bottom edge of the
 * screen"): the search, one row of chips, then the list. A search is near you; once the rider moves
 * the map, a "Search this area" button searches the map's view instead (it was two radios, always
 * shown). The count sentence ("15,663 places to eat…") is for screen readers only once a list shows.
 *
 * The status line is always rendered and its words change (a live region inserted with its text is
 * often not read). Show more adds a page and moves the focus to the first new result, so a keyboard
 * rider goes on from where they were.
 */
import { placeLetter, SHOW_ALL_ON_MAP } from "./letteredPlaces.ts";
import { createElement as h, useEffect, useRef, useState, type ReactElement, type ReactNode } from "react";
import { FOOD_DETOUR_METHOD, FOOD_DETOUR_NOTE, foodHoursText, foodHowFar, foodKindText, FOOD_PAGE, isFarmFood, type FoodResult } from "./food.ts";
import { ICON_PATHS } from "./iconPaths.ts";
import { t } from "./i18n.ts";

export const FOOD_SUMMARY = t("Search places to eat");
/** On screen, short (the audit's P7); FOOD_HELP_MORE goes on for screen readers. */
export const FOOD_HELP = t("Search a food or a name; blank shows all.");
export const FOOD_HELP_MORE = t("With a route shown, results are sorted by detour; Add as stop puts a place into your plan.");
export const FOOD_PLACEHOLDER = t("Search food or a name");
export const FOOD_SEARCH_AREA = t("Search this area");

/**
 * How many of a page show before its Show more (the owner, 2026-10-28: lists show the nearest few, the rest behind
 * Show more): what fits one phone screen in the Food popup. The page is still FOOD_PAGE, its letters on the map.
 */
export const FOOD_FIRST = 4;

/** How many of the results show: the first few until the rest of the page is asked for, then all found so far. */
export function foodRowsShown(found: number, rest: boolean): number {
  return rest ? found : Math.min(found, FOOD_FIRST);
}

export interface FoodFinderProps {
  query: string;
  onQuery: (query: string) => void;
  onSearch: () => void;
  /** Search the map's view: offered (areaMoved) once the rider has moved the map since the list was found. */
  onSearchArea?: () => void;
  areaMoved?: boolean;
  /** The cuisine chips (app/Sheets.tsx FoodChips), under the search box. */
  chips?: ReactNode;
  busy: boolean;
  status: string;
  /** The results shown (a page or more of them), in order; null before a search. */
  results: readonly FoodResult[] | null;
  /** How many matched in all. */
  total: number;
  onMore: () => void;
  /** The rest of the page shown (its Show more): how many rows show now, for the status line to say. */
  onRest?: (shown: number) => void;
  /** Whether there is a plan to add a stop to. */
  canAddStop: boolean;
  onShow: (result: FoodResult) => void;
  /** Show all on map (Stephen 2026-10-29): every place found, named on the map, framed together. Absent: no button. */
  onShowAll?: () => void;
  /** Go: Ride here, the place as the destination (the owner's lettered places of 2026-10-11). */
  onRide?: (result: FoodResult) => void;
  onAddStop: (result: FoodResult) => void;
  /** A fold of its own (the default), or the body alone, in the map's Food sheet (UI-CLEANUP), whose heading names it. */
  folded?: boolean;
  /** The hours are said for this moment (lib/openingHours.ts); the time now by default. */
  at?: Date;
  /** The list's heading: Places to eat (the default), or Grocery stores for the Grocery chip's list (lib/grocery.ts). */
  heading?: string;
}

export function FoodFinder(props: FoodFinderProps): ReactElement {
  const { query, onQuery, onSearch, onSearchArea, areaMoved = false, chips, busy, status, results, total, onMore, onRest, canAddStop, onShow, onShowAll, onAddStop, onRide, folded = true, heading = t("Places to eat") } = props;
  const at = props.at ?? new Date();
  const list = useRef<HTMLOListElement | null>(null);
  // After Show more: the index of the first new result, whose first button takes the focus.
  const focusFrom = useRef<number | null>(null);
  const found = results?.length ?? 0;
  // The rest of the page, behind Show more until asked for; a new search starts at the first few again.
  const [rest, setRest] = useState(false);
  const firstId = results?.[0]?.place.id;
  useEffect(() => setRest(false), [firstId, total]);
  const shown = foodRowsShown(found, rest);
  useEffect(() => {
    const from = focusFrom.current;
    if (from === null || !list.current) return;
    focusFrom.current = null;
    list.current.querySelectorAll("li")[from]?.querySelector("button")?.focus();
  }, [shown]);
  const anyDetour = results?.some((r) => r.detour) ?? false;
  // With a list on screen, its count sentence is heard, not shown: the list is what it counts.
  const statusHidden = shown > 0 && !busy;
  const wrap = (body: ReactElement) =>
    folded ? h("details", { className: "fold food" }, h("summary", null, FOOD_SUMMARY), body) : h("div", { className: "food food-sheet" }, body);
  return wrap(
    h(
      "div",
      { className: "fold-body" },
      h(
        "form",
        {
          role: "search",
          "aria-label": FOOD_SUMMARY,
          className: "food-search",
          onSubmit: (event: { preventDefault(): void }) => {
            event.preventDefault();
            onSearch();
          },
        },
        h("label", { htmlFor: "food-query", className: "visually-hidden" }, t("Food or name")),
        h(
          "div",
          { className: "place-search-row" },
          h("input", {
            id: "food-query",
            type: "search",
            value: query,
            placeholder: FOOD_PLACEHOLDER,
            autoComplete: "off",
            enterKeyHint: "search",
            "aria-describedby": "food-help",
            onChange: (event: { target: { value: string } }) => onQuery(event.target.value),
          }),
          h("button", { type: "submit", className: "secondary", "aria-disabled": busy ? true : undefined }, t("Search")),
        ),
      ),
      chips ?? null,
      areaMoved && onSearchArea && h("button", { type: "button", className: "secondary food-area", "aria-disabled": busy ? true : undefined, onClick: onSearchArea }, FOOD_SEARCH_AREA),
      h("p", { className: statusHidden ? "hint food-status visually-hidden" : "hint food-status", role: "status" }, status),
      results !== null &&
        results.length > 1 &&
        onShowAll &&
        h("button", { type: "button", className: "secondary show-all", onClick: onShowAll }, SHOW_ALL_ON_MAP),
      results !== null &&
        results.length > 0 &&
        h(
          "div",
          { className: "nearest-list food-list" },
          h("h3", { id: "food-list-heading", className: "visually-hidden" }, heading),
          h(
            "ol",
            // role="list": WebKit drops a list's role once its bullets are styled away.
            { role: "list", "aria-labelledby": "food-list-heading", ref: list },
            ...results.slice(0, shown).map((r, i) =>
              h(
                "li",
                { key: r.place.id },
                h(
                  "span",
                  null,
                  // The map's marker shows the name (Stephen 2026-10-29: "Named, not lettered"); the letter, its key's, is heard.
                  h("strong", null, h("span", { className: "visually-hidden" }, `${placeLetter(i)}. `), r.place.name),
                  // A farm stand or market has the apple (decorative: its kind is in the words beside it).
                  isFarmFood(r.place.kind) &&
                    h("svg", {
                      className: "icon food-apple",
                      width: 16,
                      height: 16,
                      viewBox: "0 0 24 24",
                      fill: "none",
                      stroke: "currentColor",
                      strokeWidth: 2,
                      "aria-hidden": "true",
                      focusable: "false",
                      dangerouslySetInnerHTML: { __html: ICON_PATHS.apple },
                    }),
                  ` ${foodKindText(r.place)}. ${foodHowFar(r)}`,
                  foodHoursText(r.place, at) ? ` ${foodHoursText(r.place, at)}` : "",
                ),
                h(
                  "span",
                  { className: "actions" },
                  // Go's one main action first and filled, the rest plain after it (the 2026-10-29 review).
                  onRide &&
                    h(
                      "button",
                      { type: "button", className: "ride-here", "aria-label": t("Ride here: {place}", { place: r.place.name }), onClick: () => onRide(r) },
                      t("Ride here"),
                    ),
                  h(
                    "button",
                    { type: "button", className: "secondary", "aria-label": t("Show on map: {place}, marker {letter}", { place: r.place.name, letter: placeLetter(i) }), onClick: () => onShow(r) },
                    t("Show on map"),
                  ),
                  canAddStop &&
                    h(
                      "button",
                      { type: "button", className: "secondary", "aria-label": t("Add as stop: {place}", { place: r.place.name }), onClick: () => onAddStop(r) },
                      t("Add as stop"),
                    ),
                  r.place.website &&
                    h(
                      "a",
                      { className: "food-web", href: r.place.website, target: "_blank", rel: "noopener noreferrer", "aria-label": t("Website: {place} (opens in a new tab)", { place: r.place.name }) },
                      t("Website"),
                    ),
                ),
              ),
            ),
          ),
          // The rest of the page found (its letters already on the map), then the next page.
          shown < found
            ? h(
                "button",
                {
                  type: "button",
                  className: "secondary food-more",
                  onClick: () => {
                    focusFrom.current = shown;
                    setRest(true);
                    onRest?.(found);
                  },
                },
                t("Show {count} more", { count: found - shown }),
              )
            : shown < total &&
                h(
                  "button",
                  {
                    type: "button",
                    className: "secondary food-more",
                    onClick: () => {
                      focusFrom.current = shown;
                      onMore();
                    },
                  },
                  t("Show {count} more", { count: Math.min(FOOD_PAGE, total - shown) }),
                ),
          anyDetour
            ? h("p", { className: "hint" }, h("span", { "aria-hidden": "true" }, FOOD_DETOUR_NOTE), h("span", { className: "visually-hidden" }, FOOD_DETOUR_METHOD))
            : h("p", { className: "hint" }, t("From OpenStreetMap: check the hours before you count on them. No ratings.")),
        ),
      h("p", { className: "hint", id: "food-help" }, FOOD_HELP, h("span", { className: "visually-hidden" }, ` ${FOOD_HELP_MORE}`)),
    ),
  );
}
