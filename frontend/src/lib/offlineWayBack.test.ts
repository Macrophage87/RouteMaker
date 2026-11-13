// Off-grid riding in Ride (lib/offlineWayBack.ts): the network fetched with the route, and the way back found on the
// phone made a route Ride rides. Synthetic networks only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse, StressSpan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { REPLAN_OFFLINE, replanTold } from "./navigate.ts";
import { CORRIDOR_GRAPH_VERSION, GRAPH_DEG, type CorridorGraph } from "./offlineRouter.ts";
import { fetchOfflineNetwork, OFFLINE_LINE_POINTS, OFFLINE_RETRIES, OFFLINE_RETRY_MAX_S, offlineWayBackRoute, type OfflineNetwork } from "./offlineWayBack.ts";

const LAT = 38.9;
const KX = 111_195 * Math.cos((LAT * Math.PI) / 180);
const at = (e: number, n: number): LonLat => [-77 + e / KX, LAT + n / 111_195];

/** Streets 200 m apart, `cols` x `rows`, all LTS 1; Row 0 runs along the planned line. */
function grid(cols: number, rows: number): CorridorGraph {
  const nodes: number[] = [];
  const names: string[] = [];
  const name = (n: string) => (names.includes(n) ? names.indexOf(n) : names.push(n) - 1);
  const id = (c: number, r: number) => r * cols + c;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const p = at(c * 200, r * 200);
    nodes.push(Math.round(p[0] / GRAPH_DEG), Math.round(p[1] / GRAPH_DEG));
  }
  const edges: number[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    if (c + 1 < cols) edges.push(id(c, r), id(c + 1, r), 200, 2, 0, name(r === 0 ? "A Street" : `Row ${r}`));
    if (r + 1 < rows) edges.push(id(c, r), id(c, r + 1), 200, 2, 0, name(`Col ${c}`));
  }
  return { v: CORRIDOR_GRAPH_VERSION, nodes, edges, names };
}

const NETWORK: OfflineNetwork = { graph: grid(6, 4), levelFactor: [1, 1, 1, 1, 1, 1.5, 5, 8, 20, 30, 40] };

function planned(): RouteResponse {
  const description: DescriptionEntry[] = [
    { kind: "stretch", from_m: 0, to_m: 1000, from_mi: 0, to_mi: 0.62, street: "A Street", tier: 1, facility: null, turn: null, text: "A Street" },
  ];
  const spans: StressSpan[] = [{ from_m: 0, to_m: 1000, tier: 1, facility: null }];
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(1000, 0)] },
    distance_m: 1000,
    duration_s: 200,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [1],
    description,
    stress_spans: spans,
  } as RouteResponse;
}

test("with no signal, the way back found on the phone is joined to the planned route", () => {
  const route = offlineWayBackRoute(NETWORK, planned(), at(200, 390), 200, []);
  assert.ok(route);
  const line = route.geometry.coordinates;
  // Starts at the rider, ends at the planned route's end.
  assert.ok(Math.abs(line[0][1] - at(200, 390)[1]) < 1e-6);
  assert.deepEqual(line[line.length - 1], at(1000, 0));
  // A turn back onto A Street, said as a turn, then the planned route's own stretch.
  const turns = (route.description ?? []).filter((d) => d.turn);
  assert.ok(turns.some((d) => d.turn?.onto === "A Street" || d.turn?.onto?.startsWith("Col")));
  assert.ok(route.distance_m > 400 && route.distance_m < 1600, `${route.distance_m}`);
});

test("off the network, no offline way back", () => {
  assert.equal(offlineWayBackRoute(NETWORK, planned(), at(200, 3000), 200, []), null);
});

test("the network is fetched with the route's line and ride type, and anything odd is none", async () => {
  let sent: { url: string; body: unknown } | null = null;
  const ok = (async (url: string, init: RequestInit) => {
    sent = { url, body: JSON.parse(String(init.body)) };
    return new Response(JSON.stringify({ ...grid(2, 2), level_factor: NETWORK.levelFactor }), { status: 200 });
  }) as unknown as typeof fetch;
  const got = await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "novice", stress: 40 }, ok);
  assert.ok(got);
  assert.equal(sent!.url, "/api/offline/network");
  assert.deepEqual((sent!.body as { preset: string; stress: number }).preset, "novice");
  const notBuilt = (async () => new Response(JSON.stringify({ error: "not_built" }), { status: 503 })) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, notBuilt), null);
  const offline = (async () => {
    throw new TypeError("Failed to fetch");
  }) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, offline), null);
  const wrong = (async () => new Response(JSON.stringify({ v: 9, nodes: [], edges: [], names: [] }), { status: 200 })) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, wrong), null);
});

