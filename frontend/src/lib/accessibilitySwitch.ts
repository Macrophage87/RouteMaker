/**
 * The panel's "High contrast" switch (OWNER-DECISIONS 208, 211, 212; renamed from
 * "Accessibility" by 384, whose wording drops any disability word; the identifiers, the
 * storage key and the palette= link value keep their names): on, the
 * stress colours are a colour-blind-friendly set, the lines and their casings
 * are drawn stronger, and the panel's borders and muted text are stronger too
 * (styles.css, `.a11y` on the page's root). Off unless the rider turned it on,
 * or the system asks for more contrast and the rider has not chosen.
 * Written with createElement so a test renders it (as stressLegend.ts).
 */
import { createElement as h, type ReactElement } from "react";
import { accessibilityOn, subscribePalette } from "../stressStyle.js";
import { t } from "./i18n.ts";

export const ACCESSIBILITY_LABEL = t("High contrast");

export const ACCESSIBILITY_HINT =
  t("Bolder lines, stronger borders and text, and colors that don't rely on red and green. Kept in this browser.");

export const ACCESSIBILITY_ADDRESS_NOTE = t("The address (palette= in the link) chooses the stress colors; the rest still applies.");

export const ACCESSIBILITY_CONTRAST_NOTE = t("On because your device asks for more contrast; turn it off here if you prefer.");

/** The class on the page's root that stylesheet rules for the switch hang from. */
export const ACCESSIBILITY_CLASS = "a11y";

export function AccessibilitySwitch({
  idBase = "a11y",
  on,
  source,
  paletteFromAddress,
  onChange,
  hintHidden = false,
}: {
  /**
   * The ids' stem: "a11y" (a11y-switch, a11y-label, a11y-hint) in the Map layers sheet, another in the
   * Settings sheet, because both sheets are in the page at once and an id must be unique (384).
   */
  idBase?: string;
  on: boolean;
  /** What the state is down to: the rider's "chosen", the system's "contrast", or "default". */
  source: string;
  paletteFromAddress: boolean;
  onChange: (on: boolean) => void;
  /** Settings keeps the explanation behind an (i) button: hidden from view, still the switch's description. */
  hintHidden?: boolean;
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
        id: `${idBase}-switch`,
        className: "switch",
        "aria-checked": on,
        "aria-labelledby": `${idBase}-label`,
        "aria-describedby": `${idBase}-hint`,
        onClick: () => onChange(!on),
      },
      h("span", { id: `${idBase}-label`, className: "switch-label" }, ACCESSIBILITY_LABEL),
      h("span", { className: "switch-state", "aria-hidden": "true" }, on ? "On" : "Off"),
    ),
    h("p", { className: "hint", id: `${idBase}-hint`, hidden: hintHidden }, [ACCESSIBILITY_HINT, ...notes].join(" ")),
    // Behind the (i), why the state is what it is stays in view (it is in the description too).
    hintHidden && notes.length > 0 ? h("p", { className: "hint a11y-state-note", "aria-hidden": "true" }, notes.join(" ")) : null,
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
