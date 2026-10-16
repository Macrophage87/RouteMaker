// Snapping an opened track to the map's ways (PLAN.md, Import: map matching; POST /api/match).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import { MATCH_MAX_POINTS, fitLine, matchFailedSaid, matchTrack, matchedPlan, matchedSaid, thinForMatch } from "./gpxMatch.ts";
import { waypointsShownText } from "./gpxText.ts";
import { rideAfterImport } from "./gpxEdit.ts";
import { startDials } from "./dials.ts";

const LINE: LonLat[] = Array.from({ length: 40 }, (_, i) => [-77.03 + i * 0.0005, 38.9 + (i % 7) * 0.0003]);
const PLAN: ImportedPlan = {
  points: [LINE[0], LINE[39]],
  preset: null,
  source: "track",
  reference: LINE,
  referenceM: 1800,
  notes: [],
  verbatim: { text: "<gpx/>", track: LINE.map(([lon, lat]) => [lon, lat] as [number, number]) },
};

function answering(status: number, body: unknown, seen: { url?: string; body?: string } = {}): typeof fetch {
  return (async (url: string, init: RequestInit) => {
    seen.url = url;
    seen.body = String(init.body);
    return new Response(JSON.stringify(body), { status });
  }) as unknown as typeof fetch;
}

test("only the line and the ride (type, trails off, assist) are sent, thinned to the cap with its ends kept", async () => {
  const seen: { url?: string; body?: string } = {};
  const outcome = await matchTrack("https://x.test", LINE, { preset: "default" }, answering(200, { line: LINE.slice(0, 5), matched_share: 0.96 }, seen));
  assert.deepEqual(outcome, { ok: true, line: LINE.slice(0, 5), share: 0.96 });
  assert.equal(seen.url, "https://x.test/api/match");
  const sent = JSON.parse(seen.body ?? "{}");
  assert.deepEqual(Object.keys(sent).sort(), ["assist", "points", "preset", "trails_off"]);
  assert.equal(sent.trails_off, false);
  // "Keep to roads, not trails" goes with it, so the track is never snapped onto a trail.
  await matchTrack("https://x.test", LINE, { preset: "gravel", trailsOff: true, assist: true }, answering(200, { line: LINE, matched_share: 1 }, seen));
  const ride = JSON.parse(seen.body ?? "{}");
  assert.deepEqual([ride.preset, ride.trails_off, ride.assist], ["gravel", true, true]);
  const long = Array.from({ length: MATCH_MAX_POINTS * 2 + 1 }, (_, i): LonLat => [-77 + i * 1e-6, 38.9]);
  const thin = thinForMatch(long);
  assert.equal(thin.length, MATCH_MAX_POINTS);
  assert.deepEqual(thin[0], long[0]);
  assert.deepEqual(thin.at(-1), [Math.round(long.at(-1)![0] * 1e6) / 1e6, 38.9]);
});

test("a refusal, too little matched, or no router is a sentence, and the file's track stays the plan's", async () => {
  const refused = await matchTrack("https://x.test", LINE, { preset: "default" }, answering(422, { error: "No street or path along the track could be found." }));
  assert.deepEqual(refused, { ok: false, message: "No street or path along the track could be found." });
  const little = await matchTrack("https://x.test", LINE, { preset: "default" }, answering(200, { line: LINE, matched_share: 0.3 }));
  assert.ok(!little.ok && /30%/.test(little.message));
  const busy = await matchTrack("https://x.test", LINE, { preset: "default" }, answering(429, {}));
  assert.ok(!busy.ok && /try again/.test(busy.message));
  const down = await matchTrack("https://x.test", LINE, { preset: "default" }, (async () => {
    throw new TypeError("offline");
  }) as unknown as typeof fetch);
  assert.ok(!down.ok);
  assert.match(matchFailedSaid("Why."), /^The track was not snapped\. Why\. The plan still follows the file's own track\.$/);
});

test("the snapped plan follows the snapped line and keeps the file as it came", () => {
  const snapped = LINE.map(([lon, lat]): LonLat => [lon + 0.00001, lat]);
  const next = matchedPlan(PLAN, snapped, 0.96);
  assert.deepEqual(fitLine(next), snapped);
  assert.deepEqual(fitLine(PLAN), LINE);
  assert.equal(next.reference, PLAN.reference);
  assert.equal(next.verbatim, PLAN.verbatim);
  // No ride type and no sliders: opening it keeps the ride the rider has now.
  const named = matchedPlan({ ...PLAN, preset: "mass-ride", dials: { stress: 20 } }, snapped, 0.96);
  assert.equal(named.preset, null);
  assert.ok(!("dials" in named));
  assert.deepEqual(rideAfterImport(named, { preset: "gravel", dials: startDials("gravel") }), { preset: "gravel", dials: startDials("gravel") });
  assert.ok(next.points.length >= 2 && next.points.every((p) => snapped.some((q) => q[0] === p[0] && q[1] === p[1])));
  // US units first, metric in brackets.
  assert.match(matchedSaid(next.matched!), /^Snapped 96% of the track to the map's streets and paths, [\d.]+ mi \([\d.]+ km\) in all;/);
});

test("named waypoints are said by name, the first eight and a count", () => {
  assert.equal(waypointsShownText(["Coffee"]), "Its named waypoint is marked on the map: Coffee.");
  const names = Array.from({ length: 10 }, (_, i) => `W${i}`);
  assert.equal(waypointsShownText(names), "Its 10 named waypoints are marked on the map: W0, W1, W2, W3, W4, W5, W6, W7, and 2 more.");
});
