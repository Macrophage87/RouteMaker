import { test } from "node:test";
import assert from "node:assert/strict";
import { daysLeft, deleteDraft, draftLeft, saveDraft } from "./drafts.ts";

test("a draft says how long it has left in whole days", () => {
  const now = Date.parse("2026-11-09T12:00:00Z");
  assert.equal(daysLeft("2026-11-16T12:00:00Z", now), 7);
  assert.equal(daysLeft("2026-11-16T11:00:00Z", now), 7);
  assert.equal(daysLeft("2026-11-09T13:00:00Z", now), 1);
  assert.equal(daysLeft("2026-11-08T13:00:00Z", now), 0);
  assert.equal(draftLeft("2026-11-15T11:00:00Z", now), "Draft, 6 days left");
  assert.equal(draftLeft("2026-11-10T12:00:00Z", now), "Draft, last day");
  assert.equal(draftLeft("2026-11-09T13:00:00Z", now), "Draft, last day");
});

test("Save keeps the draft exactly as drafted and names it, so it is no longer listed", async () => {
  const id = "b".repeat(32);
  const shared = { id, name: "Sandwich loop", source: "plan", distance_m: 8047, line: [[-77, 38.9], [-77.01, 38.91]], inputs: { hash: "#p=x", points: [], preset: "default", dials: {} }, answer: null, gpx: "", draft_until: "2026-11-15T12:00:00Z" };
  let sent: unknown = null;
  const get = (async () => new Response(JSON.stringify(shared), { status: 200 })) as typeof fetch;
  const post = (async (_url: string, init: RequestInit) => {
    sent = JSON.parse(String(init.body));
    return new Response(JSON.stringify({ id: 3, name: "Sandwich loop" }), { status: 201 });
  }) as typeof fetch;
  const outcome = await saveDraft("https://x", id, get, post);
  assert.ok(outcome?.ok);
  assert.deepEqual(sent, { name: "Sandwich loop", source: "plan", line: shared.line, distance_m: 8047, inputs: shared.inputs, answer: null, from_draft: id });
  const gone = (async () => new Response("{}", { status: 404 })) as typeof fetch;
  assert.equal(await saveDraft("https://x", id, gone, post), null);
});

test("Delete removes the draft on the server; one already gone counts as deleted", async () => {
  const id = "c".repeat(32);
  let asked = "";
  const send = (async (url: string, init: RequestInit) => {
    asked = `${init.method} ${url}`;
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  assert.equal(await deleteDraft("https://x", id, send, "csrftoken=t"), true);
  assert.equal(asked, `DELETE https://x/api/me/drafts/${id}`);
  assert.equal(await deleteDraft("https://x", id, (async () => new Response("{}", { status: 404 })) as typeof fetch, ""), true);
  assert.equal(await deleteDraft("https://x", id, (async () => new Response("{}", { status: 500 })) as typeof fetch, ""), false);
});
