/**
 * The panel's list of the plan's points: each one's role (Start, Stop 1, ...,
 * End), its place name when it has one, its coordinates, a Mass Ride point's
 * federal-land warning, and a Remove button.
 * Written with createElement rather than JSX so that a test can render it with
 * react-dom/server under `node --test`, which reads TypeScript but not JSX
 * (MERGE-SEARCH re-check R16: a list that showed the coordinates where the
 * role belongs passed every test).
 */
import { createElement as h, type ReactElement } from "react";
import type { PointRow } from "./geocode.ts";

export interface PointsListProps {
  rows: readonly PointRow[];
  /**
   * A Mass Ride's points on federal land: each row's warning (lib/federalStops.ts stopWarningShort,
   * item 239), or null; absent elsewhere.
   */
  warnings?: ReadonlyArray<string | null>;
  onRemove(index: number): void;
  /** Each Remove button, for the focus after a removal (App.tsx). */
  removeRef(index: number, button: HTMLButtonElement | null): void;
}

export function PointsList({ rows, warnings, onRemove, removeRef }: PointsListProps): ReactElement {
  return h(
    "ol",
    { className: "points" },
    rows.map(({ role, place, coords }, index) => {
      const federal = warnings?.[index] ?? null;
      return h(
        "li",
        { key: index, className: federal ? "point-on-federal" : undefined },
        h("span", { className: "point-name" }, role),
        place
          ? h(
              "span",
              { className: "point-place", title: `${place.label} (${coords})` },
              h("span", { className: "place-name" }, place.name),
              h("span", { className: "coords" }, coords),
            )
          : h("span", { className: "coords" }, coords),
        // On its own line, after the place and before Remove, so it is read with the point it is about
        // (item 239: a stop on federal land, in the stop list as well as the map and the description).
        federal ? h("span", { className: "point-federal" }, federal) : null,
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
      );
    }),
  );
}
