// The API's refusals, mapped to what a rider is told. Properties, not sentences:
// each status lands on its own kind, a Retry-After is carried through, and the
// server's own `error` text is shown where it says something the status does not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { describeError, parseRetryAfter, requestRoute, type ErrorKind } from "./api.ts";

test("each contract status maps to its own kind", () => {
  const cases: Array<[number, unknown, ErrorKind]> = [
    [400, { error: "point 0 is outside the area this map covers" }, "bad-input"],
    [400, { error: "the route is too long to plan in one request; split it" }, "too-long"],
    [404, { error: "No route joins these points on this preset." }, "no-route"],
    [422, { error: "No route joins these points on this preset." }, "no-route"],
    [429, { error: "slow down" }, "rate-limited"],
    [500, { error: "Something went wrong planning this route." }, "server"],
    [502, { error: "The router is not answering; try again shortly." }, "router-down"],
    [503, { error: "Planning this route took too long; try again shortly." }, "timed-out"],
    [504, null, "timed-out"],
    [409, { error: "long", code: "confirm_long", span_km: 162 }, "confirm-long"],
  ];
  for (const [status, body, kind] of cases) {
    assert.equal(describeError(status, body, null).kind, kind, `status ${status}`);
  }
  const kinds = new Set(cases.map(([s, b]) => describeError(s, b, null).kind));
  assert.equal(kinds.size, 8);
});

test("every mapped error has a title and a message to show", () => {
  for (const status of [400, 404, 422, 429, 500, 502, 503, 504, 418, 0]) {
    const described = describeError(status, null, null);
    assert.ok(described.title.length > 0, `status ${status} has no title`);
    assert.ok(described.message.length > 0, `status ${status} has no message`);
  }
});

test("too long is recognised from the message, not from every 400", () => {
  assert.equal(describeError(400, { error: "points: too short" }, null).kind, "bad-input");
  assert.equal(describeError(400, { error: "The route is TOO LONG to plan" }, null).kind, "too-long");
  assert.equal(describeError(400, "not json", null).kind, "bad-input");
});

test("the server's explanation of a missing route reaches the rider", () => {
  const detail = "Mass Ride routes only on roadways, and removing trails can leave no connection.";
  assert.ok(describeError(422, { error: detail }, null).message.includes(detail));
});

test("an input refusal is said in the rider's words, not the validator's", () => {
  const raw = "points: Value error, point 1 is outside the area this map covers";
  const message = describeError(400, { error: raw }, null).message;
  assert.match(message, /outside the area this map covers/);
  assert.doesNotMatch(message, /Value error|points:/);
  const other = describeError(400, { error: "preset: Input should be 'default'" }, null).message;
  assert.doesNotMatch(other, /preset:/);
  assert.match(other, /Input should be/);
  const odd = describeError(400, { error: "points.0: Value error, coordinates must be numbers" }, null).message;
  assert.match(odd, /coordinates must be numbers/);
  assert.doesNotMatch(odd, /Value error|points.0/);
});

test("a 409 is a long-ride question only when the API says so", () => {
  const asked = describeError(409, { error: "long", code: "confirm_long", span_km: 161.6 }, null);
  assert.equal(asked.kind, "confirm-long");
  assert.equal(asked.spanKm, 162);
  assert.match(asked.message, /162 km/);
  assert.notEqual(describeError(409, { error: "conflict" }, null).kind, "confirm-long");
  assert.equal(describeError(409, { code: "confirm_long", span_km: "far" }, null).spanKm, undefined);
});

test("a proxy's error page is not shown as if it were the API's words", () => {
  const html = "<html><body>502 Bad Gateway</body></html>";
  assert.ok(!describeError(502, html, null).message.includes("<html>"));
  assert.ok(!describeError(422, { error: 42 }, null).message.includes("42"));
});

test("Retry-After is carried on rate-limit and time-out errors", () => {
  assert.equal(describeError(429, null, "56").retryAfterS, 56);
  assert.equal(describeError(503, null, "30").retryAfterS, 30);
  assert.ok(describeError(429, null, "56").message.includes("56"));
  assert.equal(describeError(429, null, null).retryAfterS, undefined);
});

test("Retry-After parses seconds and HTTP dates and refuses nonsense", () => {
  const now = Date.parse("2026-09-26T12:00:00Z");
  assert.equal(parseRetryAfter("12", now), 12);
  assert.equal(parseRetryAfter("Sat, 26 Sep 2026 12:00:30 GMT", now), 30);
  assert.equal(parseRetryAfter("Sat, 26 Sep 2026 11:59:00 GMT", now), 0);
  assert.equal(parseRetryAfter("soon", now), undefined);
  assert.equal(parseRetryAfter("-5", now), undefined);
  assert.equal(parseRetryAfter(null, now), undefined);
});

function fakeFetch(status: number, body: string, headers: Record<string, string> = {}) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const impl = async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(body, { status, headers });
  };
  return { impl, calls };
}

