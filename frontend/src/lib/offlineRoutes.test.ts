// Routes kept for offline, the pure part (lib/offlineRoutes.ts; WEB-NAV-plan.md section 8, P3;
// OWNER-DECISIONS 465a).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  LAST_RIDE_ID,
  MAX_KEPT,
  canKeep,
  focusAfterRemove,
  keepSaid,
  keptDate,
  keptDetail,
  keptFor,
  keptId,
  offlineRouteNotice,
  orphans,
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
  assert.match(keepSaid("kept", "A to B"), /^Kept for offline: A to B, with the map along it\. Open it from Settings/);
  assert.match(keepSaid("partial", "A to B"), /first part/);
  assert.match(keepSaid("no-map", "A to B"), /map along it could not be saved/);
  assert.match(keepSaid("full", "A to B"), /^10 routes are kept, the most this app keeps\. Remove one in Settings first\.$/);
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
