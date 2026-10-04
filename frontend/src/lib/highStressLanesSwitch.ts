/**
 * The panel's "Show bike lanes on high-stress roads" switch (OWNER-DECISIONS
 * 275). Off unless the rider turned it on: a painted lane on an LTS 4 or
 * Avoid road is not drawn, not counted in the route's facility bar and not
 * called a bike lane in the route description ("Kenilworth Ave's painted lane
 * is hilarious"). Protected lanes and paths are unaffected, as are the stress
 * ratings. A button with role="switch" like the Accessibility switch, so a
 * keyboard (Space or Enter) and a screen reader (name, state, description)
 * reach it. Written with createElement so a test renders it.
 */
import { createElement as h, type ReactElement } from "react";

export const HIGH_STRESS_LANES_LABEL = "Show bike lanes on high-stress roads";

/** Read on every focus, so kept short (under 150 characters; the salience review). */
export const HIGH_STRESS_LANES_HINT =
  "Painted lanes on LTS 4 and Avoid roads are hidden on the map and in the route by default. Protected lanes and paths always show.";

export function HighStressLanesSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }): ReactElement {
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
    h("p", { className: "hint", id: "high-lanes-hint" }, HIGH_STRESS_LANES_HINT),
  );
}
