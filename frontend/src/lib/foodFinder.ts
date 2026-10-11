/**
 * The planner's "Find food" panel (lib/food.ts): a search box for a food or a name, where to
 * search (the map's view or the whole area), one persistent status line, and the results as a
 * numbered list whose numbers are the map's markers. Each result has Show on map and, with a
 * plan to add it to, Add as stop; a website where one is mapped. Written with createElement so a
 * test renders it (as nearestFinder.ts).
 *
 * Collapsed by default, beside "Find the nearest water, restroom or Metro". The status line is
 * always rendered and its words change (a live region inserted with its text is often not read).
 * Show more adds a page and moves the focus to the first new result, so a keyboard rider goes on
 * from where they were.
 */
import { createElement as h, useEffect, useRef, type ReactElement } from "react";
import { FOOD_DETOUR_NOTE, foodHowFar, foodKindText, FOOD_PAGE, type FoodResult, type FoodScope } from "./food.ts";

export const FOOD_SUMMARY = "Find food";
export const FOOD_HELP =
  "Search by food (crab, pizza, coffee, ice cream) or by a place's name. With a route shown, results are sorted by detour; Add as stop puts a place into your plan.";
export const FOOD_SCOPE_LABEL: Record<FoodScope, string> = {
  view: "In the map view",
  area: "Search the whole area",
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
  onAddStop: (result: FoodResult) => void;
  /** A fold of its own (the default), or the body alone, in the map's Food sheet (UI-CLEANUP), whose heading names it. */
  folded?: boolean;
}

export function FoodFinder(props: FoodFinderProps): ReactElement {
  const { query, onQuery, scope, onScope, onSearch, busy, status, results, total, onMore, canAddStop, onShow, onAddStop, folded = true } = props;
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
          "aria-label": "Find food",
          className: "food-search",
          onSubmit: (event: { preventDefault(): void }) => {
            event.preventDefault();
            onSearch();
          },
        },
        h("label", { htmlFor: "food-query", className: "place-search-label" }, "Food or name"),
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
          h("button", { type: "submit", className: "secondary", "aria-disabled": busy ? true : undefined }, "Search"),
        ),
        h(
          "fieldset",
          { className: "food-scope" },
          h("legend", null, "Where"),
          ...(["view", "area"] as const).map((option) =>
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
          h("h3", { id: "food-list-heading" }, "Places to eat"),
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
                  // The number is the map marker's.
                  h("strong", null, `${i + 1}. ${r.place.name}`),
                  ` ${foodKindText(r.place)}. ${foodHowFar(r)}`,
                  r.place.hours ? ` Hours as mapped: ${r.place.hours}.` : "",
                ),
                h(
                  "span",
                  { className: "actions" },
                  h(
                    "button",
                    { type: "button", className: "secondary", "aria-label": `Show on map: ${r.place.name}, marker ${i + 1}`, onClick: () => onShow(r) },
                    "Show on map",
                  ),
                  canAddStop &&
                    h(
                      "button",
                      { type: "button", className: "secondary", "aria-label": `Add as stop: ${r.place.name}`, onClick: () => onAddStop(r) },
                      "Add as stop",
                    ),
                  r.place.website &&
                    h(
                      "a",
                      { className: "food-web", href: r.place.website, target: "_blank", rel: "noopener noreferrer", "aria-label": `Website: ${r.place.name} (opens in a new tab)` },
                      "Website",
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
              `Show ${Math.min(FOOD_PAGE, total - shown)} more`,
            ),
          h("p", { className: "hint" }, anyDetour ? FOOD_DETOUR_NOTE : "From OpenStreetMap: check the hours before you count on them. No ratings."),
        ),
      h("p", { className: "hint", id: "food-help" }, FOOD_HELP),
    ),
  );
}
