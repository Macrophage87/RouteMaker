/** The AI assistant key's words and requests (lib/assistantKey.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { KEY_NONE, keySummary, makeKey, readKey, removeKey } from "./assistantKey.ts";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

test("the key's line names its last characters and when it was used, or None", () => {
  assert.equal(keySummary(null), KEY_NONE);
  assert.equal(keySummary({ hint: "ab_c", created_at: "2026-10-18T13:00:00Z", last_used_at: null }), "Ends …ab_c, not used yet");
  assert.match(keySummary({ hint: "ab_c", created_at: "2026-10-18T13:00:00Z", last_used_at: "2026-10-18T15:00:00Z" }), /^Ends …ab_c, last used Oct 18$/);
});

test("reading, making and removing send the session's requests with the CSRF token", async () => {
  const sent: [string, RequestInit | undefined][] = [];
  const fake = ((url: string, init?: RequestInit) => {
    sent.push([url, init]);
    if (url.endsWith("/delete")) return ok({ key: null });
    if (init?.method === "POST") return ok({ key: { hint: "wxyz", created_at: "x", last_used_at: null }, secret: "rmk_secretwxyz" }, 201);
    return ok({ key: null });
  }) as typeof fetch;
  assert.equal(await readKey("https://x", fake), null);
  const made = await makeKey("https://x", fake, "csrftoken=tok");
  assert.equal(made?.secret, "rmk_secretwxyz");
  assert.equal(await removeKey("https://x", fake, "csrftoken=tok"), true);
  assert.deepEqual(
    sent.map(([url]) => url),
    ["https://x/api/me/assistant-key", "https://x/api/me/assistant-key", "https://x/api/me/assistant-key/delete"],
  );
  assert.equal((sent[1][1]?.headers as Record<string, string>)["X-CSRFToken"], "tok");
  assert.equal(sent[1][1]?.credentials, "same-origin");
});

test("a refusal or a network failure is no key and no change", async () => {
  const refused = (() => ok({ error: "no" }, 403)) as typeof fetch;
  const broken = (() => Promise.reject(new Error("offline"))) as typeof fetch;
  assert.equal(await readKey("https://x", refused), undefined);
  assert.equal(await makeKey("https://x", broken), null);
  assert.equal(await removeKey("https://x", refused), false);
});
