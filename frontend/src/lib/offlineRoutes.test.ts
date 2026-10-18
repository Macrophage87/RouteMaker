// Routes kept for offline, the pure part (lib/offlineRoutes.ts; WEB-NAV-plan.md section 8, P3;
// OWNER-DECISIONS 465a).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  LAST_RIDE_ID,
  MAX_KEPT,
  canKeep,
  keptPlanKey,
  keepOffered,
  KEEP_IN_BROWSER_TAB,
  focusAfterRemove,
  keepSaid,
  keptDate,
  keptDetail,
  keptFor,
  keptId,
  offlineRouteNotice,
  orphans,
  keptRecord,
  progressSaver,
  removeFailedSaid,
  unreferenced,
  removedSaid,
  routeTitle,
  sizeText,
  sortKept,
  storageNote,
  type KeptRoute,
} from "./offlineRoutes.ts";

const DAY = 24 * 60 * 60_000;
const NOW = new Date(2026, 9, 10, 12).getTime();

function kept(id: string, over: Partial<KeptRoute> = {}): KeptRoute {
  return { id, plan: id, title: id, distanceM: 6800, savedAt: NOW, lastRide: false, answer: null, tiles: [], ranges: [], bytes: 2_000_000, complete: true, ...over };
}

test("a kept route's id is its plan (keeping it again replaces it); the last ride has one id", () => {
  assert.equal(keptId("#p=1&preset=default", false), "#p=1&preset=default");
  assert.equal(keptId("#p=1&preset=default", true), LAST_RIDE_ID);
});

test("the list: the last ride first, then the newest first", () => {
  const list = sortKept([kept("a", { savedAt: NOW - 2 * DAY }), kept("b", { savedAt: NOW }), kept(LAST_RIDE_ID, { lastRide: true, savedAt: NOW - 5 * DAY })]);
  assert.deepEqual(list.map((r) => r.id), [LAST_RIDE_ID, "b", "a"]);
});

test("at most ten kept; replacing one already kept is always allowed", () => {
  const full = Array.from({ length: MAX_KEPT }, (_, i) => kept(`r${i}`));
  assert.equal(MAX_KEPT, 10);
  assert.equal(canKeep(full, "new"), false);
  assert.equal(canKeep(full, "r3"), true);
  assert.equal(canKeep(full.slice(1), "new"), true);
});

test("Keep for offline is offered in the installed app and, by the owner's choice of 2026-10-10, in a browser tab too", () => {
  assert.equal(KEEP_IN_BROWSER_TAB, true);
  assert.equal(keepOffered(true), true);
  assert.equal(keepOffered(false), true);
  assert.equal(keepOffered(false, false), false, "the switch off: the installed app only");
});

test("the last ride is not one of the ten: it is always kept, replacing the one before, and never blocks the rider's own", () => {
  const full = Array.from({ length: MAX_KEPT }, (_, i) => kept(`r${i}`));
  assert.equal(canKeep(full, LAST_RIDE_ID), true);
  const nine = [...full.slice(1), kept(LAST_RIDE_ID, { lastRide: true })];
  assert.equal(canKeep(nine, "new"), true);
});

test("the keep key is the planner's lookup key: Mass Ride's ride size (never sent) and the private weight are left out", () => {
  const points: [number, number][] = [
    [-77.04, 38.91],
    [-77.01, 38.89],
  ];
  const dials = { stress: 60, hills: 50 };
  // As App keeps it (the dials shown, with the ride size) and as the scheduler looks it up (the dials sent: no ride size, the weight added).
  const kept = keptPlanKey(points, "mass-ride", { ...dials, rideSize: 1200 });
  const lookedUp = keptPlanKey(points, "mass-ride", { ...dials, systemWeightKg: 94 });
  assert.equal(kept, lookedUp);
  assert.ok(!/riders=|weight/.test(kept), kept);
  assert.notEqual(keptPlanKey(points, "default", dials), kept, "another ride type is another route");
});

