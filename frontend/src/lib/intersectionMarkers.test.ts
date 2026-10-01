import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ICON_PX,
  JUNCTION_HINT,
  MAX_ON_MAP,
  SEVERITY_COLOURS,
  junctionCounts,
  junctionHeadline,
  junctionItems,
  junctionsOnMap,
  warningIconSvg,
} from "./intersectionMarkers.ts";
import type { JunctionWarning } from "./api.ts";

// OWNER-DECISIONS 172: orange for higher stress, red for very high, listed in the
// route summary, a click explaining why, a neighbourhood stop sign never flagged.

const left: JunctionWarning = {
  m: 5150,
  lon: -77.01,
  lat: 38.9,
  severity: "red",
  reason: "Left turn across a 4-lane 35 mph (56 km/h) road, no signal",
  crossed_tier: 4,
  movement: "left",
  control: "none",
  kind: "left_from",
  cost_ft: 2400,
};
const crossing: JunctionWarning = {
  m: 800,
  lon: -77.02,
  lat: 38.91,
  severity: "orange",
  reason: "Crossing a 2-lane 30 mph (48 km/h) road, no signal",
  crossed_tier: 3,
  movement: "straight",
  control: "none",
  kind: "crossing",
  cost_ft: 1100,
};

test("the list is the API's, in its order, worded with miles first", () => {
  const items = junctionItems({ intersections: [crossing, left] });
  assert.deepEqual(items.map((i) => i.index), [0, 1]);
  assert.equal(items[0].where, "At 0.5 mi (0.8 km)");
  assert.equal(items[1].where, "At 3.2 mi (5.2 km)");
  assert.equal(items[1].reason, left.reason);
  assert.equal(items[1].label, `Very high stress: ${left.reason}`);
  assert.equal(items[0].label, `Higher stress: ${crossing.reason}`);
});

test("nothing is listed for a route with no junction list, an older API's included", () => {
  assert.deepEqual(junctionItems(null), []);
  assert.deepEqual(junctionItems({ intersections: null }), []);
  assert.deepEqual(junctionItems({}), []);
  assert.deepEqual(junctionItems({ intersections: [] }), []);
});

test("the count names each colour, red first", () => {
  assert.deepEqual(junctionCounts([crossing, left, left]), { orange: 1, red: 2, total: 3 });
  assert.equal(junctionHeadline({ orange: 1, red: 2, total: 3 }), "Watch for 2 very high stress (red) and 1 higher stress (orange) junctions");
  assert.equal(junctionHeadline({ orange: 1, red: 0, total: 1 }), "Watch for 1 higher stress (orange) junction");
  assert.equal(junctionHeadline({ orange: 0, red: 1, total: 1 }), "Watch for 1 very high stress (red) junction");
  assert.equal(junctionHeadline({ orange: 0, red: 0, total: 0 }), "No stressful junctions on this route");
});

test("the hint says how to avoid a junction and that quiet stop signs are never marked", () => {
  assert.match(JUNCTION_HINT, /Drag the route away/);
  assert.match(JUNCTION_HINT, /stop sign on a quiet street is never marked/);
});

test("the two colours are an orange and a red, and stay apart", () => {
  const { orange, red } = SEVERITY_COLOURS;
  assert.notEqual(orange.fill, red.fill);
  assert.match(orange.fill, /^#f59e0b$/);
  assert.match(red.fill, /^#dc2626$/);
  // The same icon, only the fill differs: the style the Mass Ride plan uses.
  const a = warningIconSvg("orange");
  const b = warningIconSvg("red");
  assert.equal(a.replaceAll(orange.fill, "X").replaceAll(orange.stroke, "Y"), b.replaceAll(red.fill, "X").replaceAll(red.stroke, "Y"));
});

test("the icon is inline SVG with nothing to fetch, sized as asked, and hidden from screen readers", () => {
  const svg = warningIconSvg("red");
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" width="24" height="24"/);
  assert.equal(ICON_PX, 24);
  assert.match(warningIconSvg("orange", 18), /width="18" height="18"/);
  assert.match(svg, /aria-hidden="true"/);
  assert.doesNotMatch(svg, /<image|href=|url\(/);
});

test("past the cap the worst junctions are drawn, in route order", () => {
  const many = Array.from({ length: MAX_ON_MAP + 20 }, (_, i) => ({ ...crossing, m: i * 10, cost_ft: 1000 + (i % 7 === 0 ? 5000 : 0) + i }));
  const items = junctionItems({ intersections: many });
  assert.equal(junctionsOnMap(items.slice(0, MAX_ON_MAP)).length, MAX_ON_MAP);
  const drawn = junctionsOnMap(items);
  assert.equal(drawn.length, MAX_ON_MAP);
  assert.deepEqual(drawn.map((i) => i.index), [...drawn.map((i) => i.index)].sort((a, b) => a - b));
  const kept = new Set(drawn.map((i) => i.index));
  for (const item of items) {
    if (item.index % 7 === 0) assert.ok(kept.has(item.index), `the costly junction ${item.index} is drawn`);
  }
});
