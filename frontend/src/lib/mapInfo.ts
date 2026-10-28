/**
 * The map's info panel: what the "i" by the OpenStreetMap credit opens (Stephen 2026-10-19: "Put this text
 * in the info panel and also add more from the documentation"). Two short lines since P8 (where to start, what
 * the line colors mean), the links to the documentation, which has the rest, then the credits.
 *
 * It is its own element in the attribution control, over MapLibre's credits (wrapCredits), not an
 * attribution entry: MapLibre sorts entries by length, so a shorter source credit would come first.
 */
import { ACCESS_SENTENCE_WHERE } from "./accessMode.ts";
import { looksLikePhone } from "./startOnComputer.ts";
import { t } from "./i18n.ts";
import { STRESS_PAGE } from "./stressLegend.ts";
import { versionSaid } from "./appVersion.ts";

/** The rider-facing documentation pages (public/about/), in the hub's order; Acknowledgements is in the credits. */
export const DOCS_LINKS: ReadonlyArray<{ href: string; text: string }> = [
  { href: "/about/using.html", text: t("Using RouteMaker") },
  { href: "/about/how-it-works.html", text: t("How RouteMaker works") },
  { href: "/about/ride-types.html", text: t("Ride types") },
  { href: STRESS_PAGE, text: t("Stress ratings") },
  { href: "/about/routing.html", text: t("Routing") },
  { href: "/about/architecture.html", text: t("Architecture") },
];

/**
 * The panel's two lines (P8, "Help on a phone"): where to start, and what the line colors mean. The rest (how
 * stress is rated, what the traffic slider weighs, closures) is in the documentation the links open. On a phone
 * the words are a finger's (`touch`, lib/startOnComputer.ts looksLikePhone); a computer keeps its click.
 */
export function infoLines(touch: boolean): { start: string; colors: string } {
  return {
    start: touch ? t("Search or tap a chip, then Start ride.") : t("Search, pick a chip or click the map, then Start ride."),
    colors: t("Line colors: green calm → red busy."),
  };
}

/**
 * The panel's markup (our own constant, no rider text), before the credits. The accessibility mode sentence is
 * shown on a computer and, on a phone, said to a screen reader only. The arrow is drawn, and read as "to".
 */
export function mapInfo(touch: boolean): string {
  const { start, colors } = infoLines(touch);
  const access = t(ACCESS_SENTENCE_WHERE);
  const [arrowBefore, arrowAfter] = colors.split("→");
  const colorLine = arrowAfter === undefined ? colors : `${arrowBefore}<span aria-hidden="true">→</span><span class="visually-hidden">${t("to")}</span>${arrowAfter}`;
  return [
    `<p><strong>${t("Where to?")}</strong> ${start}</p>`,
    `<p>${colorLine}</p>`,
    touch ? `<p class="visually-hidden">${access}</p>` : `<p>${access}</p>`,
    `<p>${t("More:")} ${DOCS_LINKS.map((link) => `<a href="${link.href}">${link.text}</a>`).join(" · ")}</p>`,
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
export function wrapCredits(control: HTMLElement | null, doc: WrapDocument = document, touch = looksLikePhone()): boolean {
  const inner = control?.querySelector(".maplibregl-ctrl-attrib-inner");
  if (!control || !inner || control.querySelector(".map-info-body")) return false;
  const body = doc.createElement("div");
  body.className = "map-info-body";
  const info = doc.createElement("div");
  info.className = "map-info";
  info.innerHTML = mapInfo(touch);
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
