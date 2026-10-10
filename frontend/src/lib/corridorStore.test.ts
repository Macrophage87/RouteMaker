// The ride's corridor in the browser (lib/corridorStore.ts): a re-plan's keepCorridor never leaves two
// prefetches running, and End ride stops what is running. In Node there is no Cache Storage, IndexedDB
// or localStorage, and the tiles' fetches fail, so only the ordering is tested here.
import { test } from "node:test";
import assert from "node:assert/strict";
import { clearCorridor, keepCorridor } from "./corridorStore.ts";
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
  await clearCorridor();
  const b = await second;
  assert.equal(b.stopped, true, "End ride stops the newer one");
});

test("keepCorridor: a call still waiting when End ride comes starts nothing", async () => {
  const pending = keepCorridor(LINE, true);
  await clearCorridor();
  const result = await pending;
  assert.equal(result.stopped, true);
  assert.equal(result.total, 0);
});
