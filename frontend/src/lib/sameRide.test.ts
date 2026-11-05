// "Same ride or a new one?" (SameRideDialog; lib/rideGroup.ts asksSameRide): a Group or Mass Ride plan's link that
// went out more than 12 hours ago is asked about before it goes out again or its ride starts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as rideGroup from "./rideGroup.ts";
import { newRideSecret } from "./rideSeal.ts";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const HOUR = 3600_000;

function memoryStore() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), kept };
}

test("a Group Ride plan's link copied again a day later asks whether it is the same ride; within 12 hours it does not", () => {
  const { asksSameRide, markRideSent, SAME_RIDE_ASK_MS } = rideGroup;
  assert.equal(SAME_RIDE_ASK_MS, 12 * HOUR);
  const store = memoryStore();
  const secret = newRideSecret();
  const monday = Date.UTC(2026, 10, 2, 18);
  // Never sent: nothing to ask.
  assert.equal(asksSameRide(secret, monday, store), false);
  markRideSent(secret, monday, false, store);
  assert.equal(asksSameRide(secret, monday + 11 * HOUR, store), false);
  // Copied again the same evening keeps Monday's time: it is when the link first went out.
  markRideSent(secret, monday + 2 * HOUR, false, store);
  assert.equal(asksSameRide(secret, monday + 13 * HOUR, store), true);
  assert.equal(asksSameRide(secret, monday + 7 * 24 * HOUR, store), true);
  // Another secret (a new ride) is not asked about.
  assert.equal(asksSameRide(newRideSecret(), monday + 7 * 24 * HOUR, store), false);
});

test("the organiser saying Same ride is not asked again for 12 hours; only a digest and a time are kept", () => {
  const { asksSameRide, markRideSent, RIDE_SENT_KEY } = rideGroup;
  const store = memoryStore();
  const secret = newRideSecret();
  const monday = Date.UTC(2026, 10, 2, 18);
  markRideSent(secret, monday, false, store);
  const thursday = monday + 3 * 24 * HOUR;
  markRideSent(secret, thursday, true, store);
  assert.equal(asksSameRide(secret, thursday + HOUR, store), false);
  assert.equal(asksSameRide(secret, thursday + 13 * HOUR, store), true);
  const kept = store.kept.get(RIDE_SENT_KEY)!;
  assert.ok(!kept.includes(secret));
  assert.deepEqual(Object.values(JSON.parse(kept)), [thursday]);
  // No storage (a private window): never asked.
  markRideSent(secret, monday, false, null);
  assert.equal(asksSameRide(secret, thursday, null), false);
});

test("Copy link, Share and Start ride on a Group or Mass Ride plan ask first; New ride makes a new key, going back sends nothing", () => {
  const app = source("../App.tsx");
  assert.match(
    app,
    /const sameRideFirst = \(go: \(secret: string\) => void\) => \{\s*if \(!riding && isRideLink\(preset, points\) && groupSecretOwn\.current && asksSameRide\(groupSecret, Date\.now\(\)\)\) setSameRideAsk\(\{ then: go \}\);\s*else go\(groupSecret\);\s*\};/,
  );
  assert.match(app, /const copyLink = \(\) => sameRideFirst\(\(secret\) => void copyLinkWith\(secret\)\);/);
  assert.match(app, /shareRoute=\{\(ride\) => \(ride \? void shareRoute\(true\) : sameRideFirst\(\(secret\) => void shareRoute\(false, shareNav, secret\)\)\)\}/);
  assert.match(app, /const startRideChecked = \(\) => sameRideFirst\(\(\) => startRideNoted\(""\)\);/);
  // The link carries the key chosen, and when it went out is kept.
  assert.match(app, /const \{ link, kept \} = sharedLinkNow\(secret\);\s*const done = await copyText\(link, navigator\.clipboard, selectionCopy\);\s*if \(done\) planLinkSent\(secret\);/);
  assert.match(app, /isRideLinkType\(from\.preset\) \? secret : null\);/);
  assert.match(app, /if \(!ride && done === "shared"\) planLinkSent\(secret\);/);
  // New ride: no plan keeps the old key.
  assert.match(app, /const fresh = ownSecrets\.current!\.renew\(groupSecret\);\s*setGroupSecret\(fresh\);\s*ask\.then\(fresh\);/);
  assert.match(app, /markRideSent\(groupSecret, Date\.now\(\), true\);\s*return ask\.then\(groupSecret\);/);
  assert.match(app, /<SameRideDialog open=\{sameRideAsk !== null\} onSame=\{\(\) => answerSameRide\(true\)\} onNew=\{\(\) => answerSameRide\(false\)\} onCancel=\{\(\) => setSameRideAsk\(null\)\} \/>/);
});

test("the question is a modal dialog named by its heading: New ride takes the focus, Escape goes back", () => {
  const dialog = source("../SameRideDialog.tsx");
  assert.match(dialog, /dialog\.showModal\?\.\(\);\s*newRef\.current\?\.focus\(\);/);
  assert.match(dialog, /aria-labelledby=\{headingId\}\s*aria-describedby=\{leadId\}/);
  assert.match(dialog, /onCancel=\{\(event\) => \{\s*event\.preventDefault\(\);\s*onCancel\(\);\s*\}\}/);
  assert.match(dialog, /<h2 id=\{headingId\}>\{SAME_RIDE_QUESTION\}<\/h2>/);
});