test("a route request posts the contract's body as JSON", async () => {
  const route = {
    preset: "mass-ride",
    variant: "no-trail",
    geometry: { type: "LineString", coordinates: [[-77.04, 38.91], [-77.01, 38.89]] },
    distance_m: 4660,
    duration_s: 1836,
    climb_m: 12,
    descent_m: 20,
    stress_m: { "1": 1, "2": 2, "3": 3, "4": 4, unknown: 0 },
    attribution: ["© OpenStreetMap contributors, ODbL"],
  };
  const { impl, calls } = fakeFetch(200, JSON.stringify(route), {
    "Content-Type": "application/json",
  });
  const points: Array<[number, number]> = [[-77.04, 38.91], [-77.01, 38.89]];
  const result = await requestRoute(points, "mass-ride", { fetchImpl: impl });
  assert.equal(result.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/route");
  assert.equal(calls[0].init.method, "POST");
  const headers = new Headers(calls[0].init.headers);
  assert.equal(headers.get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { points, preset: "mass-ride" });
  if (result.ok) assert.equal(result.route.distance_m, 4660);
});

test("confirm_long is sent only when the rider confirmed, and the rest of the body is unchanged", async () => {
  // The whole body on both branches: a confirmed Mass Ride that lost its
  // preset would be planned on the API's default.
  const bodies: unknown[] = [];
  const impl = async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    return new Response("{}", { status: 500 });
  };
  const points: Array<[number, number]> = [[-77.95, 38.25], [-76.6, 39.3]];
  await requestRoute(points, "mass-ride", { fetchImpl: impl });
  await requestRoute(points, "mass-ride", { fetchImpl: impl, confirmLong: true });
  await requestRoute(points, "group-ride", { fetchImpl: impl, confirmLong: false });
  assert.deepEqual(bodies, [
    { points, preset: "mass-ride" },
    { points, preset: "mass-ride", confirm_long: true },
    { points, preset: "group-ride" },
  ]);
});

test("an error sentence of only whitespace is not shown as the API's words", () => {
  for (const status of [404, 422]) {
    const message = describeError(status, { error: "   \n" }, null).message;
    assert.ok(message.trim().length > 0, `status ${status} showed an empty message`);
  }
  // A real sentence is shown trimmed.
  assert.equal(describeError(404, { error: "  No way across.  " }, null).message, "No way across.");
});

test("every input refusal the validator can give is said in words, never empty", () => {
  // Point counts outside 2-25 are refused by the API's validator; the app
  // never sends one, but a link edited by hand can.
  const tooFew = describeError(400, { error: "points: List should have at least 2 items after validation, not 1" }, null);
  const tooMany = describeError(400, { error: "points: List should have at most 25 items after validation, not 26" }, null);
  assert.notEqual(tooFew.message, tooMany.message);
  for (const described of [tooFew, tooMany]) {
    assert.equal(described.kind, "bad-input");
    assert.doesNotMatch(described.message, /List should|items after validation|points:/);
  }
  // Several reasons joined by ";": the first is said, not the pile.
  const several = describeError(400, { error: "preset: Input should be 'default'; points: Field required" }, null).message;
  assert.match(several, /Input should be 'default'/);
  assert.doesNotMatch(several, /Field required|;/);
  // A reason that is nothing once the field path is stripped falls back to
  // the plain sentence, with no dangling colon.
  const bare = describeError(400, { error: "points: " }, null).message;
  assert.equal(bare, describeError(400, null, null).message);
});

test("a 200 missing what the panel reads is refused, not rendered", async () => {
  const good = {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] },
    distance_m: 1,
    duration_s: 1,
    climb_m: 0,
    descent_m: 0,
    stress_m: { "1": 1 },
    attribution: [],
  };
  const broken = [
    { ...good, attribution: undefined },
    { ...good, geometry: { type: "Point", coordinates: [0, 0] } },
    { ...good, geometry: { type: "LineString" } },
    { ...good, stress_m: null },
    { ...good, distance_m: "5" },
    { ...good, duration_s: undefined },
  ];
  const { impl: goodImpl } = fakeFetch(200, JSON.stringify(good));
  assert.equal((await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: goodImpl })).ok, true);
  for (const body of broken) {
    const { impl } = fakeFetch(200, JSON.stringify(body));
    const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
    assert.equal(result.ok, false, JSON.stringify(body));
  }
});

test("a refusal comes back described, with its Retry-After", async () => {
  const { impl } = fakeFetch(429, JSON.stringify({ error: "slow down" }), { "Retry-After": "7" });
  const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.kind, "rate-limited");
    assert.equal(result.error.retryAfterS, 7);
  }
});

test("a body that is not JSON still maps by status", async () => {
  const { impl } = fakeFetch(502, "Bad Gateway");
  const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, "router-down");
});

test("a 200 that is not a route is an error, not a crash", async () => {
  const { impl } = fakeFetch(200, JSON.stringify({ hello: "world" }));
  const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
  assert.equal(result.ok, false);
});

test("a network failure is its own kind", async () => {
  const impl = async () => {
    throw new TypeError("Failed to fetch");
  };
  const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, "network");
});
