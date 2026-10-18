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
  /**
   * Plan's "Change" on the start and the destination (Plan streamline, Stephen 2026-10-17): opens that point's
   * search box. Absent: no Change.
   */
  onChange?(index: number): void;
  /** Which rows have Change (the start, and the destination of a plan that is not a loop). */
  changeable?(index: number): boolean;
  /**
   * The point being changed and its search box, shown in that point's row in place of its place and buttons
   * (edit-route redesign, Stephen 2026-10-18: the box had opened above the list, away from the point).
   */
  editor?: { index: number; node: ReactElement } | null;
}

export function PointsList({ rows, warnings, onRemove, removeRef, onChange, changeable, editor }: PointsListProps): ReactElement {
  return h(
    "ol",
    { className: "points" },
    rows.map(({ role, place, coords }, index) => {
      const federal = warnings?.[index] ?? null;
      if (editor && editor.index === index) {
        return h("li", { key: index, className: "point-editing" }, h("span", { className: "point-name" }, role), editor.node);
      }
      const shown = place
        ? h(
            "span",
            { className: "point-place", title: `${place.label} (${coords})` },
            h("span", { className: "place-name" }, place.name),
            h("span", { className: "coords" }, coords),
          )
        : h("span", { className: "coords" }, coords);
      // The start and the destination: the place itself is the Change button (edit-route redesign), named
      // "Change Start: <place>" so its shown words are in its name.
      const change = onChange && changeable?.(index);
      return h(
        "li",
        { key: index, className: federal ? "point-on-federal" : undefined },
        h("span", { className: "point-name" }, role),
        change
          ? h(
              "button",
              { type: "button", className: "point-change", onClick: () => onChange(index), "aria-label": `Change ${role}: ${place ? place.name : coords}` },
              shown,
            )
          : shown,
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
