import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { setLanguageForTest } from "./i18n.ts";
import {
  ViaMarks,
  addStopWhereShortest,
  decodeVias,
  encodeVias,
  kindSwitchLabel,
  middleCountSaid,
  movableStops,
  namePoints,
  pointSaid,
  stopsOnly,
  viaIndices,
  withVias,
} from "./pointKinds.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];

test("a kind is kept on the point itself, and a switch is a new point (so Undo takes it back)", () => {
  const marks = new ViaMarks();
  const tapped = marks.via(p(-77.0));
  const searched = p(-77.01);
  assert.equal(marks.isVia(tapped), true);
  assert.equal(marks.isVia(searched), false);
  const stop = marks.withKind(tapped, "stop");
  assert.notEqual(stop, tapped);
  assert.deepEqual(stop, tapped);
  assert.equal(marks.isVia(stop), false);
  assert.equal(marks.isVia(tapped), true, "the old pair keeps its kind, for Undo");
  const via = marks.withKind(searched, "via");
  assert.equal(marks.isVia(via), true);
  // A dragged point keeps its kind.
  assert.equal(marks.isVia(marks.moved(tapped, p(-77.2))), true);
  assert.equal(marks.isVia(marks.moved(searched, p(-77.2))), false);
});

test("stops are numbered among themselves; via points are unnumbered and the ends are neither", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), marks.via(p(-77.01)), p(-77.02), marks.via(p(-77.03)), p(-77.04), marks.via(p(-77.05))];
  assert.deepEqual(
    namePoints(points, marks.isVia).map((n) => n.name),
    ["Start", "Via point", "Stop 1", "Via point", "Stop 2", "End"],
  );
  assert.deepEqual(viaIndices(points, marks.isVia), [1, 3]);
  // The start and the end are never via points, whatever made them.
  const ends = [marks.via(p(-77.0)), marks.via(p(-77.1))];
  assert.deepEqual(namePoints(ends, marks.isVia).map((n) => n.role), ["start", "end"]);
  assert.deepEqual(viaIndices(ends, marks.isVia), []);
});

test("a screen reader hears 'Via point' or 'Stop 2, Union Market'", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), p(-77.01), marks.via(p(-77.02)), p(-77.03), p(-77.04)];
  const names = namePoints(points, marks.isVia);
  assert.equal(pointSaid(names[3], "Union Market"), "Stop 2, Union Market");
  assert.equal(pointSaid(names[2], undefined), "Via point");
  assert.equal(pointSaid(names[2], "Rock Creek Trail"), "Via point, Rock Creek Trail");
  assert.equal(kindSwitchLabel("stop"), "Make this a via point");
  assert.equal(kindSwitchLabel("via"), "Make this a stop");
  assert.equal(kindSwitchLabel("start"), null);
  assert.equal(kindSwitchLabel("end"), null);
});

test("Best order moves stops only: each via point stays with the stop it leads to", () => {
  const marks = new ViaMarks();
  const start = p(-77.0);
  const v1 = marks.via(p(-77.01));
  const a = p(-77.02);
  const b = p(-77.03);
  const v2 = marks.via(p(-77.04));
  const end = p(-77.05);
  const split = stopsOnly([start, v1, a, b, v2, end], marks.isVia);
  assert.deepEqual(split.points, [start, a, b, end]);
  // The answer swaps the two stops: v1 still leads to a.
  assert.deepEqual(withVias([0, 2, 1, 3], split), [start, b, v1, a, v2, end]);
  assert.deepEqual(withVias([0, 1, 2, 3], split), [start, v1, a, b, v2, end]);
  assert.equal(movableStops([start, v1, a, b, v2, end], marks.isVia), 2);
  assert.equal(movableStops([start, v1, a, end], marks.isVia), 1);
});

test("in a loop every point after the start may move, its via points with it", () => {
  const marks = new ViaMarks();
  const start = p(-77.0);
  const a = p(-77.02);
  const b = p(-77.03);
  const v = marks.via(p(-77.04));
  const last = p(-77.05);
  const split = stopsOnly([start, a, b, v, last], marks.isVia, true);
  assert.deepEqual(split.points, [start, a, b, last]);
  assert.deepEqual(withVias([0, 3, 2, 1], split), [start, v, last, b, a]);
});

test("a searched stop goes where it adds the least distance", () => {
  const start = p(-77.0);
  const end = p(-77.1);
  const middle = p(-77.05, 38.901);
  const added = addStopWhereShortest([start, p(-77.08), end], middle);
  assert.deepEqual(added.points, [start, middle, p(-77.08), end]);
  assert.equal(added.index, 1);
});

test("the link keeps each point's kind; an old link has none, so every point is a stop", () => {
  const marks = new ViaMarks();
  const points = [p(-77.0), marks.via(p(-77.01)), p(-77.02), marks.via(p(-77.03)), p(-77.04)];
  assert.equal(encodeVias(points, marks.isVia), "1,3");
  assert.equal(encodeVias([p(1), p(2)], marks.isVia), null);
  assert.deepEqual(decodeVias("1,3", 5), [1, 3]);
  assert.deepEqual(decodeVias(null, 5), []);
  // Never an end, a duplicate or a stray value.
  assert.deepEqual(decodeVias("0,4,3,3,x,-1,2.5", 5), [3]);
});

test("Go's route card counts stops and via points apart (a commute of via points is not '4 stops')", () => {
  const marks = new ViaMarks();
  const allVias = [p(-77.0), marks.via(p(-77.01)), marks.via(p(-77.02)), marks.via(p(-77.03)), marks.via(p(-77.04)), p(-77.05)];
  assert.equal(middleCountSaid(allVias, marks.isVia), "4 via points");
  const mixed = [p(-77.0), p(-77.01), marks.via(p(-77.02)), marks.via(p(-77.03)), marks.via(p(-77.04)), p(-77.05)];
  assert.equal(middleCountSaid(mixed, marks.isVia), "1 stop · 3 via points");
  assert.equal(middleCountSaid([p(-77.0), p(-77.01), p(-77.02), p(-77.03)], marks.isVia), "2 stops");
  assert.equal(middleCountSaid([p(-77.0), marks.via(p(-77.01)), p(-77.02)], marks.isVia), "1 via point");
  assert.equal(middleCountSaid([p(-77.0), p(-77.02)], marks.isVia), "");
  // A loop's last point is a stop (Plan's list names it so): the old card's count, now by kind.
  const loop = [p(-77.0), marks.via(p(-77.01)), marks.via(p(-77.02)), p(-77.03)];
  assert.equal(middleCountSaid(loop, marks.isVia, true), "1 stop · 2 via points");
  setLanguageForTest("es");
  try {
    assert.equal(middleCountSaid(mixed, marks.isVia), "1 parada · 3 puntos de paso");
    assert.equal(middleCountSaid(allVias, marks.isVia), "4 puntos de paso");
  } finally {
    setLanguageForTest("en");
  }
});