test("with no network, a plan's kept route answers: the rider's own before the last ride's", () => {
  const list = [kept(LAST_RIDE_ID, { plan: "#x", lastRide: true }), kept("#x"), kept("#y")];
  assert.equal(keptFor(list, "#x")?.id, "#x");
  assert.equal(keptFor([list[0], list[2]], "#x")?.id, LAST_RIDE_ID);
  assert.equal(keptFor(list, "#z"), undefined);
});

test("a removal frees only what no remaining route uses (shared tiles, the base map's header and directories)", () => {
  const removed = kept("a", { tiles: ["t1", "t2", "glyph", "t1"], ranges: ["0:16384", "500:40", "900:40"] });
  const remaining = [kept("b", { tiles: ["t2", "glyph"], ranges: ["0:16384", "900:40"] }), kept("c", { tiles: [], ranges: [] })];
  assert.deepEqual(orphans(removed, remaining), { tiles: ["t1"], ranges: ["500:40"] });
  assert.deepEqual(orphans(removed, []), { tiles: ["t1", "t2", "glyph"], ranges: ["0:16384", "500:40", "900:40"] });
});

test("a route's name from its first and last points' names, or Start and End; a loop by its start", () => {
  assert.equal(routeTitle("Union Station", "Dupont Circle", false), "Union Station to Dupont Circle");
  assert.equal(routeTitle(undefined, " ", false), "Start to End");
  assert.equal(routeTitle("Union Station", "Union Station", true), "Loop from Union Station");
});

test("the row's details: miles first with kilometres in brackets, when, and about how much", () => {
  assert.equal(keptDate(NOW, NOW), "Oct 10");
  assert.equal(keptDate(new Date(2025, 2, 3, 12).getTime(), NOW), "Mar 3, 2025");
  assert.equal(sizeText(12.4 * 1024 * 1024), "12 MB");
  assert.equal(sizeText(800 * 1024), "800 KB");
  assert.equal(sizeText(10), "1 KB");
  assert.equal(keptDetail(kept("a"), NOW), "4.2 mi (6.8 km). Kept Oct 10. About 2 MB.");
  assert.equal(keptDetail(kept("b", { lastRide: true, complete: false }), NOW), "4.2 mi (6.8 km). Last ride, kept Oct 10. About 2 MB. Part of the map along it is not saved.");
});

test("what a keep press says, for each outcome", () => {
  assert.match(keepSaid("kept", "A to B"), /^Kept for offline: A to B, with the map along it\. Open it from Save & load/);
  assert.match(keepSaid("partial", "A to B"), /first part/);
  assert.match(keepSaid("no-map", "A to B"), /map along it could not be saved/);
  assert.match(keepSaid("full", "A to B"), /^10 routes are kept, the most this app keeps\. Remove one in Save & load first\.$/);
  assert.match(keepSaid("failed", "A to B"), /refused/);
});

test("the storage note: what persist() said, and Safari's seven days for a tab, not for the installed app", () => {
  assert.equal(storageNote(true, true), "Your browser will keep them until you remove them.");
  assert.match(storageNote(false, true), /^Your browser may clear them if the device runs short of space\.$/);
  assert.match(storageNote(null, false), /seven days without a visit; the installed app keeps them\.$/);
});

test("the planner's notice for a kept answer, and a removal's sentence", () => {
  assert.equal(offlineRouteNotice(kept("a"), NOW), "No signal: this is the route you kept on Oct 10. It may be out of date; plan again when you have a signal.");
  assert.equal(removedSaid("A to B", 0), "Removed A to B. No routes are kept.");
  assert.equal(removedSaid("A to B", 1), "Removed A to B. 1 route is kept.");
  assert.equal(removedSaid("A to B", 3), "Removed A to B. 3 routes are kept.");
});

