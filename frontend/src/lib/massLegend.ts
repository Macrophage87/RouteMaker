/**
 * The Mass Ride map's legend and the route panel's riders-per-minute figures
 * (OWNER-DECISIONS 325-327, 387; the approved mock-up, sidebar-mockup-v3/MassRide.dc.html):
 * riders per minute in place of the LTS breakdown. Written with createElement so a test
 * renders it (as stressLegend.ts does); every swatch is hidden from a screen reader and every
 * row has its words, so nothing is colour alone.
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { MASS_AVOID, MASS_BANDS } from "../massStyle.js";
import type { RouteResponse } from "./api.ts";
import { DC_BOUNDARY_CREDIT, MASS_DC_ONLY } from "./dcBoundary.ts";
import { formatDistance } from "./format.ts";
import { ROUTE_CASING_WIDTH, routeCasing, routeClasses, routeMarkDash, routeMarkWidth, type RouteClass, type RouteClassKey } from "./routeColours.ts";
import {
  AVOID_LEGEND_TEXT,
  CAPACITY_FIGURE_TITLE,
  CAPACITY_LEGEND_TITLE,
  CAPACITY_MEANS,
  CAPACITY_SOURCE,
  MASS_ZOOM_HINT,
  bandLegendText,
  massBandsSaid,
  capacityRows,
  capacitySummary,
  capacityPair,
  capitalise,
  narrowestClause,
  narrowestLines,
  typicalLines,
  type CapacityLine,
} from "./massCapacity.ts";

const SWATCH_W = 56;

type Band = (typeof MASS_BANDS)[number];

/** A band's swatch: its halo (which shows in the dash's gaps), then its line at the map's width and dash. */
export function BandSwatch({ band }: { band: Band }): ReactElement {
  const dash = band.dashPx ? band.dashPx.join(" ") : undefined;
  return h(
    "svg",
    { width: SWATCH_W, height: 14, "aria-hidden": "true", className: "mass-swatch" },
    h("line", { x1: 0, y1: 7, x2: SWATCH_W, y2: 7, stroke: band.halo, strokeWidth: band.width + 2 }),
    h("line", { x1: 0, y1: 7, x2: SWATCH_W, y2: 7, stroke: band.color, strokeWidth: band.width, strokeDasharray: dash }),
  );
}

/** The Avoid swatch: near-black on coral, dash-dot. */
export function AvoidSwatch(): ReactElement {
  const dash = MASS_AVOID.dash.map((d: number) => d * MASS_AVOID.width).join(" ");
  return h(
    "svg",
    { width: SWATCH_W, height: 14, "aria-hidden": "true", className: "mass-swatch" },
    h("line", { x1: 0, y1: 7, x2: SWATCH_W, y2: 7, stroke: MASS_AVOID.casing, strokeWidth: MASS_AVOID.casingWidth }),
    h("line", { x1: 0, y1: 7, x2: SWATCH_W, y2: 7, stroke: MASS_AVOID.color, strokeWidth: MASS_AVOID.width, strokeDasharray: dash }),
  );
}

/**
 * A route section's own swatch (the route line's look, as FacilityBreakdown draws it): for the route
 * list's Avoid row, the route's magenta with the white dash-dot (397), and its "No capacity figure"
 * row, the unrated grey on its halo, which the map legend has no row for (accessibility review N2).
 */
export function RouteClassSwatch({ cls }: { cls: RouteClass }): ReactElement {
  const line = (stroke: string, width: number, extra: Record<string, unknown> = {}) =>
    h("line", { x1: 3, y1: 7, x2: 33, y2: 7, stroke, strokeWidth: width, strokeLinecap: "round", ...extra });
  return h(
    "svg",
    { width: 36, height: 14, "aria-hidden": "true", className: "route-swatch" },
    line(routeCasing(), ROUTE_CASING_WIDTH),
    cls.ring ? line(cls.ring, cls.ringWidth ?? cls.haloWidth) : null,
    line(cls.halo, cls.haloWidth),
    line(cls.color, cls.width),
    cls.mark
      ? line(cls.mark, routeMarkWidth(cls.width), { className: "route-avoid-mark", strokeLinecap: undefined, strokeDasharray: routeMarkDash(cls.width) })
      : null,
  );
}

/** The route classes the list's two rows without a band are drawn in. */
const ROW_CLASS: Record<string, RouteClassKey> = { avoid: "mavoid", none: "unknown" };

function rowSwatch(key: string): ReactElement {
  const cls = routeClasses().find((c) => c.key === ROW_CLASS[key]);
  return cls ? h(RouteClassSwatch, { cls }) : h("span", { className: "swatch", "aria-hidden": "true" });
}

