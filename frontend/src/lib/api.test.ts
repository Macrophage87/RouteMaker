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
  ];
  for (const [status, body, kind] of cases) {
    assert.equal(describeError(status, body, null).kind, kind, `status ${status}`);
  }
  const kinds = new Set(cases.map(([s, b]) => describeError(s, b, null).kind));
  assert.equal(kinds.size, 7);
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

test("the server's own explanation reaches the rider for input and no-route errors", () => {
  const detail = "Mass Ride routes only on roadways, and removing trails can leave no connection.";
  assert.ok(describeError(422, { error: detail }, null).message.includes(detail));
  const input = "point 1 is outside the area this map covers";
  assert.ok(describeError(400, { error: input }, null).message.includes(input));
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

test("an aborted request is reported as aborted, so the caller can drop it", async () => {
  const impl = async () => {
    throw new DOMException("The operation was aborted.", "AbortError");
  };
  const result = await requestRoute([[0, 0], [1, 1]], "default", { fetchImpl: impl });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.error.kind, "aborted");
});
