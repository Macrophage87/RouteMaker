// Learning from each ride (lib/rideFeedback.ts; the 2026-11-12 backlog, item 7). Made-up roads and points, not a real ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import { CLOSED_SAME_M, FELT_MOST, closedSpots, feltStretches, levelSaid, sendClosedSpots } from "./rideFeedback.ts";
import type { RiddenStretch } from "./rideStats.ts";

const DEG_PER_M = 1 / 111_195;
const at = (m: number): [number, number] => [-77, 38.9 + m * DEG_PER_M];
const r = (street: string | null, tier: number, m: number, p = 0): RiddenStretch => ({ street, tier, m, point: at(p) });

test("the streets offered: the same street and level added up, the short ones left out, longest first, at most FELT_MOST", () => {
  const ridden = [r("A St", 2, 300), r("B St", 4, 900, 300), r("A St", 2, 300, 1200), r("C St", 1, 50), r(null, 3, 400), r(null, 3, 400)];
  const felt = feltStretches({ ridden });
  assert.deepEqual(
    felt.map((f) => [f.street, f.tier, Math.round(f.m)]),
    [
      ["B St", 4, 900],
      ["A St", 2, 600],
      [null, 3, 400],
      [null, 3, 400],
    ],
  );
  assert.equal(felt[0].label, "B St · LTS 4 · 0.6 mi (0.9 km)");
  // The first point it was ridden at, where the road is looked up.
  assert.deepEqual(felt[1].point, at(0));
  const many = Array.from({ length: 10 }, (_, i) => r(`S${i}`, 2, 500 + i));
  assert.equal(feltStretches({ ridden: many }).length, FELT_MOST);
  assert.deepEqual(feltStretches({}), []);
});

test("a path or an unnamed road is never added to another of the same words", () => {
  const path = (m: number, p: number): RiddenStretch => ({ street: "a path", named: false, tier: 1, m, point: at(p) });
  const felt = feltStretches({ ridden: [path(400, 0), r("A St", 2, 300, 400), path(500, 700)] });
  assert.deepEqual(
    felt.map((f) => [f.street, Math.round(f.m)]),
    [
      ["a path", 500],
      ["a path", 400],
      ["A St", 300],
    ],
  );
});

test("figures kept by an older page, or damaged, give no lines rather than an error", () => {
  assert.deepEqual(feltStretches({ ridden: "x" as never }), []);
  assert.deepEqual(closedSpots({ closed: [null, "y"] as never }), []);
});

test("a level is said as the line draws it", () => {
  assert.equal(levelSaid(2.5), "LTS 2.5");
  assert.equal(levelSaid(5), "Avoid");
});

test("Road closed spots: the middle of each stretch's first piece, two presses at one closure counted once", () => {
  const spots = closedSpots({ closed: [[at(0), at(100), at(150)], [at(10), at(90)], [at(1000), at(1150)]] });
  assert.equal(spots.length, 2);
  assert.ok(Math.abs(spots[0][1] - at(50)[1]) < 1e-9);
  assert.ok(CLOSED_SAME_M > 0 && Math.abs(spots[1][1] - at(1075)[1]) < 1e-9);
  assert.deepEqual(closedSpots({}), []);
});

/** A server: segment-info at a point finds way 11 near 0 and way 22 further on; nothing past 5000 m. */
function server(log: { url: string; body?: unknown }[]) {
  return (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    log.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    if (url.includes("/api/segment-info")) {
      const lat = Number(new URL(url).searchParams.get("lat"));
      const m = (lat - 38.9) / DEG_PER_M;
      if (m > 5000) return json(200, { found: false, title: "", tier: null, open: null, osm_way_id: null, distance_m: null, sections: [] });
      const way = m < 500 ? 11 : 22;
      return json(200, { found: true, title: "Road", tier: 3, step: 3, half_steps: true, open: true, osm_way_id: way, distance_m: 2, on_way: [-77.0001, lat], sections: [] });
    }
    if (url.includes("/api/stress-suggestions/ticket")) return json(200, { ticket: "t", reasons: [["closed", "Closed"]] });
    if (url.includes("/api/stress-suggestions/signed-out")) return json(200, { id: 1, message: "Thanks." });
    return json(404, {});
  }) as typeof fetch;
}

test("sending the spots: each road once, as the short form's Closed at its own level, marked from the ride, the road's own point", async () => {
  const log: { url: string; body?: unknown }[] = [];
  const outcome = await sendClosedSpots("https://example.test", [at(10), at(100), at(1000), at(9000)], () => "c", server(log));
  assert.deepEqual(outcome, { sent: 2, failed: 1, left: [at(9000)] });
  const sends = log.filter((l) => l.url.endsWith("/signed-out")).map((l) => l.body as Record<string, unknown>);
  assert.equal(sends.length, 2);
  assert.deepEqual(
    sends.map((b) => [b.osm_way_id, b.step, b.reasons, b.from_ride, b.lon]),
    [
      [11, 3, ["closed"], true, -77.0001],
      [22, 3, ["closed"], true, -77.0001],
    ],
  );
  // Nothing of the rider's in a send: no time, no path, no other field.
  assert.deepEqual(Object.keys(sends[0]).sort(), ["from_ride", "lat", "lon", "osm_way_id", "other", "reasons", "step", "ticket", "website"]);
});

test("a server that cannot be reached: nothing sent, all counted as not sent", async () => {
  const outcome = await sendClosedSpots("https://example.test", [at(10)], () => null, (async () => {
    throw new TypeError("offline");
  }) as typeof fetch);
  assert.deepEqual(outcome, { sent: 0, failed: 1, left: [at(10)] });
});
