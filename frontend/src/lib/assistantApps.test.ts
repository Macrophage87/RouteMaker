/** Settings' AI assistants: the connected apps' words and requests (lib/assistantApps.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { APPS_NONE, DOCS_LINK, appSummary, assistantsSummary, disconnectApp, readApps } from "./assistantApps.ts";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

test("the fold names how many apps are connected, and each app its own line", () => {
  const app = { id: 3, name: "Claude", created_at: "2026-10-19T13:00:00Z", last_used_at: null };
  assert.equal(assistantsSummary([]), APPS_NONE);
  assert.equal(assistantsSummary([app]), "1 app connected");
  assert.equal(assistantsSummary([app, { ...app, id: 4 }]), "2 apps connected");
  assert.equal(appSummary(app), "Claude, connected Oct 19, not used yet");
});

test("how to connect one is the assistants page", () => {
  assert.equal(DOCS_LINK, "/about/assistants.html");
});

test("apps are read and disconnected with the session's requests", async () => {
  const sent: [string, RequestInit | undefined][] = [];
  const fake = ((url: string, init?: RequestInit) => {
    sent.push([url, init]);
    return ok({ apps: [] });
  }) as typeof fetch;
  assert.deepEqual(await readApps("https://x", fake), []);
  assert.deepEqual(await disconnectApp("https://x", 3, fake, "csrftoken=tok"), []);
  assert.deepEqual(
    sent.map(([url]) => url),
    ["https://x/api/me/connected-apps", "https://x/api/me/connected-apps/3/delete"],
  );
  assert.equal((sent[1][1]?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  const refused = (() => ok({ error: "no" }, 403)) as typeof fetch;
  const broken = (() => Promise.reject(new Error("offline"))) as typeof fetch;
  assert.equal(await disconnectApp("https://x", 3, refused), null);
  assert.equal(await readApps("https://x", broken), undefined);
});
