/**
 * The map's info panel: what the "i" by the OpenStreetMap credit opens (Stephen 2026-10-19: "Put this text
 * in the info panel and also add more from the documentation"). Since 2026-11-06 one big button to the help
 * guides instead of the text, then the credits.
 *
 * It is its own element in the attribution control, over MapLibre's credits (wrapCredits), not an
 * attribution entry: MapLibre sorts entries by length, so a shorter source credit would come first.
 */
import { ACCESS_SENTENCE_WHERE } from "./accessMode.ts";
import { t } from "./i18n.ts";
import { versionSaid } from "./appVersion.ts";

/** The help guides' first page; its menu leads to the rest (How it works, Ride types, Stress ratings, ...). */
export const GUIDES_PAGE = "/about/using.html";

/**
 * The panel's markup (our own constant, no rider text), before the credits: one big button to the help guides
 * (Stephen 2026-11-06: "Put a big button to the help files in help as opposed to the wall of text"), the release
 * for Go and rides, then the credits. The accessibility mode sentence is said to a screen reader only.
 */
export function mapInfo(): string {
  return [
    `<p><a class="map-info-guides" href="${GUIDES_PAGE}">${t("Using RouteMaker")}</a></p>`,
    `<p class="visually-hidden">${t(ACCESS_SENTENCE_WHERE)}</p>`,
    // Which release this is, for Go and rides, where Plan's heading is out of sight (lib/appVersion.ts).
    versionSaid() ? `<p>${versionSaid()}.</p>` : "",
    `<p><strong>${t("Credits.")}</strong></p>`,
  ].join("");
}

/** The parts of the DOM wrapCredits touches. */
export interface WrapDocument {
  createElement(tag: "div"): HTMLDivElement;
}

/**
 * Put the info panel over MapLibre's credits, both in one body that shows only while the "i" is open
 * and scrolls as one (styles.css). MapLibre keeps its own reference to the credits' element and only
 * replaces its children, so moving it into the body is safe. Whether it did.
 */
export function wrapCredits(control: HTMLElement | null, doc: WrapDocument = document): boolean {
  const inner = control?.querySelector(".maplibregl-ctrl-attrib-inner");
  if (!control || !inner || control.querySelector(".map-info-body")) return false;
  const body = doc.createElement("div");
  body.className = "map-info-body";
  const info = doc.createElement("div");
  info.className = "map-info";
  info.innerHTML = mapInfo();
  inner.replaceWith(body);
  body.append(info, inner);
  // The "i" says what it is (Stephen 2026-10-21, "Label the (i)"): the docs are behind it.
  const button = control.querySelector(".maplibregl-ctrl-attrib-button");
  if (button) {
    button.textContent = t("Help");
    // And whether it is open (the v0.10.1 end review): MapLibre's class says so, set by a tap, the map's first drag,
    // collapseCredits or a ride's start (MapView.tsx), so the button follows the class, not its own clicks.
    const sync = () => helpExpanded(control, button);
    sync();
    if (typeof MutationObserver !== "undefined") new MutationObserver(sync).observe(control, { attributes: true, attributeFilter: ["class"] });
  }
  return true;
}

/** The parts of the control and its button helpExpanded touches. */
export interface HelpParts {
  control: { classList: { contains(name: string): boolean } };
  button: { setAttribute(name: string, value: string): void };
}

/** Set the Help button's aria-expanded from whether the panel shows (MapLibre's maplibregl-compact-show). */
export function helpExpanded(control: HelpParts["control"], button: HelpParts["button"]): void {
  button.setAttribute("aria-expanded", String(control.classList.contains("maplibregl-compact-show")));
}
