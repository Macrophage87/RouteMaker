/**
 * The panel's "Accessibility" switch (OWNER-DECISIONS 208, 211, 212): on, the
 * stress colours are a colour-blind-friendly set, the lines and their casings
 * are drawn stronger, and the panel's borders and muted text are stronger too
 * (styles.css, `.a11y` on the page's root). Off unless the rider turned it on,
 * or the system asks for more contrast and the rider has not chosen.
 * Written with createElement so a test renders it (as stressLegend.ts).
 */
import { createElement as h, type ReactElement } from "react";
import { accessibilityOn, subscribePalette } from "../stressStyle.js";

export const ACCESSIBILITY_LABEL = "Accessibility";

export const ACCESSIBILITY_HINT =
  "Colour-blind-friendly stress colours, bolder lines, and stronger borders and text. Kept in this browser.";

export const ACCESSIBILITY_ADDRESS_NOTE = "The address (palette= in the link) chooses the stress colours; the rest still applies.";

export const ACCESSIBILITY_CONTRAST_NOTE = "On because your device asks for more contrast; turn it off here if you prefer.";

/** The class on the page's root that stylesheet rules for the switch hang from. */
export const ACCESSIBILITY_CLASS = "a11y";

export function AccessibilitySwitch({
  on,
  source,
  paletteFromAddress,
  onChange,
}: {
  on: boolean;
  /** What the state is down to: the rider's "chosen", the system's "contrast", or "default". */
  source: string;
  paletteFromAddress: boolean;
  onChange: (on: boolean) => void;
}): ReactElement {
  const notes = [
    on && source === "contrast" ? ACCESSIBILITY_CONTRAST_NOTE : "",
    paletteFromAddress ? ACCESSIBILITY_ADDRESS_NOTE : "",
  ].filter(Boolean);
  return h(
    "div",
    { className: "a11y-setting" },
    h(
      "button",
      {
        type: "button",
        role: "switch",
        id: "a11y-switch",
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": "a11y-label",
        "aria-describedby": "a11y-hint",
        onClick: () => onChange(!on),
      },
      h("span", { id: "a11y-label", className: "switch-label" }, ACCESSIBILITY_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: "a11y-hint" }, [ACCESSIBILITY_HINT, ...notes].join(" ")),
  );
}

/** The parts of a DOM element the root class uses. */
export interface ClassRoot {
  classList: { toggle(name: string, force: boolean): unknown };
}

/** Put the switch's class on `root` (or take it off). */
export function setRootClass(root: ClassRoot, on: boolean): void {
  root.classList.toggle(ACCESSIBILITY_CLASS, on);
}

/**
 * Keep `root`'s class in step with the switch, now and as it changes (the
 * rider's flip, or the system's request for more contrast with nothing
 * chosen). Returns the way to stop.
 */
export function followAccessibility(root: ClassRoot): () => void {
  setRootClass(root, accessibilityOn());
  return subscribePalette(() => setRootClass(root, accessibilityOn()));
}