test("the offline way back is said as found, also to the stoker", () => {
  assert.equal(replanTold(false, "stoker", REPLAN_OFFLINE), "say");
  assert.equal(replanTold(false, "quiet", REPLAN_OFFLINE), "quiet");
});

test("Ride fetches the network with each route and uses it when a re-plan fails for no signal", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /fetchOfflineNetwork\(route\.geometry\.coordinates as LonLat\[\], \{ preset, stress: dialsRef\.current\.stress, carrying: dialsRef\.current\.carrying \}, undefined, undefined, \(\) => current && !ended\.current\)/);
  assert.match(ride, /if \(!found && failed === "network" && !via && !check && !done && !voided\(\)\) \{/);
  assert.match(ride, /offlineWayBackRoute\(net\.network, routeRef\.current, here, Math\.max\(progressM, closed\), keptPoints\)/);
  assert.match(ride, /note = REPLAN_OFFLINE;/);
  // Ridden only until the signal is back: then planned again on the server.
  assert.match(ride, /offlineRoute\.current = rough \? found : null;/);
  assert.match(ride, /const rough = offlineRoute\.current !== null && offlineRoute\.current === routeRef\.current;/);
});

test("a long route's line is thinned before it is sent, its ends kept", async () => {
  let sent: LonLat[] = [];
  const ok = (async (_url: string, init: RequestInit) => {
    sent = (JSON.parse(String(init.body)) as { line: LonLat[] }).line;
    return new Response(JSON.stringify({ ...grid(2, 2), level_factor: NETWORK.levelFactor }), { status: 200 });
  }) as unknown as typeof fetch;
  const long = Array.from({ length: 9000 }, (_, i) => at(i * 5, 0));
  await fetchOfflineNetwork(long, { preset: "default" }, ok);
  assert.equal(sent.length, OFFLINE_LINE_POINTS);
  assert.deepEqual(sent[0], [Math.round(long[0][0] * 1e6) / 1e6, Math.round(long[0][1] * 1e6) / 1e6]);
  assert.deepEqual(sent[sent.length - 1], [Math.round(long[8999][0] * 1e6) / 1e6, Math.round(long[8999][1] * 1e6) / 1e6]);
});

test("a busy server is asked again after its Retry-After; not built is not", async () => {
  const waits: number[] = [];
  const wait = async (s: number) => {
    waits.push(s);
  };
  let calls = 0;
  const busyOnce = (async () => {
    calls += 1;
    if (calls === 1) return new Response(JSON.stringify({ error: "busy" }), { status: 503, headers: { "Retry-After": "2" } });
    return new Response(JSON.stringify({ ...grid(2, 2), level_factor: NETWORK.levelFactor }), { status: 200 });
  }) as unknown as typeof fetch;
  assert.ok(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, busyOnce, wait));
  assert.deepEqual(waits, [2]);
  let built = 0;
  const notBuilt = (async () => {
    built += 1;
    return new Response(JSON.stringify({ error: "not_built" }), { status: 503 });
  }) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, notBuilt, wait), null);
  assert.equal(built, 1);
  let busy = 0;
  const alwaysBusy = (async () => {
    busy += 1;
    return new Response("{}", { status: 503, headers: { "Retry-After": "2" } });
  }) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, alwaysBusy, wait), null);
  assert.equal(busy, 1 + OFFLINE_RETRIES);
  assert.ok(Math.max(...waits) <= OFFLINE_RETRY_MAX_S);
  // The per-minute count's long wait, an empty header, or a ride ended meanwhile: not asked again.
  for (const headers of [{ "Retry-After": "60" }, { "Retry-After": "" }]) {
    let n = 0;
    const once = (async () => {
      n += 1;
      return new Response("{}", { status: 429, headers });
    }) as unknown as typeof fetch;
    assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, once, wait), null);
    assert.equal(n, 1);
  }
  let ended = 0;
  const busyAgain = (async () => {
    ended += 1;
    return new Response("{}", { status: 503, headers: { "Retry-After": "1" } });
  }) as unknown as typeof fetch;
  assert.equal(await fetchOfflineNetwork([at(0, 0), at(100, 0)], { preset: "default" }, busyAgain, wait, () => false), null);
  assert.equal(ended, 1);
});

test("the way back never joins behind a road the rider marked closed", () => {
  // Rider beside A Street at 200 m, road closed up to 600 m: the join is past it.
  const route = offlineWayBackRoute(NETWORK, planned(), at(200, 390), 600, []);
  assert.ok(route);
  const line = route.geometry.coordinates;
  const joinedAt = line.findIndex((p, i) => i > 0 && Math.abs(p[1] - LAT) < 1e-6);
  assert.ok(joinedAt > 0);
  assert.ok((line[joinedAt][0] - -77) * KX >= 600 - 1, `${(line[joinedAt][0] - -77) * KX}`);
});
