/** The Wahoo connection's words and requests (lib/wahooLink.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { withoutReturn } from "./garminLink.ts";
import { CONNECTION_ENDED, RETURNED, ROUTE_ADDED, ROUTE_UPDATED, RETURN_PARAM, UNREACHED, disconnectWahoo, readWahoo, sendToWahoo, wahooReturnFrom } from "./wahooLink.ts";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
const ROUTE = { name: "Loop", line: [[-77, 38.9, 10] as const, [-77, 38.91] as const], fit: "Dg==", saved_route: 4 };

test("Wahoo's return is read once and only for outcomes the page knows", () => {
  assert.equal(wahooReturnFrom("?wahoo=connected"), RETURNED.connected);
  assert.equal(wahooReturnFrom("?x=1&wahoo=declined"), RETURNED.declined);
  assert.equal(wahooReturnFrom("?wahoo=toString"), null);
  assert.equal(wahooReturnFrom("?garmin=connected"), null);
  assert.equal(withoutReturn("?x=1&wahoo=failed", RETURN_PARAM), "?x=1");
  assert.equal(withoutReturn("?garmin=connected&wahoo=failed", RETURN_PARAM), "?garmin=connected");
});

test("reading and disconnecting send the session's requests with the CSRF token", async () => {
  const sent: [string, RequestInit | undefined][] = [];
  const fake = ((url: string, init?: RequestInit) => {
    sent.push([url, init]);
    return ok({ available: true, connected: !url.endsWith("/delete"), connected_at: null, last_used_at: null });
  }) as typeof fetch;
  assert.equal((await readWahoo("https://x", fake))?.connected, true);
  assert.equal((await disconnectWahoo("https://x", fake, "csrftoken=tok"))?.connected, false);
  assert.deepEqual(sent.map(([url]) => url), ["https://x/api/me/wahoo", "https://x/api/me/wahoo/delete"]);
  assert.equal((sent[1][1]?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  const failing = (() => ok({}, 500)) as typeof fetch;
  assert.equal(await readWahoo("https://x", failing), undefined);
  assert.equal(await disconnectWahoo("https://x", failing), null);
});

test("sending says what Wahoo did, or why the file goes instead", async () => {
  let body: unknown;
  const answer = (reply: unknown, status = 200) =>
    ((_url: string, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return ok(reply, status);
    }) as typeof fetch;
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, answer({ sent: "added" })), { said: ROUTE_ADDED });
  assert.deepEqual(body, ROUTE);
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, answer({ sent: "updated" })), { said: ROUTE_UPDATED });
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, answer({ error: "x", code: "not_connected" }, 409)), { asFile: CONNECTION_ENDED });
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, answer({ error: "Wahoo is taking too many routes just now." }, 502)), { asFile: "Wahoo is taking too many routes just now." });
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, answer({}, 500)), { asFile: UNREACHED });
  const down = (() => Promise.reject(new TypeError("offline"))) as typeof fetch;
  assert.deepEqual(await sendToWahoo("https://x", ROUTE, down), { asFile: UNREACHED });
});
