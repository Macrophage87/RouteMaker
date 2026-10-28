/**
 * The map's info panel: what the "i" by the OpenStreetMap credit opens (Stephen 2026-10-19: "Put this text
 * in the info panel and also add more from the documentation"). Plan's how-to moved here out of the Plan
 * panel, so Plan scrolls less; a screen reader still hears it there (Planner.tsx). Then the documentation's
 * "In short", most important first, with links to the pages for the rest, then the credits.
 *
 * It is its own element in the attribution control, over MapLibre's credits (wrapCredits), not an
 * attribution entry: MapLibre sorts entries by length, so a shorter source credit would come first.
 */
import { searchLede } from "./sidebar.ts";
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

/** The documentation's short version (how-it-works.html, "In short"), one line each. */
export const INFO_POINTS: readonly string[] = [
  t("Every road is rated for traffic stress, from LTS 1 (comfortable for everyone) to LTS 4 (busy, fast traffic), plus 4.5 and Avoid for the worst roads."),
  t("Your ride type and the traffic slider decide how much extra distance a calmer road is worth."),
  t("Busy junctions cost extra too."),
  t("Real closures move a route. DC's planned-work permits never do."),
];

/** The panel's markup (our own constant, no rider text), before the credits. */
export const MAP_INFO: string = [
  `<p><strong>${t("Plan a route.")}</strong> ${searchLede(false)}</p>`,
  `<ul>${INFO_POINTS.map((point) => `<li>${point}</li>`).join("")}</ul>`,
  `<p>${t("More:")} ${DOCS_LINKS.map((link) => `<a href="${link.href}">${link.text}</a>`).join(" · ")}</p>`,
  // Which release this is, for Go and rides, where Plan's heading is out of sight (lib/appVersion.ts).
  versionSaid() ? `<p>${versionSaid()}.</p>` : "",
  `<p><strong>${t("Credits.")}</strong></p>`,
].join("");

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
  info.innerHTML = MAP_INFO;
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
