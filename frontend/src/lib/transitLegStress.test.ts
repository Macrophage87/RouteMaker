/**
 * Every ride of a transit trip coloured by traffic stress (v0.7.0; Stephen: "When a trip includes a
 * mix of modes, it doesn't seem to include the LTS of the section towards the destination"). The API
 * now routes each later ride as it routes the first, and gives its step `stress_spans` along its
 * routed `coordinates`; the map cuts it into the route's own sections, the legend counts it, and the
 * steps list says its stress as the route chart says the route's.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse, StressSpan, TransitPlan, TransitStep } from "./api.ts";
import { routeAndRideSections, routeLineData } from "./mapGlue.ts";
import { routeLegend, routeSections } from "./routeColours.ts";
import { RIDES_LEGEND, rideSections, stepStressSaid, transitFeatures, transitRideLines, transitRideSections, tripStressSpans } from "./transit.ts";

const MAIN_SPANS: StressSpan[] = [
  { from_m: 0, to_m: 200, tier: 2, facility: "lane" },
  { from_m: 200, to_m: 300, tier: 1, facility: "path" },
];
const LAST_SPANS: StressSpan[] = [
  { from_m: 0, to_m: 150, tier: 3, facility: "none" },
  { from_m: 150, to_m: 450, tier: 2, facility: "lane" },
];
const LAST_LINE: [number, number][] = [
  [-77.0281, 38.8932],
  [-77.029, 38.8945],
  [-77.03, 38.896],
];

const step = (over: Partial<TransitStep>): TransitStep => ({
  mode: "ride",
  text: "Ride 2 min to your destination.",
  seconds: 120,
  wait_s: 0,
  to: null,
  lines: [],
  with_bike: false,
  route_line: false,
  coordinates: [],
  ...over,
});

const FIRST = step({ text: "Ride 4 min to Eastern Market.", to: "Eastern Market", route_line: true });
const METRO = step({
  mode: "metro",
  text: "Board the Orange Line; ride 10 min to Federal Triangle.",
  lines: ["Orange Line"],
  system: "Metro",
  coordinates: [
    [-76.996, 38.8846],
    [-77.0159, 38.8851],
  ],
});
const LAST = step({ coordinates: LAST_LINE, stress_spans: LAST_SPANS });
const PLAIN_LAST = step({ coordinates: [LAST_LINE[0], LAST_LINE[2]], stress_spans: null });

const plan = (steps: TransitStep[]) => ({ steps }) as unknown as TransitPlan;
const route = (steps: TransitStep[]) =>
  ({
    geometry: {
      type: "LineString",
      coordinates: [
        [-76.993, 38.883],
        [-76.995, 38.884],
        [-76.996, 38.8846],
      ],
    },
    stress_spans: MAIN_SPANS,
    transit: plan(steps),
  }) as unknown as RouteResponse;

test("a later ride routed with its stress is cut into the route's own coloured sections", () => {
  const sections = rideSections(LAST)!;
  assert.deepEqual(sections, routeSections(LAST_LINE, LAST_SPANS));
  assert.ok(sections.length >= 2);
  assert.deepEqual(transitRideSections(plan([FIRST, METRO, LAST])), sections);
  // The route line's own step, a transit step, and a ride with no stress have none.
  assert.equal(rideSections(FIRST), null);
  assert.equal(rideSections(METRO), null);
  assert.equal(rideSections(PLAIN_LAST), null);
  // A share bike's ride at the far end is coloured too; a walk never is.
  assert.ok(rideSections({ ...LAST, mode: "bikeshare" }));
  assert.equal(rideSections({ ...LAST, mode: "walk" }), null);
});

test("the map draws a coloured later ride in the route's sections, not as a plain line", () => {
  const coloured = transitFeatures(plan([FIRST, METRO, LAST])).features.map((f) => f.properties.draw);
  assert.deepEqual(coloured, ["transit"]);
  // A ride the router did not answer in time keeps today's thin solid line.
  const plain = transitFeatures(plan([FIRST, METRO, PLAIN_LAST])).features.map((f) => f.properties.draw);
  assert.deepEqual(plain, ["transit", "ride"]);
  // Its sections go beside the route's own, and its line under the route's casing.
  const all = routeAndRideSections(route([FIRST, METRO, LAST]))!;
  const own = routeSections(route([]).geometry.coordinates as [number, number][], MAIN_SPANS)!;
  assert.equal(all.length, own.length + rideSections(LAST)!.length);
  assert.deepEqual(transitRideLines(plan([FIRST, METRO, LAST])), [LAST_LINE]);
  const data = routeLineData(route([FIRST, METRO, LAST])) as { type: string; features: { geometry: { coordinates: unknown } }[] };
  assert.equal(data.type, "FeatureCollection");
  assert.deepEqual(data.features[1].geometry.coordinates, LAST_LINE);
  // With no coloured later ride, the route source is the route alone, as before.
  assert.equal((routeLineData(route([FIRST, METRO, PLAIN_LAST])) as { type: string }).type, "Feature");
  assert.equal(routeAndRideSections(null), null);
});

test("the legend counts the later rides' colours with the route's", () => {
  const spans = tripStressSpans(route([FIRST, METRO, LAST]))!;
  assert.deepEqual(
    spans.map((s) => [s.from_m, s.to_m, s.tier]),
    [
      [0, 200, 2],
      [200, 300, 1],
      [300, 450, 3],
      [450, 750, 2],
    ],
  );
  const legend = routeLegend(spans);
  // LTS 3 is on the last ride only, and is named all the same.
  assert.ok(legend.some((row) => row.metres === 150));
  assert.equal(legend.reduce((sum, row) => sum + row.metres, 0), 750);
  // No coloured later ride: the route's own sections, as before.
  assert.equal(tripStressSpans(route([FIRST, METRO, PLAIN_LAST])), MAIN_SPANS);
});

test("a screen reader hears each ride's stress in the route chart's words, the first ride's and the later ones' alike", () => {
  assert.equal(stepStressSaid(LAST), "Traffic stress along it: 67% LTS 2, 33% LTS 3.");
  assert.equal(stepStressSaid(FIRST, MAIN_SPANS), "Traffic stress along it: 33% traffic-free path, 67% LTS 2.");
  assert.equal(stepStressSaid(FIRST), null);
  assert.equal(stepStressSaid(PLAIN_LAST), null);
  assert.equal(stepStressSaid(METRO, MAIN_SPANS), null);
  const summary = readFileSync(new URL("../TransitSummary.tsx", import.meta.url), "utf8");
  assert.match(summary, /stepStressSaid\(step, lineSpans\)/);
  assert.match(summary, /\{RIDES_LEGEND\}/);
  assert.match(RIDES_LEGEND, /Every ride is coloured by traffic stress/);
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /lineSpans=\{route\.stress_spans\}/);
  const breakdown = readFileSync(new URL("../FacilityBreakdown.tsx", import.meta.url), "utf8");
  assert.match(breakdown, /routeLegend\(tripStressSpans\(route\)\)/);
});
