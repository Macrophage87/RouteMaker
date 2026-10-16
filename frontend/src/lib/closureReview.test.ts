// Reviewer-confirmed closures and saved-route alerts (v0.7.0 closures; lib/closureReview.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alertLine,
  closureProblem,
  closureStretchPath,
  confirmReport,
  endClosure,
  enterClosure,
  fetchClosureReview,
  regionToday,
  type ClosureAlert,
} from "./closureReview.ts";

const alert = (text: string): ClosureAlert => ({ id: "reviewer-1-0", title: "Oak Street: closed", road: "Oak Street", end: null, source: "Confirmed by a RouteMaker reviewer", text });

test("My routes says the first closure on a route, and how many more, in one line", () => {
  assert.equal(alertLine(undefined), "");
  assert.equal(alertLine([]), "");
  assert.equal(alertLine([alert("Closed on your route: Oak Street, until Oct 20, 2026.")]), "Closed on your route: Oak Street, until Oct 20, 2026.");
  assert.equal(alertLine([alert("Closed on your route: Oak Street, no end date given."), alert("x"), alert("y")]), "Closed on your route: Oak Street, no end date given. And 2 more closures.");
  assert.equal(alertLine([alert("A."), alert("B.")]), "A. And 1 more closure.");
});

test("the form names the field that is wrong before it sends", () => {
  assert.equal(closureProblem("  ", "", "", "")?.field, "reason");
  assert.equal(closureProblem("x".repeat(501), "", "", "")?.field, "reason");
  assert.equal(closureProblem("Bridge works", "2026-10-20", "2026-10-19", "")?.field, "end");
  assert.equal(closureProblem("Bridge works", "2026-10-20", "", "example.org")?.field, "url");
  assert.equal(closureProblem("Bridge works", "2026-10-20", "2026-10-20", "https://example.org/notice"), null);
  assert.equal(closureProblem("Bridge works", "", "", ""), null);
});

test("today is the region's day, not the device's", () => {
  // 02:00 UTC on Oct 17 is still Oct 16 in Washington.
  assert.equal(regionToday(new Date("2026-10-17T02:00:00Z")), "2026-10-16");
  assert.equal(regionToday(new Date("2026-10-17T12:00:00Z")), "2026-10-17");
});

test("the requests carry the security token and say a refusal plainly", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const reply = (status: number, body: unknown) =>
    (async (url: string, init: RequestInit) => {
      seen.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    }) as unknown as typeof fetch;
  const body = { reason: "Bridge works", start: "2026-10-20", end: null, url: "" };
  const done = await enterClosure("https://x.test", [5001, 5002], body, reply(201, { id: 7, message: "Closure confirmed: Oak Street." }), "csrftoken=abc");
  assert.deepEqual(done, { kind: "done", id: 7, message: "Closure confirmed: Oak Street." });
  assert.equal(seen[0].url, "https://x.test/api/closures/reviewed");
  assert.equal((seen[0].init.headers as Record<string, string>)["X-CSRFToken"], "abc");
  assert.deepEqual(JSON.parse(String(seen[0].init.body)), { osm_way_ids: [5001, 5002], ...body });

  const refused = await confirmReport("https://x.test", 3, body, reply(400, { error: "The last day is before the first.", field: "end" }), "");
  assert.deepEqual(refused, { kind: "refused", message: "The last day is before the first.", field: "end" });
  assert.equal(seen[1].url, "https://x.test/api/closures/reports/3/confirm");
  await endClosure("https://x.test", 9, reply(200, { id: 9, message: "Ended." }), "");
  assert.equal(seen[2].url, "https://x.test/api/closures/reviewed/9/end");
  assert.equal(closureStretchPath(5001), "/api/closures/stretch/5001");
});

test("the review list, or a sentence where it could not be read", async () => {
  const list = await fetchClosureReview("https://x.test", (async () => new Response(JSON.stringify({ closures: [], reports: [] }), { status: 200 })) as unknown as typeof fetch);
  assert.deepEqual(list, { closures: [], reports: [] });
  const failed = await fetchClosureReview("https://x.test", (async () => new Response("{}", { status: 403 })) as unknown as typeof fetch);
  assert.equal(failed, "The closures could not be read; try again shortly.");
});
