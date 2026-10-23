/** The Garmin connection's words and requests (lib/garminLink.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { GARMIN_NOT_CONNECTED, RETURNED, disconnectGarmin, garminReturnFrom, garminSummary, readGarmin, withoutReturn } from "./garminLink.ts";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

test("Garmin's return is read once and only for outcomes the page knows", () => {
  assert.equal(garminReturnFrom("?garmin=connected"), RETURNED.connected);
  assert.equal(garminReturnFrom("?x=1&garmin=declined"), RETURNED.declined);
  assert.equal(garminReturnFrom("?garmin=toString"), null);
  assert.equal(garminReturnFrom("?garmin=<b>"), null);
  assert.equal(garminReturnFrom(""), null);
  assert.equal(withoutReturn("?garmin=connected"), "");
  assert.equal(withoutReturn("?x=1&garmin=failed"), "?x=1");
});

test("the fold's line says whether Garmin is connected", () => {
  assert.equal(garminSummary(undefined), "…");
  assert.equal(garminSummary({ available: true, connected: false, connected_at: null, last_used_at: null }), GARMIN_NOT_CONNECTED);
  assert.equal(garminSummary({ available: true, connected: true, connected_at: "2026-10-23T15:00:00Z", last_used_at: null }), "Connected since Oct 23");
});

test("reading and disconnecting send the session's requests with the CSRF token", async () => {
  const sent: [string, RequestInit | undefined][] = [];
  const fake = ((url: string, init?: RequestInit) => {
    sent.push([url, init]);
    return ok({ available: true, connected: !url.endsWith("/delete"), connected_at: null, last_used_at: null });
  }) as typeof fetch;
  assert.equal((await readGarmin("https://x", fake))?.connected, true);
  assert.equal((await disconnectGarmin("https://x", fake, "csrftoken=tok"))?.connected, false);
  assert.deepEqual(
    sent.map(([url]) => url),
    ["https://x/api/me/garmin", "https://x/api/me/garmin/delete"],
  );
  assert.equal((sent[1][1]?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  const failing = (() => ok({}, 500)) as typeof fetch;
  assert.equal(await readGarmin("https://x", failing), undefined);
  assert.equal(await disconnectGarmin("https://x", failing), null);
});
