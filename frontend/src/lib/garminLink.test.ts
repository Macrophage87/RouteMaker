/** The Garmin connection's words and requests (lib/garminLink.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { AS_FILE, CONNECTION_ENDED, COURSE_ADDED, COURSE_FAILED_FILE, COURSE_UPDATED, GARMIN_NOT_CONNECTED, RETURNED, disconnectGarmin, garminReturnFrom, garminSummary, readGarmin, sendDirect, withoutReturn } from "./garminLink.ts";

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

test("a course sent through the connection says added or updated, or why it went as a file", async () => {
  const course = { name: "Loop", preset: "default", line: [[-77, 38.9, 10] as const, [-77, 38.91] as const], saved_route: 7 };
  const sent: RequestInit[] = [];
  const answer = (body: unknown, status = 200) =>
    ((_url: string, init?: RequestInit) => {
      if (init) sent.push(init);
      return ok(body, status);
    }) as typeof fetch;
  assert.deepEqual(await sendDirect("https://x", course, answer({ sent: "added" }), "csrftoken=tok"), { said: COURSE_ADDED });
  assert.deepEqual(JSON.parse(String(sent[0].body)), { ...course, line: [[-77, 38.9, 10], [-77, 38.91]] });
  assert.equal((sent[0].headers as Record<string, string>)["X-CSRFToken"], "tok");
  assert.deepEqual(await sendDirect("https://x", course, answer({ sent: "updated" })), { said: COURSE_UPDATED });
  assert.deepEqual(await sendDirect("https://x", course, answer({ error: "Gone", code: "not_connected" }, 409)), { asFile: CONNECTION_ENDED });
  assert.deepEqual(await sendDirect("https://x", course, answer({ error: "Garmin is busy." }, 502)), { asFile: `Garmin is busy. ${AS_FILE}` });
  assert.deepEqual(await sendDirect("https://x", course, answer({ error: "Too many points." }, 400)), { asFile: `Too many points. ${AS_FILE}` });
  assert.deepEqual(await sendDirect("https://x", course, answer({ error: "CSRF" }, 403)), { asFile: COURSE_FAILED_FILE });
  assert.deepEqual(await sendDirect("https://x", course, answer({}, 500)), { asFile: COURSE_FAILED_FILE });
  const offline = (() => Promise.reject(new TypeError("offline"))) as typeof fetch;
  assert.deepEqual(await sendDirect("https://x", course, offline), { asFile: COURSE_FAILED_FILE });
});
