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
import { STRESS_PAGE } from "./stressLegend.ts";

/** The rider-facing documentation pages (public/about/), in the hub's order; Acknowledgements is in the credits. */
export const DOCS_LINKS: ReadonlyArray<{ href: string; text: string }> = [
  { href: "/about/using.html", text: "Using RouteMaker" },
  { href: "/about/how-it-works.html", text: "How RouteMaker works" },
  { href: "/about/ride-types.html", text: "Ride types" },
  { href: STRESS_PAGE, text: "Stress ratings" },
  { href: "/about/routing.html", text: "Routing" },
  { href: "/about/architecture.html", text: "Architecture" },
];

/** The documentation's short version (how-it-works.html, "In short"), one line each. */
export const INFO_POINTS: readonly string[] = [
  "Every road is rated for traffic stress, from LTS 1 (comfortable for everyone) to LTS 4 (busy, fast traffic), plus 4.5 and Avoid for the worst roads.",
  "Your ride type and the traffic slider decide how much extra distance a calmer road is worth.",
  "Busy junctions cost extra too.",
  "Real closures move a route. DC's planned-work permits never do.",
];

/** The panel's markup (our own constant, no rider text), before the credits. */
export const MAP_INFO: string = [
  `<p><strong>Plan a route.</strong> ${searchLede(false)}</p>`,
  `<ul>${INFO_POINTS.map((point) => `<li>${point}</li>`).join("")}</ul>`,
  `<p>More: ${DOCS_LINKS.map((link) => `<a href="${link.href}">${link.text}</a>`).join(" · ")}</p>`,
  "<p><strong>Credits.</strong></p>",
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
  return true;
}
