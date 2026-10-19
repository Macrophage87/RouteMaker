/**
 * The map's info panel: what the "i" by the OpenStreetMap credit opens (Stephen 2026-10-19: "Put this text
 * in the info panel and also add more from the documentation"). Plan's how-to moved here out of the Plan
 * panel, so Plan scrolls less; a screen reader still hears it there (Planner.tsx). Then the documentation's
 * "In short", most important first, with links to the pages for the rest, then the credits.
 *
 * MapLibre shows it as the attribution control's one entry, through its own sanitizer (p, ul, li, strong
 * and a survive), so it is plain markup with no handlers.
 */
import { searchLede } from "./sidebar.ts";

/** The rider-facing documentation pages (public/about/), in the order the hub lists them. */
export const DOCS_LINKS: ReadonlyArray<{ href: string; text: string }> = [
  { href: "/about/how-it-works.html", text: "How RouteMaker works" },
  { href: "/about/ride-types.html", text: "Ride types" },
  { href: "/about/stress.html", text: "Stress ratings" },
  { href: "/about/architecture.html", text: "Architecture" },
];

/** The documentation's short version (how-it-works.html, "In short"), one line each. */
export const INFO_POINTS: readonly string[] = [
  "Every road is rated for traffic stress, from LTS 1 (comfortable for everyone) to LTS 4 (busy, fast traffic), plus 4.5 and Avoid for the worst roads.",
  "Your ride type and the traffic slider decide how much extra distance a calmer road is worth.",
  "Busy junctions cost extra too.",
  "Real closures move a route. DC's planned-work permits never do.",
];

/** The panel's markup, before the credits. */
export const MAP_INFO: string = [
  '<div class="map-info">',
  `<p><strong>Plan a route.</strong> ${searchLede(false)}</p>`,
  `<ul>${INFO_POINTS.map((point) => `<li>${point}</li>`).join("")}</ul>`,
  `<p>More: ${DOCS_LINKS.map((link) => `<a href="${link.href}">${link.text}</a>`).join(" · ")}</p>`,
  "<p><strong>Credits.</strong></p>",
  "</div>",
].join("");
