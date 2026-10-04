// A place picked from search goes into the plan the way every other edit
// does (merge re-check B1), and the panel's points list shows its name.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EditHistory } from "./editHistory.ts";
import { planEdits, type Snapshot } from "./planEdits.ts";
import { pickIntoPlan, pointRows, type Place } from "./geocode.ts";
import type { LonLat } from "./geo.ts";

const LINCOLN: Place = { name: "Lincoln Memorial", label: "Lincoln Memorial, Washington", lon: -77.0502, lat: 38.8893, kind: "other" };
const UNION: Place = { name: "Union Station", label: "Union Station, NoMa", lon: -77.0074, lat: 38.8978, kind: "house" };
const DUPONT: Place = { name: "Dupont Circle", label: "Dupont Circle, Washington", lon: -77.0434, lat: 38.9096, kind: "other" };
const at = (p: Place): LonLat => [p.lon, p.lat];

/** App.tsx's plan: its own commit and undo and redo (planEdits.ts), over a stand-in for its state. */
function plan(start: LonLat[] = []) {
  const history = new EditHistory<Snapshot<LonLat[], null>>();
  let points = start;
  const remembered: string[] = [];
  const edits = planEdits<LonLat[], null>({
    history,
    current: () => points,
    ride: () => null,
    set: (next) => {
      points = next;
    },
    applyRide: () => {},
    sync: () => {},
  });
  const deps = {
    current: () => points,
    commit: edits.commit,
    remember: (_p: LonLat, name: string) => {
      remembered.push(name);
    },
  };
  const travel = (direction: "undo" | "redo") => {
    edits.travel(direction);
  };
  return { deps, history, remembered, travel, points: () => points };
}

test("a pick is one undoable step: Ctrl+Z takes back only the pick, redo gives it back", () => {
  const p = plan();
  pickIntoPlan(LINCOLN, "start", p.deps);
  pickIntoPlan(UNION, "end", p.deps);
  assert.deepEqual(p.points(), [at(LINCOLN), at(UNION)]);
  p.travel("undo");
  assert.deepEqual(p.points(), [at(LINCOLN)], "only the last pick is taken back");
  p.travel("redo");
  assert.deepEqual(p.points(), [at(LINCOLN), at(UNION)]);
});

test("a pick after other edits undoes one step, and clears what could be redone", () => {
  const drag: LonLat = [-77.0201, 38.8992];
  const station: LonLat = [-77.0217, 38.8979];
  const p = plan();
  pickIntoPlan(LINCOLN, "start", p.deps);
  pickIntoPlan(UNION, "end", p.deps);
  p.deps.commit([at(LINCOLN), drag, at(UNION)]); // a line drag
  p.deps.commit([at(LINCOLN), station, drag, at(UNION)]); // a station via
  const withStation = p.points();
  pickIntoPlan(DUPONT, "end", p.deps);
  assert.deepEqual(p.points(), [at(LINCOLN), station, drag, at(DUPONT)]);
  p.travel("undo");
  assert.deepEqual(p.points(), withStation, "one step back: the station via is still there");
  p.travel("undo");
  p.travel("redo");
  p.travel("redo");
  assert.deepEqual(p.points(), [at(LINCOLN), station, drag, at(DUPONT)]);
  p.travel("undo");
  pickIntoPlan(LINCOLN, "via", p.deps);
  assert.equal(p.history.canRedo, false, "a new pick replaces what could be redone");
});

test("a pick keeps the name it was found by; a place outside the map changes nothing", () => {
  const p = plan();
  pickIntoPlan(UNION, "start", p.deps);
  assert.deepEqual(p.remembered, ["Union Station"]);
  const outside = { ...DUPONT, lon: -60 };
  assert.equal(pickIntoPlan(outside, "end", p.deps), null);
  assert.deepEqual(p.points(), [at(UNION)]);
  assert.equal(p.history.size, 1, "nothing recorded for a place refused");
});

test("the points list: each point's role, its name when it has one, its coordinates", () => {
  const points: LonLat[] = [at(LINCOLN), [-77.02, 38.9], at(UNION)];
  const names = { name: (pt: LonLat) => (pt[0] === LINCOLN.lon ? { name: LINCOLN.name, label: LINCOLN.label } : undefined) };
  const rows = pointRows(points, names);
  assert.deepEqual(rows.map((r) => r.role), ["Start", "Stop 1", "End"]);
  assert.deepEqual(rows[0].place, { name: LINCOLN.name, label: LINCOLN.label });
  assert.equal(rows[1].place, undefined, "a point with no name yet shows its coordinates");
  assert.match(rows[2].coords, /38\.8978.*-77\.0074/);
});

test("App asks names for the plan's own points and renders the rows from pointRows", () => {
  // The wiring itself, which no helper can hold: the hook is given the
  // points the plan has (the re-check's F06 gave it none), the list is
  // pointRows, and the pick goes through pickIntoPlan with App's commit.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /usePlaceNames\(points\)/);
  assert.match(app, /pointRows\(points, namer, loopVias\)/);
  assert.match(app, /pickIntoPlan\(found, choice, \{\s*current: \(\) => pointsRef\.current,\s*commit,/);
  assert.match(app, /remember: \(p, name, label\) => namer\.remember\(p, name, label\)/);
});
