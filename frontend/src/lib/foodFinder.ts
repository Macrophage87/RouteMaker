/**
 * The planner's "Find food" panel (lib/food.ts): a search box for a food or a name (blank for all
 * food), where to search (near you, the default, or the map's view), one persistent status line, and the results as a
 * numbered list whose numbers are the map's markers. Each result has Show on map and, with a
 * plan to add it to, Add as stop; a website where one is mapped. Written with createElement so a
 * test renders it (as nearestFinder.ts).
 *
 * Collapsed by default, beside "Find the nearest water, restroom or Metro". The status line is
 * always rendered and its words change (a live region inserted with its text is often not read).
 * Show more adds a page and moves the focus to the first new result, so a keyboard rider goes on
 * from where they were.
 */
import { placeLetter } from "./letteredPlaces.ts";
import { createElement as h, useEffect, useRef, type ReactElement } from "react";
import { FOOD_DETOUR_NOTE, foodHoursText, foodHowFar, foodKindText, FOOD_PAGE, isFarmFood, type FoodResult, type FoodScope } from "./food.ts";
import { ICON_PATHS } from "./iconPaths.ts";
import { t } from "./i18n.ts";

export const FOOD_SUMMARY = t("Find food");
export const FOOD_HELP =
  t("Search by food (crab, pizza, coffee) or a place's name, or leave it blank for all food. With a route shown, results are sorted by detour; Add as stop puts a place into your plan.");
export const FOOD_SCOPE_LABEL: Record<FoodScope, string> = {
  near: t("Near you"),
  view: t("In the map view"),
};

export interface FoodFinderProps {
  query: string;
  onQuery: (query: string) => void;
  scope: FoodScope;
  onScope: (scope: FoodScope) => void;
  onSearch: () => void;
  busy: boolean;
  status: string;
  /** The results shown (a page or more of them), in order; null before a search. */
  results: readonly FoodResult[] | null;
  /** How many matched in all. */
  total: number;
  onMore: () => void;
  /** Whether there is a plan to add a stop to. */
  canAddStop: boolean;
  onShow: (result: FoodResult) => void;
  /** Go: Ride here, the place as the destination (the owner's lettered places of 2026-10-11). */
  onRide?: (result: FoodResult) => void;
  onAddStop: (result: FoodResult) => void;
  /** A fold of its own (the default), or the body alone, in the map's Food sheet (UI-CLEANUP), whose heading names it. */
  folded?: boolean;
  /** The list's heading: Places to eat (the default), or Grocery stores for the Grocery chip's list (lib/grocery.ts). */
  heading?: string;
}

export function FoodFinder(props: FoodFinderProps): ReactElement {
  const { query, onQuery, scope, onScope, onSearch, busy, status, results, total, onMore, canAddStop, onShow, onAddStop, onRide, folded = true, heading = t("Places to eat") } = props;
  const list = useRef<HTMLOListElement | null>(null);
  // After Show more: the index of the first new result, whose first button takes the focus.
  const focusFrom = useRef<number | null>(null);
  const shown = results?.length ?? 0;
  useEffect(() => {
    const from = focusFrom.current;
    if (from === null || !list.current) return;
    focusFrom.current = null;
    list.current.querySelectorAll("li")[from]?.querySelector("button")?.focus();
  }, [shown]);
  const anyDetour = results?.some((r) => r.detour) ?? false;
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
          "aria-label": t("Find food"),
          className: "food-search",
          onSubmit: (event: { preventDefault(): void }) => {
            event.preventDefault();
            onSearch();
          },
        },
        h("label", { htmlFor: "food-query", className: "place-search-label" }, t("Food or name")),
        h(
          "div",
          { className: "place-search-row" },
          h("input", {
            id: "food-query",
            type: "search",
            value: query,
            autoComplete: "off",
            enterKeyHint: "search",
            "aria-describedby": "food-help",
            onChange: (event: { target: { value: string } }) => onQuery(event.target.value),
          }),
          h("button", { type: "submit", className: "secondary", "aria-disabled": busy ? true : undefined }, t("Search")),
        ),
        h(
          "fieldset",
          { className: "food-scope" },
          h("legend", null, t("Where")),
          ...(["near", "view"] as const).map((option) =>
            h(
              "label",
              { key: option, className: "toggle" },
              h("input", { type: "radio", name: "food-scope", value: option, checked: option === scope, onChange: () => onScope(option) }),
              FOOD_SCOPE_LABEL[option],
            ),
          ),
        ),
      ),
      h("p", { className: "hint food-status", role: "status" }, status),
      results !== null &&
        results.length > 0 &&
        h(
          "div",
          { className: "nearest-list food-list" },
          h("h3", { id: "food-list-heading" }, heading),
          h(
            "ol",
            // role="list": WebKit drops a list's role once its bullets are styled away.
            { role: "list", "aria-labelledby": "food-list-heading", ref: list },
            ...results.map((r, i) =>
              h(
                "li",
                { key: r.place.id },
                h(
                  "span",
                  null,
                  // The letter is the map marker's (lib/letteredPlaces.ts).
                  h("strong", null, `${placeLetter(i)}. ${r.place.name}`),
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
                  foodHoursText(r.place) ? ` ${foodHoursText(r.place)}` : "",
                ),
                h(
                  "span",
                  { className: "actions" },
                  h(
                    "button",
                    { type: "button", className: "secondary", "aria-label": t("Show on map: {place}, marker {letter}", { place: r.place.name, letter: placeLetter(i) }), onClick: () => onShow(r) },
                    t("Show on map"),
                  ),
                  onRide &&
                    h(
                      "button",
                      { type: "button", className: "secondary", "aria-label": t("Ride here: {place}", { place: r.place.name }), onClick: () => onRide(r) },
                      t("Ride here"),
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
          shown < total &&
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
          h("p", { className: "hint" }, anyDetour ? FOOD_DETOUR_NOTE : t("From OpenStreetMap: check the hours before you count on them. No ratings.")),
        ),
      h("p", { className: "hint", id: "food-help" }, FOOD_HELP),
    ),
  );
}
