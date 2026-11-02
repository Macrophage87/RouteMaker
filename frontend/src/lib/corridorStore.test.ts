// The ride's corridor in the browser (lib/corridorStore.ts): a re-plan's keepCorridor never leaves two
// prefetches running, and End ride stops what is running. In Node there is no Cache Storage, IndexedDB
// or localStorage, and the tiles' fetches fail, so only the ordering is tested here.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { copyCorridor, corridorStress, endCorridor, keepCorridor } from "./corridorStore.ts";
import type { LonLat } from "./geo.ts";

const LINE: LonLat[] = [
  [-77.05, 38.9],
  [-77.04, 38.9],
];

test("keepCorridor: two calls that both waited on the clear leave one prefetch running; End ride stops it", async () => {
  const first = keepCorridor(LINE);
  const second = keepCorridor(LINE);
  const a = await first;
  assert.equal(a.stopped, true, "the older call is stopped by the newer one");
  await endCorridor();
  const b = await second;
  assert.equal(b.stopped, true, "End ride stops the newer one");
});

test("keepCorridor: a call still waiting when End ride comes starts nothing", async () => {
  const pending = keepCorridor(LINE, true);
  await endCorridor();
  const result = await pending;
  assert.equal(result.stopped, true);
  assert.equal(result.total, 0);
});

test("endCorridor with a hand-on: a Start ride that comes while the hand-on runs waits for it, and is not stopped by it", async () => {
  let release = () => {};
  const order: string[] = [];
  const ended = endCorridor(async (kept) => {
    order.push(`hand-on ${kept.tiles.length} tiles`);
    await new Promise<void>((resolve) => (release = resolve));
    order.push("hand-on done");
  });
  assert.equal(corridorStress.riding(), false, "End ride stops keeping at once");
  const ride = keepCorridor(LINE, true);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(corridorStress.riding(), false, "the new ride waits for the old ride's hand-on");
  release();
  await ended;
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(corridorStress.riding(), true, "the new ride keeps; the old clear came before it, not after");
  assert.deepEqual(order, ["hand-on 0 tiles", "hand-on done"]);
  await endCorridor();
  assert.equal((await ride).stopped, true);
});

test("End ride keeps the tiles for the same route's day (battery audit, 2026-11-01): only another route or a day deletes them", () => {
  const store = readFileSync(new URL("./corridorStore.ts", import.meta.url), "utf8");
  const end = store.slice(store.indexOf("export function endCorridor("), store.indexOf("export function clearCorridor("));
  assert.doesNotMatch(end, /stopKeeping|clearKept/, "End ride stops keeping and deletes nothing");
  const keep = store.slice(store.indexOf("export async function keepCorridor("), store.indexOf("export interface CorridorSnapshot"));
  assert.match(keep, /if \(keptForRoute\(kept, route, now\)\) \{[^]*?\} else \{\s*await stopKeeping\(\);/);
  assert.match(store, /due = sweepDue\(localStorage\.getItem\(STAMP_KEY\), now\);/);
});

test("copyCorridor (the app hidden mid-ride, review RIDE-1): the hand-on sees what is kept, and keeping goes on", async () => {
  const ride = keepCorridor(LINE, true);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(corridorStress.riding(), true);
  const seen: number[] = [];
  await copyCorridor(async (kept) => {
    seen.push(kept.tiles.length);
  });
  assert.deepEqual(seen, [0]);
  assert.equal(corridorStress.riding(), true, "the ride keeps its corridor");
  // A copy that fails changes nothing either.
  await copyCorridor(async () => {
    throw new Error("quota");
  });
  assert.equal(corridorStress.riding(), true);
  await endCorridor();
  assert.equal((await ride).stopped, true);
});
