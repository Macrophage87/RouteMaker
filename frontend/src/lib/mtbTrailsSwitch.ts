/**
 * The Map layers sheet's "Mountain-bike trails" switch (OWNER-DECISIONS 454:
 * "Three map layers for everyone (every mode, signed out too), off until
 * clicked on: topo lines, climbs, mountain-bike trails."). This is the first of
 * the three; topo lines and climbs need data the tiles do not carry yet
 * (docs/MTB-TOPO-PLAN.md). Off unless the rider turned it on, and kept per
 * browser (stressStyle.js, setMtbTrails). It shows or hides the trails' own
 * not-for-routes line (452a) and changes no route. A button with
 * role="switch" like "Show bike lanes on high-stress roads", so a keyboard
 * (Space or Enter) and a screen reader (name, state, description) reach it.
 * Written with createElement so a test renders it.
 */
import { createElement as h, type ReactElement } from "react";
import { MTB_MIN_ZOOM } from "../stressStyle.js";

export const MTB_TRAILS_LABEL = "Mountain-bike trails";

/** Read on every focus, so kept short (under 150 characters), in plain words. */
export const MTB_TRAILS_HINT = `Natural-surface trails for mountain bikes, a thin grey dotted line from zoom ${MTB_MIN_ZOOM}. Not used for routes; Gravel and Mountain Goat may use them.`;

/** The description while the stress map, which carries the trails, is unavailable. */
export const MTB_TRAILS_NO_MAP_HINT = "Mountain-bike trails show with the stress map, which is unavailable for now.";

export function MtbTrailsSwitch({
  on,
  onChange,
  overlay = true,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  /** Whether the stress tiles, which carry the trails, are on the page (App's `stress === "available"`). */
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
        id: "mtb-trails-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "mtb-trails-label",
        "aria-describedby": "mtb-trails-hint",
        onClick: () => onChange(!on),
      },
      h("span", { id: "mtb-trails-label", className: "switch-label" }, MTB_TRAILS_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: "mtb-trails-hint" }, overlay ? MTB_TRAILS_HINT : MTB_TRAILS_NO_MAP_HINT),
  );
}
