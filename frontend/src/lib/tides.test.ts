// Low tides for the beach path (lib/tides.ts): the nearest Gulf station, and its low tides on the ride's day.
import { test } from "node:test";
import assert from "node:assert/strict";
import { loadTides, lowTidesOn, nearestStation, readTides } from "./tides.ts";

const at = (iso: string) => Math.floor(Date.parse(iso) / 60_000);
const RAW = {
  from: "2026-12-23",
  to: "2027-01-23",
  stations: [
    { id: "8725110", name: "Naples (outer coast)", lon: -81.808, lat: 26.132, lows: [[at("2026-12-23T10:34Z"), -13], [at("2026-12-23T22:18Z"), 14], [at("2026-12-24T11:23Z"), -13]] },
    { id: "8726034", name: "Siesta Key, Big Sarasota Pass", lon: -82.565, lat: 27.284, lows: [[at("2026-12-23T12:00Z"), -5]] },
    { id: 7, name: "not a station" },
  ],
};

test("the file is read, and what is not tide data is left out", () => {
  const data = readTides(RAW);
  assert.deepEqual(data?.stations.map((s) => s.id), ["8725110", "8726034"]);
  assert.equal(readTides({ error: "x" }), null);
  assert.equal(readTides(null), null);
});

test("a beach in Bonita Springs takes Naples' tides, one on Siesta Key takes Siesta Key's", () => {
  const data = readTides(RAW)!;
  assert.equal(nearestStation(data, [-81.84, 26.33]).id, "8725110");
  assert.equal(nearestStation(data, [-82.55, 27.26]).id, "8726034");
});

test("the low tides are those of the ride's day on the beach's clock, with their height", () => {
  const naples = readTides(RAW)!.stations[0];
  // 22:18 UTC on the 23rd is 5:18 PM that day in Florida; 11:23 UTC on the 24th is the next morning.
  const lows = lowTidesOn(naples, new Date("2026-12-23T15:00:00Z"));
  assert.deepEqual(lows.map((l) => l.at.toISOString()), ["2026-12-23T10:34:00.000Z", "2026-12-23T22:18:00.000Z"]);
  assert.deepEqual(lows.map((l) => l.feet), [-1.3, 1.4]);
  assert.deepEqual(lowTidesOn(naples, new Date("2027-03-01T15:00:00Z")), []);
});

test("the file is fetched once, and a failed fetch is tried again next time", async () => {
  let calls = 0;
  const failing = (async () => {
    calls++;
    throw new TypeError("offline");
  }) as unknown as typeof fetch;
  assert.equal(await loadTides("/t.json", failing), null);
  const serving = (async () => {
    calls++;
    return new Response(JSON.stringify(RAW));
  }) as unknown as typeof fetch;
  assert.equal((await loadTides("/t.json", serving))?.stations.length, 2);
  await loadTides("/t.json", serving);
  assert.equal(calls, 2);
});