test("after a removal the focus goes to the next row's Remove, the previous one at the end, else the heading", () => {
  assert.deepEqual(focusAfterRemove(0, 2), { row: 0 });
  assert.deepEqual(focusAfterRemove(2, 2), { row: 1 });
  assert.equal(focusAfterRemove(0, 0), "heading");
});

test("no position is kept: a kept route holds the plan, the answer, tile and range keys and a time, nothing else", () => {
  const source = readFileSync(new URL("./offlineRoutes.ts", import.meta.url), "utf8");
  const shape = /export interface KeptRoute<Answer = unknown> \{([\s\S]*?)\n\}/.exec(source)?.[1] ?? "";
  const fields = [...shape.matchAll(/^\s+(\w+):/gm)].map((m) => m[1]).sort();
  assert.deepEqual(fields, ["answer", "bytes", "complete", "distanceM", "id", "lastRide", "plan", "ranges", "savedAt", "tiles", "title"]);
  for (const name of ["offlineKeep.ts", "offlineRouteStore.ts"]) {
    const code = readFileSync(new URL(`./${name}`, import.meta.url), "utf8");
    assert.ok(!/\bfix\b|coords\.|watchPosition|getCurrentPosition|accuracy/i.test(code), `${name} touches a position`);
  }
});

test("keeping a plan again starts from what its record already names, so a keep cut short leaves nothing unnamed", () => {
  const fields = { id: "#a", plan: "#a", title: "A", distanceM: 1000, answer: null, lastRide: false };
  const fresh = keptRecord(fields, undefined, NOW);
  assert.deepEqual([fresh.tiles, fresh.ranges, fresh.bytes, fresh.complete], [[], [], 0, false]);
  const before = kept("#a", { tiles: ["/tiles/stress/14/1/2.pbf"], ranges: ["0:127"], bytes: 900 });
  const again = keptRecord(fields, before, NOW + DAY);
  assert.deepEqual(again.tiles, before.tiles);
  assert.deepEqual(again.ranges, before.ranges);
  assert.equal(again.bytes, 900);
  assert.equal(again.complete, false);
  again.tiles.push("/x");
  assert.equal(before.tiles.length, 1, "the old record's lists are not shared");
});

test("a keep writes its record as it goes, at most every so often, and once more at the end", async () => {
  let clock = 0;
  const writes: number[] = [];
  const saver = progressSaver(async () => void writes.push(clock), 2000, () => clock);
  saver.noted();
  assert.deepEqual(writes, [], "not again within the interval");
  clock = 2500;
  saver.noted();
  saver.noted();
  await Promise.resolve();
  assert.deepEqual(writes, [2500], "one write, however many tiles came");
  clock = 3000;
  await saver.flush();
  assert.deepEqual(writes, [2500, 3000], "the end always writes");
});

test("the sweep deletes only what no kept route names; tile URLs are compared as the store spells them", () => {
  const routes = [kept("#a", { tiles: ["/tiles/stress/14/1/2.pbf?rev=3"], ranges: ["0:127", "500:20"] })];
  const norm = (url: string) => new URL(url, "http://127.0.0.1/").href;
  const free = unreferenced(routes, ["http://127.0.0.1/tiles/stress/14/1/2.pbf?rev=3", "http://127.0.0.1/tiles/stress/14/1/3.pbf"], ["0:127", "500:20", "900:40"], norm);
  assert.deepEqual(free, { tiles: ["http://127.0.0.1/tiles/stress/14/1/3.pbf"], ranges: ["900:40"] });
  assert.deepEqual(unreferenced([], ["a"], ["b"]), { tiles: ["a"], ranges: ["b"] }, "no route: all of it");
});

test("a removal that fails says so, and that the route is still kept", () => {
  assert.equal(removeFailedSaid("Dupont Circle to Union Station"), "Could not remove Dupont Circle to Union Station. It is still kept; try again.");
});
