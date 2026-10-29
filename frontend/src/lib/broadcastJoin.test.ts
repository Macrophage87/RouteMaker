// Joining a broadcast (Stephen 2026-10-28: "For joining a broadcast ride also add the ability to download the gpx, or
// send to garmin/wahoo if connected. Have this be just a big popup when you join").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { JOINED_KEEP_MS, JOINED_KEY, JOINED_MAX, JOIN_TITLE, joinActions, joinKey, joinLine, joinShown, joinTitle, keepJoinShown, showJoin } from "./broadcastJoin.ts";
import { FILES_PLUGIN, GPX_CHOOSER, GPX_HAND_FAILED, handGpx, pluginGpxName } from "./sendToGarmin.ts";
import type { CapacitorBridge } from "./nativeShell.ts";

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const dialog = readFileSync(new URL("../BroadcastJoinDialog.tsx", import.meta.url), "utf8");

function memoryStore(): { getItem(key: string): string | null; setItem(key: string, value: string): void; data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

const ON = { available: true, connected: true };
const OFF = { available: true, connected: false };

test("shown once per joined ride: kept when shown, so a reload or a resumed ride does not show it again", () => {
  const store = memoryStore();
  const key = joinKey("0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210");
  const now = 1_800_000_000_000;
  assert.equal(joinShown(key, store, now), false);
  keepJoinShown(key, store, now);
  assert.equal(joinShown(key, store, now + 60_000), true, "the same ride again (a reload)");
  assert.equal(joinShown(joinKey("0123456789abcdef0123456789abcdef", "another-leader"), store, now), false, "another leader's broadcast is another ride");
  assert.equal(joinShown(joinKey("another-line", "fedcba9876543210fedcba9876543210"), store, now), false);
  assert.equal(joinShown(key, store, now + JOINED_KEEP_MS), false, "after a day it is a new ride");
});

test("the kept list stays small, drops old rides, and storage that refuses or holds junk shows the sheet", () => {
  const store = memoryStore();
  const now = 1_800_000_000_000;
  keepJoinShown("old", store, now - JOINED_KEEP_MS - 1);
  for (let i = 0; i < JOINED_MAX + 5; i += 1) keepJoinShown(`ride${i}`, store, now + i);
  const kept = JSON.parse(store.data.get(JOINED_KEY)!) as [string, number][];
  assert.equal(kept.length, JOINED_MAX);
  assert.ok(!kept.some(([k]) => k === "old"));
  assert.equal(kept[kept.length - 1][0], `ride${JOINED_MAX + 4}`);
  store.data.set(JOINED_KEY, "{not json");
  assert.equal(joinShown("ride1", store, now), false);
  const refusing = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
  assert.doesNotThrow(() => keepJoinShown("x", refusing, now));
  assert.equal(joinShown("x", null, now), false);
  assert.doesNotThrow(() => keepJoinShown("x", null, now));
});

test("showJoin: only a follower's ride the link started, not shown before, with something to offer", () => {
  const go = { following: true, started: true, shownBefore: false, actions: 1 };
  assert.equal(showJoin(go), true);
  assert.equal(showJoin({ ...go, following: false }), false, "never the leader");
  assert.equal(showJoin({ ...go, started: false }), false, "no ride started (a computer, the Resume question)");
  assert.equal(showJoin({ ...go, shownBefore: true }), false, "once per ride");
  assert.equal(showJoin({ ...go, actions: 0 }), false, "nothing to offer but Just ride");
});

test("joinActions: GPX where a file can be handed on; Garmin and Wahoo only where connected", () => {
  // Signed out: nothing read of either connection.
  assert.deepEqual(joinActions({ canHandFile: true, garmin: undefined, wahoo: undefined }), ["gpx"]);
  assert.deepEqual(joinActions({ canHandFile: true, garmin: ON, wahoo: ON }), ["gpx", "garmin", "wahoo"]);
  assert.deepEqual(joinActions({ canHandFile: true, garmin: OFF, wahoo: ON }), ["gpx", "wahoo"]);
  assert.deepEqual(joinActions({ canHandFile: true, garmin: ON, wahoo: OFF }), ["gpx", "garmin"]);
  assert.deepEqual(joinActions({ canHandFile: true, garmin: { available: false, connected: true }, wahoo: undefined }), ["gpx"], "a server without Garmin's keys");
  // A phone app from before its file plugin can hand on no file.
  assert.deepEqual(joinActions({ canHandFile: false, garmin: ON, wahoo: undefined }), ["garmin"]);
  assert.deepEqual(joinActions({ canHandFile: false, garmin: undefined, wahoo: undefined }), []);
});

test("the title names the shared route where it has a name; the line is distance · time", () => {
  assert.equal(joinTitle("Hains Point loop"), 'Joined the ride "Hains Point loop"');
  assert.equal(joinTitle("  "), JOIN_TITLE);
  assert.equal(joinTitle(undefined), JOIN_TITLE);
  assert.equal(joinLine({ distance_m: 20_000, duration_s: 3900 }), "12.4 mi (20.0 km) · 1 h 05 min");
});

test("handGpx: in the phone app the GPX file goes to Android's Open with list; in a browser it is the caller's download", async () => {
  assert.equal(await handGpx("<gpx/>", "r.gpx", null), null);
  const calls: unknown[][] = [];
  const shell = (answer: () => Promise<unknown>): CapacitorBridge => ({
    isNativePlatform: () => true,
    isPluginAvailable: (name) => name === FILES_PLUGIN,
    nativePromise: (plugin, method, options) => {
      calls.push([plugin, method, options]);
      return answer();
    },
    nativeCallback: () => "",
  });
  assert.equal(await handGpx("<gpx/>", "Hains Point loop.gpx", shell(async () => ({ app: "chooser" }))), GPX_CHOOSER);
  assert.deepEqual(calls[0], [FILES_PLUGIN, "openWith", { name: "Hains-Point-loop.gpx", data: btoa("<gpx/>"), anyApp: true }]);
  assert.equal(await handGpx("<gpx/>", "r.gpx", shell(() => Promise.reject(new Error("no app")))), GPX_HAND_FAILED);
  assert.equal(pluginGpxName("routemaker-default-12_4mi.gpx"), "routemaker-default-12_4mi.gpx");
  assert.equal(pluginGpxName("Café ride (Sunday).gpx"), "Caf-ride-Sunday.gpx");
  assert.equal(pluginGpxName("...gpx"), "route.gpx");
});

test("App: the sheet comes only from a followed broadcast's own start, over that ride, with the GPX sheet's own actions", () => {
  assert.match(app, /if \(sharedFollow\) \{\s*startRideNoted\(BROADCAST_FOLLOWING\);\s*if \(sharedOpen\?\.id && sharedOpen\.lead\) offerJoin\(/);
  assert.match(app, /<BroadcastJoinDialog ask=\{riding \? joinAsk : null\}/);
  assert.match(app, /if \(action === "gpx"\) downloadRoute\(said\);\s*else if \(action === "garmin"\) sendToGarminRoute\(said\);\s*else sendToWahooRoute\(said\);/);
  // No closure question over a followed ride: the leader's to weigh.
  assert.match(app, /if \(shown && followsBroadcast\(shown\)\) return proceed\(\);/);
});

test("the sheet: a modal dialog, closed by Escape, a tap outside, Just ride or a screen left alone; results said politely, not spoken", () => {
  assert.match(dialog, /dialog\.showModal\?\.\(\);\s*firstRef\.current\?\.focus\(\);/);
  assert.match(dialog, /onCancel=\{\(event\) => \{\s*event\.preventDefault\(\);\s*onClose\(\);/);
  assert.match(dialog, /if \(event\.target === event\.currentTarget\) onClose\(\);/);
  assert.match(dialog, /\[IDLE_CLOSE_ATTR\]: ""/);
  assert.match(dialog, /role="status" aria-live="polite"/);
  assert.doesNotMatch(dialog, /announce|speak/);
});
