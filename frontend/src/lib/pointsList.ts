/**
 * The panel's list of the plan's points: each one's role (Start, Stop 1, ...,
 * End), its place name when it has one, its coordinates, and a Remove button.
 * Written with createElement rather than JSX so that a test can render it with
 * react-dom/server under `node --test`, which reads TypeScript but not JSX
 * (MERGE-SEARCH re-check R16: a list that showed the coordinates where the
 * role belongs passed every test).
 */
import { createElement as h, type ReactElement } from "react";
import type { PointRow } from "./geocode.ts";

export interface PointsListProps {
  rows: readonly PointRow[];
  onRemove(index: number): void;
  /** Each Remove button, for the focus after a removal (App.tsx). */
  removeRef(index: number, button: HTMLButtonElement | null): void;
}

export function PointsList({ rows, onRemove, removeRef }: PointsListProps): ReactElement {
  return h(
    "ol",
    { className: "points" },
    rows.map(({ role, place, coords }, index) =>
      h(
        "li",
        { key: index },
        h("span", { className: "point-name" }, role),
        place
          ? h(
              "span",
              { className: "point-place", title: `${place.label} (${coords})` },
              h("span", { className: "place-name" }, place.name),
              h("span", { className: "coords" }, coords),
            )
          : h("span", { className: "coords" }, coords),
        h(
          "button",
          {
            type: "button",
            className: "link",
            ref: (button: HTMLButtonElement | null) => removeRef(index, button),
            onClick: () => onRemove(index),
            "aria-label": `Remove ${role}`,
          },
          "Remove",
        ),
      ),
    ),
  );
}
