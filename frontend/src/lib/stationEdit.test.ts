// A station's Start here / End here / Add as stop as an edit of the plan.
import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { EditHistory, step } from "./editHistory.ts";
import { stationEdit } from "./railStations.ts";
import { pointName } from "./summary.ts";

const STATION: LonLat = [-77.02791, 38.89893];
const plan = (n: number): LonLat[] => Array.from({ length: n }, (_, i) => [-77 + i * 0.001, 38.9] as LonLat);

test("each role sets the point it names, and says which index that is", () => {
  const cases: Array<[number, "start" | "end" | "via"]> = [
    [0, "start"],
    [1, "start"],
    [1, "end"],
    [3, "start"],
    [3, "end"],
    [3, "via"],
  ];
  for (const [n, role] of cases) {
    const edit = stationEdit(plan(n), STATION, role);
    assert.ok("next" in edit, `${role} at ${n}`);
    assert.deepEqual(edit.next[edit.index], STATION, `${role} at ${n}`);
    if (role === "start") assert.equal(edit.index, 0);
    if (role === "end") assert.equal(edit.index, edit.next.length - 1);
    if (role === "via") assert.ok(edit.index > 0 && edit.index < edit.next.length - 1);
  }
});

test("End at the station that is already Start is the end, not the start", () => {
  // The fixtures hand out one coordinate array per station, so both ends can be the same object.
  const start = stationEdit([], STATION, "start");
  assert.ok("next" in start);
  const end = stationEdit(start.next, STATION, "end");
  assert.ok("next" in end);
  assert.equal(end.index, 1);
  assert.equal(end.next.length, 2);
  // And where the plan's start is that very array.
  const same = stationEdit([STATION, [-77.01, 38.9]], STATION, "end");
  assert.ok("next" in same);
  assert.equal(same.index, 1);
  const via = stationEdit([STATION, [-77.01, 38.9], [-77.02, 38.91]], STATION, "via");
  assert.ok("next" in via);
  assert.ok(via.index > 0, "a via at the start's station is not the start");
});

test("a via is refused at the 25-point cap, and fits one below it", () => {
  const below = stationEdit(plan(MAX_POINTS - 1), STATION, "via");
  assert.ok("next" in below);
  assert.equal(below.next.length, MAX_POINTS);
  assert.deepEqual(stationEdit(plan(MAX_POINTS), STATION, "via"), { refused: "cap" });
  // Start and End replace a point, so the cap does not stop them.
  for (const role of ["start", "end"] as const) {
    const edit = stationEdit(plan(MAX_POINTS), STATION, role);
    assert.ok("next" in edit, role);
    assert.equal(edit.next.length, MAX_POINTS);
  }
});

test("a role the plan does not offer is refused, not a cap", () => {
  assert.deepEqual(stationEdit([], STATION, "end"), { refused: "role" });
  assert.deepEqual(stationEdit(plan(1), STATION, "via"), { refused: "role" });
});

test("the edit leaves the plan it was given alone", () => {
  const points = plan(3);
  const copy = points.map((p) => [...p]);
  stationEdit(points, STATION, "via");
  stationEdit(points, STATION, "start");
  assert.deepEqual(points, copy);
});

test("a station's edit, recorded as App's commit does, is undone and redone exactly", () => {
  const history = new EditHistory<LonLat[]>();
  const before = plan(2);
  const edit = stationEdit(before, STATION, "via");
  assert.ok("next" in edit);
  history.record(before);
  const undone = step(history, "undo", edit.next);
  assert.deepEqual(undone, before);
  assert.deepEqual(step(history, "redo", undone!), edit.next);
});

test("Add as via at the station that is already the End is a stop, and is announced as one", () => {
  // The same array as the End, as the fixtures hand it out.
  const points: LonLat[] = [[-77.05, 38.9], [-77.04, 38.91], STATION];
  const edit = stationEdit(points, STATION, "via");
  assert.ok("next" in edit);
  assert.equal(edit.next.length, 4);
  assert.ok(edit.index > 0 && edit.index < edit.next.length - 1, `index ${edit.index}`);
  assert.equal(edit.next[edit.index], STATION);
  assert.equal(edit.next[edit.next.length - 1], STATION, "the End is still the station");
  assert.match(pointName(edit.index, edit.next.length), /^Stop [0-9]/);
});
