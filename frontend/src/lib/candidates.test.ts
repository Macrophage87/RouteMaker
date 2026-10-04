/** The routes to choose from (OWNER-DECISIONS 265). */
import assert from "node:assert/strict";
import test from "node:test";
import type { RouteResponse } from "./api.ts";
import { candidateRoute, candidateRows, choiceSaid, rankName, routesOf, statsLine, statsOf } from "./candidates.ts";
import { announceRoute } from "./summary.ts";

function body(over: Partial<RouteResponse> = {}): RouteResponse {
  return {
    preset: "trailmaxxing",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [] },
    distance_m: 93_000,
    duration_s: 20_000,
    climb_m: 300,
    descent_m: 300,
    stress_m: { "1": 50_000, "2": 30_000, "3": 11_000, "4": 400, "5": 20 },
    facility_m: { path: 38_000, protected: 3_000 },
    intersections: [
      { severity: "red" },
      { severity: "orange" },
      { severity: "orange" },
    ] as never,
    effort_m: 150_000,
    attribution: [],
    ...over,
  } as RouteResponse;
}

const ALT = body({ rank: 2, distance_m: 95_000, stress_m: { "3": 10_000, "4": 100 }, intersections: [] });

test("one route has no candidates and no picker", () => {
  assert.deepEqual(routesOf(null), []);
  assert.equal(candidateRows(body()), null);
  assert.equal(candidateRows(body({ candidates: [] })), null);
  assert.equal(candidateRows(body({ candidates: null })), null);
  assert.equal(choiceSaid(body(), 0), null);
  assert.equal(candidateRoute(null, 0), null);
});

test("the answer is first and its candidates follow in rank order", () => {
  const answer = body({ rank: 1, candidates: [ALT, body({ rank: 3 })] });
  assert.deepEqual(
    routesOf(answer).map((r) => r.rank),
    [1, 2, 3],
  );
  assert.equal(candidateRoute(answer, 0), answer);
  assert.equal(candidateRoute(answer, 1), ALT);
  assert.equal(candidateRoute(answer, 7), answer, "out of range is the answer");
  assert.equal(candidateRoute(answer, -1), answer);
});

test("each row says its figures in words, miles first, and names its rank", () => {
  const rows = candidateRows(body({ rank: 1, candidates: [ALT] }))!;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].name, "Route 1, the calmest");
  assert.equal(rows[1].name, "Route 2");
  assert.equal(rankName(3), "Route 3");
  assert.match(rows[0].line, /^57\.8 mi \(93\.0 km\), 0\.3 mi \(0\.4 km\) of heavy-traffic roads \(LTS 4\), 6\.8 mi \(11\.0 km\) of busy roads \(LTS 3\)/);
  assert.match(rows[0].line, /1 very high stress junction, 2 higher stress junctions/);
  assert.match(rows[0].line, /25\.5 mi \(41\.0 km\) on trails and protected lanes/);
  assert.match(rows[0].line, /climb 984 ft \(300 m\)/);
  assert.match(rows[0].line, /effort equal to 93\.2 mi \(150\.0 km\) on the flat/);
  assert.match(rows[1].line, /^59\.0 mi \(95\.0 km\)/);
  assert.match(rows[1].line, /0 very high stress junctions, 0 higher stress junctions/);
});

test("LTS 4 and Avoid count together, and trail is path plus protected", () => {
  const stats = statsOf(body(), 1);
  assert.equal(stats.lts4M, 420);
  assert.equal(stats.trailM, 41_000);
  assert.equal(stats.red, 1);
  assert.equal(stats.orange, 2);
  assert.equal(stats.effortM, 150_000);
  assert.equal(statsOf(body({ effort_m: undefined, facility_m: undefined, intersections: null }), 1).effortM, null);
  assert.doesNotMatch(statsLine(statsOf(body({ effort_m: null }), 1)), /effort equal/);
});

test("choosing one is said with its place, once, and the route's own figures follow", () => {
  const answer = body({ rank: 1, candidates: [ALT] });
  assert.equal(choiceSaid(answer, 0), "Route 1 of 2.");
  assert.equal(choiceSaid(answer, 1), "Route 2 of 2.");
  assert.equal(choiceSaid(answer, 9), "Route 2 of 2.");
  assert.match(announceRoute(candidateRoute(answer, 1)!), /^Route planned: 59\.0 mi/);
});

test("each says how far over the rider's target it is, and only when it is (OWNER-DECISIONS 271)", () => {
  const answer = body({
    rank: 1,
    calm_search: { rate: 10, rounds: 1, excluded: 1, limited: null, target_distance_m: 92_000, over_target_m: 1_000 },
    candidates: [{ ...ALT, over_target_m: 3_000 }, body({ rank: 3, over_target_m: 0 })],
  });
  const rows = candidateRows(answer)!;
  assert.match(rows[0].line, /^57\.8 mi \(93\.0 km\), 0\.6 mi \(1\.0 km\) over your target, 0\.3 mi/);
  assert.match(rows[1].line, /^59\.0 mi \(95\.0 km\), 1\.9 mi \(3\.0 km\) over your target, /);
  assert.doesNotMatch(rows[2].line, /over your target/);
  assert.equal(statsOf(body(), 1).overTargetM, null);
  assert.doesNotMatch(statsLine(statsOf(body(), 1)), /target/);
});