const row = (key: string, swatch: ReactElement, text: string) =>
  h("li", { key }, swatch, h("span", { className: "stress-label" }, text));

/**
 * The bands the map shows at the zoom it is at, in words (OWNER-DECISIONS 421), then the standing
 * note, under the legend. The status line is one persistent role="status" element whose words change
 * (as the federal-land section's: a live region inserted with its text is often not read), and its
 * words change only when the set of bands does, so zooming within a level says nothing.
 */
export function MassZoomNotes({ zoom, shown }: { zoom: number | null; shown: boolean }): ReactElement {
  const said = massBandsSaid(zoom, shown);
  return h(
    Fragment,
    null,
    h("p", { className: said ? "notice mass-bands" : "notice notice-empty mass-bands", role: "status" }, said ?? ""),
    h("p", { className: "hint" }, MASS_ZOOM_HINT),
  );
}

/**
 * The legend the Mass Ride map has in place of the stress legend: the four bands, lowest
 * first, then Avoid. Federal land, stops and groups keep their own sections (324).
 */
export function MassLegend(): ReactElement {
  return h(
    Fragment,
    null,
    h("p", { className: "hint lts-means" }, CAPACITY_MEANS),
    h(
      "ul",
      { className: "legend mass-legend", "aria-label": CAPACITY_LEGEND_TITLE },
      ...MASS_BANDS.map((band: Band, i: number) => row(band.key, h(BandSwatch, { band }), bandLegendText(i))),
      row("avoid", h(AvoidSwatch), AVOID_LEGEND_TEXT),
    ),
    h("p", { className: "hint capacity-source" }, CAPACITY_SOURCE),
    // DC only for now (OWNER-DECISIONS 418), in words, with the boundary's source.
    h("p", { className: "hint mass-dc-only" }, MASS_DC_ONLY),
    h("p", { className: "hint dc-boundary-source" }, DC_BOUNDARY_CREDIT),
  );
}

/** The route's own list: what the map's line colours mean on this route, with each band's share and length. */
export function CapacityFigures({ route }: { route: Pick<RouteResponse, "stress_spans"> & Partial<Pick<RouteResponse, "profile">> }): ReactElement | null {
  const summary = capacitySummary(route.stress_spans);
  if (!summary) return null;
  const pause = h("span", { className: "visually-hidden" }, ", ");
  return h(
    "figure",
    { className: "stress capacity", "aria-labelledby": "capacity-caption" },
    h("figcaption", { id: "capacity-caption" }, CAPACITY_FIGURE_TITLE),
    // The narrowest points, as the card and the directions give them (OWNER-DECISIONS 424).
    h("p", { className: "hint capacity-narrowest-said" }, `${capitalise(narrowestClause(capacityPair(summary, route.profile?.flow)))}.`),
    h(
      "ul",
      { className: "stress-list", "aria-label": "Share of the route in each riders-per-minute band" },
      ...capacityRows(summary).map((r) =>
        h(
          "li",
          { key: r.key },
          r.band === null ? rowSwatch(r.key) : h(BandSwatch, { band: MASS_BANDS[r.band] }),
          h("span", { className: "stress-name" }, r.text),
          pause,
          h("span", { className: "stress-pct" }, `${r.percent}%`),
          pause,
          h("span", { className: "stress-label" }, formatDistance(r.metres)),
        ),
      ),
    ),
  );
}

/**
 * The route view's figures (the mock-up's cards): the narrowest points, which are the route's
 * bottleneck, and the typical capacity, each on the flat and with the hills (OWNER-DECISIONS 424),
 * said once where the two agree. A definition list like the totals above it.
 */
export function CapacityStats({ route }: { route: Pick<RouteResponse, "stress_spans"> & Partial<Pick<RouteResponse, "profile">> }): ReactElement | null {
  const summary = capacitySummary(route.stress_spans);
  if (!summary || summary.minRpm === null) return null;
  const pair = capacityPair(summary, route.profile?.flow);
  const term = (line: CapacityLine, className: string) =>
    h("div", { key: line.key, className }, h("dt", null, capitalise(line.label)), h("dd", null, line.text));
  return h(
    Fragment,
    null,
    h("h3", { className: "visually-hidden" }, "Carrying capacity"),
    h(
      "dl",
      { className: "stats capacity-stats" },
      ...narrowestLines(pair).map((line) => term(line, `capacity-narrowest ${line.key}`)),
      ...typicalLines(pair).map((line) => term(line, `capacity-typical ${line.key}`)),
    ),
  );
}
