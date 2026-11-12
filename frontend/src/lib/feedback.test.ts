import { test } from "node:test";
import assert from "node:assert/strict";
import { feedbackDetails, feedbackOn, sendFeedback, shortBrowser } from "./feedback.ts";

test("a short browser name, never the whole user-agent string", () => {
  const android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.81 Mobile Safari/537.36";
  assert.equal(shortBrowser(android), "Chrome 131 on Android");
  const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";
  assert.equal(shortBrowser(iphone), "Safari 18 on iPhone");
  const edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.70";
  assert.equal(shortBrowser(edge), "Edge 131 on Windows");
  const firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0";
  assert.equal(shortBrowser(firefox), "Firefox 133 on Linux");
  assert.equal(shortBrowser("curl/8"), "a browser on another system");
});

test("the details carry no place and no full user agent", () => {
  const details = feedbackDetails({ userAgent: "Mozilla/5.0 (Linux; Android 14) Chrome/131.0 Mobile", rideType: "commute", language: "es", mode: "go", nativeApp: true });
  assert.deepEqual(Object.keys(details).sort(), ["app", "browser", "language", "mode", "ride_type"].sort());
  assert.equal(details.app, "Android app");
  assert.doesNotMatch(JSON.stringify(details), /Mozilla|-?\d+\.\d{3,}/);
});

test("the entry shows only where the server says it takes feedback", async () => {
  const answer = (status: number, body: string) => (async () => new Response(body, { status })) as typeof fetch;
  assert.equal(await feedbackOn("https://x", answer(200, '{"enabled": true}')), true);
  assert.equal(await feedbackOn("https://x", answer(200, '{"enabled": false}')), false);
  assert.equal(await feedbackOn("https://x", answer(404, "")), false);
  assert.equal(await feedbackOn("https://x", answer(200, "<html>")), false);
});

test("send: the trimmed words and the details, and what came of it", async () => {
  let sent: { url: string; init?: RequestInit } | null = null;
  const ok = (async (url: string, init?: RequestInit) => {
    sent = { url, init };
    return new Response('{"sent": true}', { status: 200 });
  }) as typeof fetch;
  assert.equal(await sendFeedback("https://x", "  the button did nothing  ", { mode: "go" }, ok), "sent");
  assert.equal(sent!.url, "https://x/api/feedback");
  assert.deepEqual(JSON.parse(String(sent!.init?.body)), { text: "the button did nothing", details: { mode: "go" } });
  const status = (code: number) => (async () => new Response("", { status: code })) as typeof fetch;
  assert.equal(await sendFeedback("https://x", "hello", {}, status(429)), "busy");
  assert.equal(await sendFeedback("https://x", "hello", {}, status(502)), "failed");
  const offline = (async () => {
    throw new TypeError("Failed to fetch");
  }) as typeof fetch;
  assert.equal(await sendFeedback("https://x", "hello", {}, offline), "failed");
});
