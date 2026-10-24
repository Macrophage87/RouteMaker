/** The Wahoo connection's words and requests (lib/wahooLink.ts). */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { withoutReturn } from "./garminLink.ts";
import type { CapacitorBridge } from "./nativeShell.ts";
import { FILES_PLUGIN } from "./sendToGarmin.ts";
import {
  AS_FILE,
  AS_FILE_CHOOSER,
  AS_FILE_FAILED,
  AS_FILE_GARMIN,
  AS_FILE_NONE,
  CONNECTION_ENDED,
  RETURNED,
  ROUTE_ADDED,
  ROUTE_UPDATED,
  RETURN_PARAM,
  UNREACHED,
  disconnectWahoo,
  handWahooFile,
  readWahoo,
  sendToWahoo,
  wahooReturnFrom,
} from "./wahooLink.ts";

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

test("the file instead: saved in a browser, handed to the phone app's Open with list (never Garmin Connect)", async () => {
  const bytes = new Uint8Array([14, 16, 0x6c, 0x08]);
  const saved: string[] = [];
  const save = (_b: Uint8Array<ArrayBuffer>, type: string, name: string) => void saved.push(`${type} ${name}`);
  assert.equal(await handWahooFile(bytes, "r.fit", { bridge: null, save }), AS_FILE);
  assert.deepEqual(saved, ["application/vnd.ant.fit r.fit"]);
  const calls: unknown[][] = [];
  const shell = (available: boolean, answer: () => Promise<unknown>): CapacitorBridge => ({
    isNativePlatform: () => true,
    isPluginAvailable: (name) => available && name === FILES_PLUGIN,
    nativePromise: (plugin, method, options) => {
      calls.push([plugin, method, options]);
      return answer();
    },
    nativeCallback: () => "",
  });
  assert.equal(await handWahooFile(bytes, "r.fit", { bridge: shell(true, async () => ({ app: "chooser" })), save }), AS_FILE_CHOOSER);
  assert.deepEqual(calls[0], [FILES_PLUGIN, "openWith", { name: "r.fit", data: "DhBsCA==", anyApp: true }]);
  // An app from before anyApp sent it to Garmin Connect: said, not claimed as the Wahoo app's.
  assert.equal(await handWahooFile(bytes, "r.fit", { bridge: shell(true, async () => ({ app: "garmin-connect" })), save }), AS_FILE_GARMIN);
  assert.equal(await handWahooFile(bytes, "r.fit", { bridge: shell(true, () => Promise.reject(new Error("no"))), save }), AS_FILE_FAILED);
  assert.equal(await handWahooFile(bytes, "r.fit", { bridge: shell(false, async () => ({})), save }), AS_FILE_NONE);
  assert.equal(saved.length, 1, "the phone app never downloads (a WebView saves nothing)");
  assert.doesNotMatch(AS_FILE_CHOOSER + AS_FILE_FAILED, /saved/);
  const panel = readFileSync(new URL("../GpxPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const asFile = await handWahooFile\(bytes, courseFileName\(route, "fit"\), browserSendEnv\(/);
  const plugin = readFileSync(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/FilesPlugin.java", import.meta.url), "utf8");
  assert.match(plugin, /for \(Intent candidate : anyApp \? new Intent\[0\] : /);
});
