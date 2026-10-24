/**
 * v0.7.0 "Via points vs stops": the wiring around lib/pointKinds.ts - the link, the route request, Best order,
 * the GPX file, the points list and the map's markers.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";
import { ViaMarks, markerLabels, viaIndices, importedKinds, kindSaid } from "./pointKinds.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { requestRoute } from "./api.ts";
import { applyAnswer, type StopOrder } from "./stopOrder.ts";
import { startDials } from "./dials.ts";
import { planPointNames, writeGpx } from "./gpx.ts";
import { pointRows } from "./geocode.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];
const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the link keeps each point's kind, and an older link reads every point as a stop", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), marks.via(p(-77.01)), p(-77.02), p(-77.03)];
  const hash = encodePlan(points, "default", startDials("default"), viaIndices(points, marks.isVia));
  assert.match(hash, /via=1/);
  const plan = decodePlan(hash);
  assert.deepEqual(plan.vias, [1]);
  const reopened = new ViaMarks();
  reopened.markAt(plan.points, plan.vias);
  assert.deepEqual(viaIndices(plan.points, reopened.isVia), [1]);
  // A link from before v0.7.0: no via field, so every point is a stop.
  const old = decodePlan(encodePlan(points, "default", startDials("default")));
  assert.deepEqual(old.vias, []);
});

test("a Riding with kids link opens Novice and Nervous at its own starting sliders", () => {
  const plan = decodePlan("#p=-77.00000,38.90000;-77.10000,38.90000&preset=kids&stress=40&hills=20&v=2");
  assert.equal(plan.preset, "novice");
  assert.equal(plan.dials.stress, startDials("novice").stress);
  assert.equal(plan.dials.hills, startDials("novice").hills);
  // A link to the ride type by its own name keeps the sliders it carries.
  const own = decodePlan("#p=-77.00000,38.90000;-77.10000,38.90000&preset=novice&stress=40&hills=20&v=2");
  assert.equal(own.dials.stress, 40);
  assert.equal(own.dials.hills, 20);
});

test("the route request names the via points, never on a two-point ride type", async () => {
  const bodies: Record<string, unknown>[] = [];
  const impl = async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response("{}", { status: 500 });
  };
  const points = [p(-77.0), p(-77.01), p(-77.02)];
  await requestRoute(points, "default", { fetchImpl: impl, vias: [1] });
  await requestRoute(points, "default", { fetchImpl: impl, vias: [] });
  await requestRoute([p(-77.0), p(-77.02)], "bikeshare", { fetchImpl: impl, vias: [1] });
  assert.deepEqual(bodies[0].via_points, [1]);
  assert.equal("via_points" in bodies[1], false);
  assert.equal("via_points" in bodies[2], false);
});

test("Best order is asked of the stops only, and each via point moves with the stop it leads to", () => {
  const marks = new ViaMarks();
  const start = p(-77.0);
  const v = marks.via(p(-77.01));
  const a = p(-77.02);
  const b = p(-77.03);
  const end = p(-77.04);
  const current = [start, v, a, b, end];
  const stops = { points: [start, a, b, end], leading: [[], [v], [], []] };
  const dials = startDials("default");
  const answer: StopOrder = { order: [0, 2, 1, 3], changed: true, by: "route_cost", exact: true, before_s: 600, after_s: 540, before_m: null, after_m: null };
  const names = { name: () => undefined };
  const applied = applyAnswer(
    { points: current, preset: "default", dials, loop: false, stops },
    { points: current, preset: "default", dials },
    { ok: true, answer },
    names,
  );
  assert.deepEqual(applied.commit, [start, b, v, a, end]);
  assert.match(applied.say, /Stop 1|Stop 2/);
});

test("a GPX file names a via point 'Via point', numbers the stops among themselves, and reads it back", () => {
  assert.deepEqual(planPointNames(5, false, [1]), ["Start", "Via point", "Stop 1", "Stop 2", "End"]);
  assert.deepEqual(planPointNames(4), ["Start", "Stop 1", "Stop 2", "End"]);
  const points = [p(-77.0), p(-77.01), p(-77.02), p(-77.03)];
  const gpx = writeGpx({ name: "n", description: "d", attribution: [], preset: "default", planPoints: points, vias: [2], geometry: points });
  const named = [...gpx.matchAll(/<rtept [^>]*>\s*<name>([^<]*)<\/name>/g)].map((m) => m[1]);
  assert.deepEqual(named, ["Start", "Stop 1", "Via point", "End"]);
  // No <wpt> for a via point (the file has none for any point).
  assert.doesNotMatch(gpx, /<wpt/);
  // Opened again: the named via point, and never an end.
  assert.deepEqual(importedKinds(named, 4).vias, [2]);
  assert.deepEqual(importedKinds(["Via point", "Stop 1", "Via point"], 3).vias, []);
});

test("the list, the markers and the announcements name a via point and number the stops among themselves", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), marks.via(p(-77.01)), p(-77.02), p(-77.03)];
  const rows = pointRows(points, { name: () => undefined }, false, marks.isVia);
  assert.deepEqual(rows.map((r) => r.role), ["Start", "Via point", "Stop 1", "End"]);
  // Without the kinds, the list is as it was.
  assert.deepEqual(pointRows(points, { name: () => undefined }).map((r) => r.role), ["Start", "Stop 1", "Stop 2", "End"]);
  assert.deepEqual(markerLabels(points, marks.isVia).map((m) => [m.kind, m.text, m.name]), [
    ["start", "", "Start"],
    ["through", "", "Via point"],
    ["via", "1", "Stop 1"],
    ["end", "", "End"],
  ]);
  assert.equal(kindSaid(points, 1, marks.isVia, false, "added"), "Via point added.");
  assert.equal(kindSaid(points, 2, marks.isVia, false, "removed"), "Stop 1 removed.");
});

test("the map's point menu is a real menu with Remove and the one switch between a stop and a via point", () => {
  const map = source("../MapView.tsx");
  assert.match(map, /menu\.setAttribute\("role", "menu"\);/);
  assert.match(map, /item\.setAttribute\("role", "menuitem"\);/);
  assert.match(map, /kindSwitchLabel\(/);
  assert.match(map, /callbacks\.current\.onSwitchKind\?\.\(index\);/);
  // A right-click or a long press opens the same menu.
  assert.match(map, /element\.addEventListener\("contextmenu", \(event\) => \{/);
  const css = source("../styles.css");
  assert.match(css, /\.pin-via\.pin-through \{\s+background: transparent;/);
  const app = source("../App.tsx");
  // Taps between the ends and line drags are via points; a drag keeps the kind; the switch is one undoable edit.
  assert.match(app, /if \(isMiddle\(index, next\.length, loopVias\) && index < next\.length - 1\) VIA_MARKS\.via\(point\);/);
  assert.match(app, /commit\(current\.map\(\(p, i\) => \(i === index \? VIA_MARKS\.withKind\(p, to\) : p\)\)\);/);
  assert.match(app, /onSwitchKind=\{riding \? ignore : switchKind\}/);
});
