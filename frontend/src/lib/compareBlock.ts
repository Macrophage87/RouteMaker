/**
 * Plan's Keep to compare (lib/compareRoutes.ts), as the plan panel shows it (app/PlanPanel.tsx): the one button while
 * nothing is kept; with a route kept, the two side by side in a small table, then Use kept route and Stop comparing.
 * The better side of a row is in bold and says so out of sight. Written with createElement so a test renders it.
 */
import { createElement as h, type ReactElement } from "react";
import {
  BETTER_SAID,
  COMPARE_CAPTION,
  EDITED_KEPT_HINT,
  KEEP_LABEL,
  KEPT_HEADING,
  NOW_HEADING,
  SAME_AS_KEPT,
  STOP_COMPARING_LABEL,
  USE_KEPT_LABEL,
  type CompareRow,
} from "./compareRoutes.ts";

/** The block's state and its three actions. */
export interface PlanCompare {
  /** The table's rows, kept first; null where there is nothing to compare yet (the route shown is the kept one). */
  rows: readonly CompareRow[] | null;
  /** A route is kept. */
  kept: boolean;
  /** The plan changed since the route shown was drawn: nothing can be kept until it is routed. */
  edited: boolean;
  onKeep: () => void;
  onUse: () => void;
  onStop: () => void;
}

function cell(text: string, better: boolean): ReactElement {
  if (!better) return h("td", null, text);
  return h("td", { className: "plan-compare-better" }, text, h("span", { className: "visually-hidden" }, `, ${BETTER_SAID}`));
}

function button(label: string, onClick: () => void, className = "secondary"): ReactElement {
  return h("button", { type: "button", className, onClick }, label);
}

/** The block, or null (nothing kept and the plan changed: nothing to keep until it is routed). */
export function compareBlock(compare: PlanCompare): ReactElement | null {
  if (!compare.kept) {
    if (compare.edited) return null;
    return h("div", { className: "plan-compare" }, button(KEEP_LABEL, compare.onKeep, "secondary plan-keep"));
  }
  const rows = compare.rows;
  const table = rows
    ? h(
        "table",
        { className: "plan-compare-table" },
        h("caption", { className: "visually-hidden" }, COMPARE_CAPTION),
        h("thead", null, h("tr", null, h("td"), h("th", { scope: "col" }, KEPT_HEADING), h("th", { scope: "col" }, NOW_HEADING))),
        h(
          "tbody",
          null,
          ...rows.map((row) =>
            h("tr", { key: row.label }, h("th", { scope: "row" }, row.label), cell(row.kept, row.better === "kept"), cell(row.now, row.better === "now")),
          ),
        ),
      )
    : h("p", { className: "hint" }, compare.edited ? EDITED_KEPT_HINT : SAME_AS_KEPT);
  return h(
    "div",
    { className: "plan-compare" },
    table,
    h("div", { className: "plan-compare-actions" }, rows ? button(USE_KEPT_LABEL, compare.onUse) : null, button(STOP_COMPARING_LABEL, compare.onStop)),
  );
}
