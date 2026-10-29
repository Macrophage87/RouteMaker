/**
 * The panel's list of the plan's points: each one's role (Start, Stop 1, ...,
 * End), its place name when it has one with its street or neighbourhood (else its coordinates), a Mass Ride point's
 * federal-land warning, and a Remove button.
 * Written with createElement rather than JSX so that a test can render it with
 * react-dom/server under `node --test`, which reads TypeScript but not JSX
 * (MERGE-SEARCH re-check R16: a list that showed the coordinates where the
 * role belongs passed every test).
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { placeArea, type PointRow } from "./geocode.ts";
import { ICON_PATHS } from "./iconPaths.ts";
import { rowShift, type PointMover } from "./pointMover.ts";

/** The grip's description, read after its name (lib/pointMover.ts says the three ways). */
export const MOVE_HINT = "Drag, or press for Up and Down.";

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
  /**
   * Reordering the stops by hand (lib/pointMover.ts, Stephen 2026-10-18): a grip on each stop's row, with two stops
   * or more, as Best order. `slots`: each stop's row, in order. Absent: no grips.
   */
  mover?: PointMover | null;
  slots?: readonly number[];
}

export function PointsList({ rows, warnings, onRemove, removeRef, onChange, changeable, editor, mover, slots = [] }: PointsListProps): ReactElement {
  const grips = mover && slots.length >= 2 && !editor ? mover : null;
  const list = h(
    "ol",
    { className: grips?.drag ? "points points-dragging" : "points" },
    rows.map(({ role, place, coords }, index) => {
      const federal = warnings?.[index] ?? null;
      if (editor && editor.index === index) {
        return h("li", { key: index, className: "point-editing" }, h("span", { className: "point-name" }, role), editor.node);
      }
      // A named point: its street or neighbourhood under the name, its coordinates in the title only (P10: "38.9120,
      // -77.0390" told a rider nothing). A point not yet named shows its coordinates, all there is.
      const area = place ? placeArea(place) : "";
      const shown = place
        ? h(
            "span",
            { className: "point-place", title: `${place.label} (${coords})` },
            h("span", { className: "place-name" }, place.name),
            area ? h("span", { className: "place-area" }, area) : null,
          )
        : h("span", { className: "coords" }, coords);
      // The start and the destination: the place itself is the Change button (edit-route redesign), named
      // "Change Start: <place>" so its shown words are in its name.
      const change = onChange && changeable?.(index);
      const slot = grips ? slots.indexOf(index) : -1;
      const shift = slot >= 0 && grips?.drag ? rowShift(slot, grips.drag) : 0;
      const classes = [
        federal ? "point-on-federal" : "",
        slot >= 0 && grips?.drag?.from === slot ? "point-dragged" : "",
        slot >= 0 && grips?.moving === slot ? "point-moving" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const grip = grips && slot >= 0
        ? h(
            "button",
            {
              type: "button",
              className: "point-grip",
              "aria-label": `Move ${role}`,
              "aria-describedby": "point-move-hint",
              "aria-expanded": grips.moving === slot,
              ...grips.grip(slot),
            },
            h("svg", { className: "icon", width: 20, height: 20, viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", dangerouslySetInnerHTML: { __html: ICON_PATHS.grip } }),
          )
        : grips
          ? h("span", { className: "point-grip-space", "aria-hidden": "true" })
          : null;
      // Up, Down and Done in place of Remove, while the grip's press has them out (on a line of their own).
      const steps =
        grips && slot >= 0 && grips.moving === slot
          ? h(
              "span",
              { className: "point-steps" },
              slot > 0
                ? h("button", { type: "button", className: "link", ref: (b: HTMLButtonElement | null) => grips.stepRef(slot, -1, b), onClick: () => grips.step(slot, -1), "aria-label": `Move ${role} up` }, "Up")
                : null,
              slot < slots.length - 1
                ? h("button", { type: "button", className: "link", ref: (b: HTMLButtonElement | null) => grips.stepRef(slot, 1, b), onClick: () => grips.step(slot, 1), "aria-label": `Move ${role} down` }, "Down")
                : null,
              h("button", { type: "button", className: "link", onClick: () => grips.done(slot) }, "Done"),
            )
          : null;
      return h(
        "li",
        { key: index, className: classes || undefined, style: shift ? { transform: `translateY(${shift}px)` } : undefined },
        grip,
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
        steps ??
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
  return grips
    ? h(Fragment, null, list, h("span", { id: "point-move-hint", hidden: true }, MOVE_HINT))
    : list;
}
