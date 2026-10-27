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
import { t } from "./i18n.ts";

export const HIGH_STRESS_LANES_LABEL = "Show bike lanes on high-stress roads";

/**
 * Read on every focus, so one short line (the salience review; the owner, 2026-10-12: "less wordy"), in plain
 * words (the a11y review's N2); the legend's facility hint (stressLegend.ts) says how each facility is drawn.
 */
export const HIGH_STRESS_LANES_HINT = "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads, on the map and in the route.";

/** The description while the stress map is unavailable: the map has no lanes to hide then. */
export const HIGH_STRESS_LANES_NO_MAP_HINT = "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads, in route totals and description.";

/**
 * The description on the Mass Ride map, which draws no lane, protected lane or path at any zoom
 * (OWNER-DECISIONS 417, 417a): "Protected lanes and paths always show" would be untrue there
 * (REBUILD-BUNDLE spec review S3), and the switch changes only the route's words.
 */
export const HIGH_STRESS_LANES_MASS_HINT = "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads, in the route's description only.";

export function HighStressLanesSwitch({
  on,
  onChange,
  overlay = true,
  massMap = false,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  /** Whether the stress map is on the page (App's `stress === "available"`). */
  overlay?: boolean;
  /** Whether the map is the Mass Ride's capacity map (App's `massMap`). */
  massMap?: boolean;
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
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? t("On") : t("Off")),
    ),
    h(
      "p",
      { className: "hint", id: "high-lanes-hint" },
      massMap ? HIGH_STRESS_LANES_MASS_HINT : overlay ? HIGH_STRESS_LANES_HINT : HIGH_STRESS_LANES_NO_MAP_HINT,
    ),
  );
}
