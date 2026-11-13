// Anonymous daily usage totals: what Start sends (lib/usage.ts, core.usage).
import { test } from "node:test";
import assert from "node:assert/strict";
import { countUse } from "./usage.ts";

test("a ride started sends its kind and nothing else", () => {
  const calls: [string, RequestInit][] = [];
  const send = ((url: string, init: RequestInit) => {
    calls.push([url, init]);
    return Promise.resolve(new Response(null, { status: 204 }));
  }) as unknown as typeof fetch;
  countUse("https://example.test", "walk", send);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "https://example.test/api/usage");
  assert.deepEqual(JSON.parse(String(calls[0][1].body)), { tool: "walk" });
});

test("a count that cannot be sent never stops the ride", () => {
  const rejecting = (() => Promise.reject(new Error("offline"))) as unknown as typeof fetch;
  assert.doesNotThrow(() => countUse("https://example.test", "ride", rejecting));
  const throwing = (() => {
    throw new Error("no fetch");
  }) as unknown as typeof fetch;
  assert.doesNotThrow(() => countUse("https://example.test", "run", throwing));
});
