import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchServerStatus, parseServerStatus, serverStatusLine } from "./serverStatus.ts";

test("only a status file the server wrote makes a line", () => {
  assert.deepEqual(parseServerStatus('{"state": "updating"}'), { state: "updating" });
  assert.deepEqual(parseServerStatus('{"state": "degraded", "parts": ["search", "trails", "weather"]}'), {
    state: "degraded",
    parts: ["trails", "search"],
  });
  for (const text of ["<!doctype html><div id=root>", "", "null", '{"state": "fine"}', '{"state": "degraded", "parts": []}']) {
    assert.equal(parseServerStatus(text), null, text);
  }
});

test("one short line, routing before trails, search added", () => {
  assert.equal(serverStatusLine(null), null);
  assert.equal(serverStatusLine({ state: "updating" }), "Updating. Back in a few minutes.");
  assert.equal(serverStatusLine({ state: "degraded", parts: ["trails"] }), "Some ride types are not working right now.");
  assert.equal(
    serverStatusLine({ state: "degraded", parts: ["routing", "trails", "search"] }),
    "Route planning is down right now. Place search is down right now.",
  );
});

test("a 404, a network error or a page is no status", async () => {
  const answer = (status: number, body: string) => (async () => new Response(body, { status })) as typeof fetch;
  assert.equal(await fetchServerStatus("https://x", answer(404, "Not found")), null);
  assert.equal(await fetchServerStatus("https://x", answer(200, "<html>")), null);
  assert.deepEqual(await fetchServerStatus("https://x", answer(200, '{"state":"updating"}')), { state: "updating" });
  const offline = (async () => {
    throw new TypeError("Failed to fetch");
  }) as typeof fetch;
  assert.equal(await fetchServerStatus("https://x", offline), null);
  let asked = "";
  let init: RequestInit | undefined;
  await fetchServerStatus("https://x", (async (url: string, options?: RequestInit) => {
    asked = url;
    init = options;
    return new Response("", { status: 404 });
  }) as typeof fetch);
  assert.equal(asked, "https://x/status.json");
  assert.equal(init?.cache, "no-store");
});
