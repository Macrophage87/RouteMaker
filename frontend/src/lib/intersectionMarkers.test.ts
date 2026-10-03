import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ICON_PX,
  JUNCTION_HINT,
  MAX_ON_MAP,
  SEVERITY_COLOURS,
  SEVERITY_SHAPES,
  GROUP_BELOW_ZOOM,
  GROUP_RADIUS_PX,
  groupJunctions,
  groupRadius,
  MAP_MAX_ZOOM,
  OVERLAP_RADIUS_PX,
  groupLabel,
  junctionCounts,
  junctionHeadline,
  junctionItems,
  junctionRows,
  junctionsOnMap,
  warningIconSvg,
} from "./intersectionMarkers.ts";
import type { JunctionGroupSummary, JunctionWarning } from "./api.ts";

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
  // Never the colour alone (review r1): a triangle for orange, an octagon for red.
  const a = warningIconSvg("orange");
  const b = warningIconSvg("red");
  assert.ok(a.includes(SEVERITY_SHAPES.orange) && !a.includes(SEVERITY_SHAPES.red));
  assert.ok(b.includes(SEVERITY_SHAPES.red) && !b.includes(SEVERITY_SHAPES.orange));
  assert.notEqual(a.replaceAll(orange.fill, "X").replaceAll(orange.stroke, "Y"), b.replaceAll(red.fill, "X").replaceAll(red.stroke, "Y"));
  // The octagon has eight corners.
  assert.equal((SEVERITY_SHAPES.red.match(/[hvlHVL]/g) ?? []).length + 1, 8);
});

test("close markers are one group when zoomed out, and come apart when zoomed in", () => {
  const at = (m: number, severity: "orange" | "red") =>
    junctionItems({
      intersections: [{ m, lon: -77, lat: 38.9, severity, reason: "r", crossed_tier: 4, movement: "straight", control: "none", kind: "crossing", cost_ft: 1000 }],
    }).map((item) => ({ ...item, index: m }))[0];
  const items = [at(0, "orange"), at(10, "red"), at(100, "orange"), at(29, "orange")];
  // Screen x is the m figure; all on one line.
  const project = (item: { m: number }) => ({ x: item.m, y: 0 });
  const out = groupJunctions(items, GROUP_BELOW_ZOOM - 1, project);
  assert.deepEqual(
    out.map((g) => g.members.map((m) => m.m)),
    [[0, 10], [100], [29]],
    "joined to the first group within the radius of its anchor",
  );
  assert.deepEqual(out.map((g) => g.severity), ["red", "orange", "orange"], "a group is as bad as its worst");
  assert.equal(groupLabel(out[0]), "2 stressful junctions here, 1 very high stress: zoom in to see them");
  const close = groupJunctions(items, GROUP_BELOW_ZOOM, project);
  assert.deepEqual(
    close.map((g) => g.members.map((m) => m.m)),
    [[0, 10], [100], [29]],
    "at and above the zoom only markers that would overlap (closer than an icon) are one",
  );
  assert.equal(groupJunctions(items, MAP_MAX_ZOOM, project).length, 4, "at the last zoom every junction is its own marker");
  assert.equal(groupJunctions(items, MAP_MAX_ZOOM, project, 200).length, 4, "even with a radius given");
  assert.equal(groupJunctions(items, 17.9, project).length, 3, "just below it, overlapping ones still group");
  // Exactly an icon apart still overlaps at the edge; a pixel more does not.
  assert.equal(groupJunctions([at(0, "orange"), at(24, "orange")], GROUP_BELOW_ZOOM, project).length, 1);
  assert.equal(groupJunctions([at(0, "orange"), at(25, "orange")], GROUP_BELOW_ZOOM, project).length, 2);
  assert.equal(groupRadius(GROUP_BELOW_ZOOM - 0.1), GROUP_RADIUS_PX);
  assert.equal(groupRadius(GROUP_BELOW_ZOOM), OVERLAP_RADIUS_PX);
  assert.equal(groupRadius(MAP_MAX_ZOOM), 0);
  assert.equal(OVERLAP_RADIUS_PX, ICON_PX);
  assert.equal(MAP_MAX_ZOOM, 18);
  assert.equal(groupJunctions(items, 10, project, 200).length, 1);
  assert.equal(GROUP_RADIUS_PX, 28);
  // Exactly the radius away is close enough.
  assert.equal(groupJunctions([at(0, "orange"), at(28, "orange")], 10, project).length, 1);
  // Within reach of two groups, a junction joins the first in route order.
  const between = groupJunctions([at(0, "orange"), at(40, "red"), at(20, "orange")], 10, project);
  assert.deepEqual(between.map((g) => g.members.map((m) => m.m)), [[0, 20], [40]]);
});

