/**
 * The panel's "Show bike lanes on high-stress roads" switch (OWNER-DECISIONS
 * 275). Off unless the rider turned it on: a painted lane on an LTS 4 or
 * Avoid road is not drawn, not counted in the route's facility bar and not
 * called a bike lane in the route description (the owner: "Kenilworth avenue
 * is hillarious at having a bike lane on it."). Protected lanes and paths are
 * unaffected, as are the stress ratings. A button with role="switch" like the
 * High contrast switch, so a keyboard (Space or Enter) and a screen reader
 * (name, state, description) reach it. Written with createElement so a test
 * renders it.
 *
 * It is shown whether or not the stress map is there (the a11y review's SF4):
 * it changes the route's facility totals and description too, which a
 * screen-reader rider hears with the stress tiles down. With no overlay its
 * description says only what it changes then.
 */
import { createElement as h, type ReactElement } from "react";

export const HIGH_STRESS_LANES_LABEL = "Show bike lanes on high-stress roads";

/** Read on every focus, so kept short (under 150 characters; the salience review), in plain words (the a11y review's N2). */
export const HIGH_STRESS_LANES_HINT =
  "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads are hidden on the map and in the route. Protected lanes and paths always show.";

/** The description while the stress map is unavailable: the map has no lanes to hide then. */
export const HIGH_STRESS_LANES_NO_MAP_HINT =
  "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads are hidden in the route's facility totals and description.";

export function HighStressLanesSwitch({
  on,
  onChange,
  overlay = true,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  /** Whether the stress map is on the page (App's `stress === "available"`). */
  overlay?: boolean;
}): ReactElement {
  return h(
    "div",
    { className: "a11y-setting" },
    h(
      "button",
      {
        type: "button",
        role: "switch",
        id: "high-lanes-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "high-lanes-label",
        "aria-describedby": "high-lanes-hint",
        onClick: () => onChange(!on),
      },
      h("span", { id: "high-lanes-label", className: "switch-label" }, HIGH_STRESS_LANES_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: "high-lanes-hint" }, overlay ? HIGH_STRESS_LANES_HINT : HIGH_STRESS_LANES_NO_MAP_HINT),
  );
}