test("every list row says its severity in words", () => {
  const items = junctionItems({
    intersections: [
      { m: 100, lon: -77, lat: 38.9, severity: "red", reason: "Crossing a heavy-traffic road (LTS 4), no signal mapped", crossed_tier: 4, movement: "straight", control: "none", kind: "crossing", cost_ft: 3000 },
      { m: 900, lon: -77, lat: 38.9, severity: "orange", reason: "Crossing a slip lane off a busy road (LTS 3), traffic signal", crossed_tier: 3, movement: "straight", control: "signal", kind: "slip_lane", cost_ft: 800 },
    ],
  });
  // "stress" every time: "Higher" alone was ambiguous (a11y review of integrate-2).
  assert.deepEqual(items.map((i) => i.severityText), ["Very high stress", "Higher stress"]);
  assert.equal(SEVERITY_COLOURS.red.short, "Very high stress");
  assert.equal(SEVERITY_COLOURS.orange.short, "Higher stress");
  for (const severity of ["red", "orange"] as const) assert.equal(SEVERITY_COLOURS[severity].short, SEVERITY_COLOURS[severity].label);
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

// OWNER-DECISIONS 233, 234: a Mass Ride's signalized crossings within a quarter mile
// of one another are one row of the list, which opens onto its members.

function crossingAt(m: number, severity: "orange" | "red", group: number | null): JunctionWarning {
  return {
    m,
    lon: -77.03 + m / 100000,
    lat: 38.9,
    severity,
    reason: `Crossing a 4-lane road at ${m} m, traffic signal`,
    crossed_tier: severity === "red" ? 4 : 3,
    movement: "straight",
    control: "signal",
    kind: "crossing",
    cost_ft: 300,
    group,
  };
}

function summary(over: Partial<JunctionGroupSummary> = {}): JunctionGroupSummary {
  return {
    group: 1,
    from_m: 1600,
    to_m: 2600,
    count: 3,
    lts4: 1,
    streets: ["17th Street Northwest", "15th Street Northwest", "14th Street Northwest"],
    more: 0,
    severity: "red",
    members: [1, 2, 3],
    text: "1.0 to 1.6 mi (1.6 to 2.6 km): 3 crossings with traffic signals (17th Street Northwest, 15th Street Northwest and 14th Street Northwest), 1 of them a heavy-traffic road (LTS 4)",
    ...over,
  };
}

const massRide = {
  intersections: [
    { ...crossing, group: null },
    crossingAt(1600, "orange", 1),
    crossingAt(2100, "red", 1),
    crossingAt(2600, "orange", 1),
    { ...left, group: null },
  ],
  intersection_groups: [summary()],
};

test("a group is one row at its first crossing, between the junctions before and after it", () => {
  const rows = junctionRows(massRide);
  assert.deepEqual(rows.map((r) => r.kind), ["item", "group", "item"]);
  const group = rows[1];
  assert.equal(group.kind, "group");
  if (group.kind !== "group") return;
  assert.deepEqual(group.group.members.map((m) => m.index), [1, 2, 3]);
  assert.equal(group.group.count, 3);
  assert.equal(group.group.text, massRide.intersection_groups[0].text);
});

test("a group's severity is its worst member's, in words", () => {
  const group = junctionRows(massRide)[1];
  assert.equal(group.kind, "group");
  if (group.kind !== "group") return;
  assert.equal(group.group.severity, "red");
  assert.equal(group.group.severityText, "Very high stress");
  const calm = junctionRows({
    intersections: massRide.intersections.map((j) => ({ ...j, severity: "orange" as const })),
    intersection_groups: [summary({ severity: "orange" })],
  })[1];
  assert.equal(calm.kind === "group" && calm.group.severityText, "Higher stress");
});

test("every junction is still in the junction items, so the map and the headline count them all", () => {
  assert.equal(junctionItems(massRide).length, 5);
  assert.equal(junctionHeadline(junctionCounts(junctionItems(massRide))), "Watch for 2 very high stress (red) and 3 higher stress (orange) junctions");
});

test("without groups, or from an older API, every junction is a row of its own", () => {
  for (const route of [
    { intersections: massRide.intersections },
    { intersections: massRide.intersections, intersection_groups: [] },
    { intersections: massRide.intersections, intersection_groups: null },
    { intersections: [] },
    null,
  ]) {
    const rows = junctionRows(route);
    assert.ok(rows.every((r) => r.kind === "item"));
    assert.equal(rows.length, route?.intersections?.length ?? 0);
  }
});

test("a group that does not hold together is not shown as one: nothing is hidden", () => {
  const broken: Partial<JunctionGroupSummary>[] = [
    { members: [1, 2, 9] },
    { members: [1] },
    { members: [0, 1, 2] },
    { text: "  " },
    { members: undefined as unknown as number[] },
  ];
  for (const over of broken) {
    const rows = junctionRows({ ...massRide, intersection_groups: [summary(over)] });
    assert.equal(rows.length, 5, JSON.stringify(over));
    assert.ok(rows.every((r) => r.kind === "item"));
  }
});

test("two groups are two rows, in route order", () => {
  const route = {
    intersections: [
      crossingAt(100, "orange", 1),
      crossingAt(300, "orange", 1),
      { ...crossing, group: null },
      crossingAt(5000, "red", 2),
      crossingAt(5200, "orange", 2),
    ],
    intersection_groups: [
      summary({ group: 1, members: [0, 1], count: 2 }),
      summary({ group: 2, members: [3, 4], count: 2, text: "3.1 to 3.2 mi (5.0 to 5.2 km): 2 crossings with traffic signals" }),
    ],
  };
  const rows = junctionRows(route);
  assert.deepEqual(rows.map((r) => (r.kind === "group" ? `g${r.group.number}` : "item")), ["g1", "item", "g2"]);
});

// --- The row names (a11y re-check of 2b0cf00, B2) ---

test("a row's name is one string with no stray spaces, the visible words first", async () => {
  const { rowName } = await import("./intersectionMarkers.ts");
  assert.equal(rowName("Higher stress", "At 0.6 mi (1.0 km)", "Crossing a busy road (LTS 3), traffic signal"),
    "Higher stress, At 0.6 mi (1.0 km): Crossing a busy road (LTS 3), traffic signal");
  assert.equal(rowName("Very high stress", "Group", "1.1 to 1.8 mi (1.7 to 2.9 km): 4 crossings with traffic signals"),
    "Very high stress, Group: 1.1 to 1.8 mi (1.7 to 2.9 km): 4 crossings with traffic signals");
  const list = readFileSync(new URL("../IntersectionList.tsx", import.meta.url), "utf8");
  // Every row, member and group is named by it; no hidden separators left to space.
  assert.match(list, /aria-label=\{rowName\(item\.severityText, item\.where, item\.reason\)\}/);
  assert.match(list, /aria-label=\{rowName\(group\.severityText, "Group", group\.text\)\}/);
  assert.doesNotMatch(list, /visually-hidden/);
});
