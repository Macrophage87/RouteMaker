// A link opened during a ride asks first (the 2026-10-29 review); a crash in a part that is not the ride leaves the ride on.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { OPEN_LINK_ASK, OPEN_LINK_EVENT, watchOpenLinks } from "./rideLinks.ts";
import { guardForProps, guardOutcome } from "./rideGuard.ts";

function rig(onBike: boolean, yes: boolean) {
  const target = new EventTarget();
  const asked: string[] = [];
  const opened: string[] = [];
  const stop = watchOpenLinks(target, () => onBike, (q) => (asked.push(q), yes), (url) => opened.push(url));
  const send = (detail: unknown) => target.dispatchEvent(new CustomEvent(OPEN_LINK_EVENT, { detail, cancelable: true }));
  return { asked, opened, stop, send };
}

test("off the bike a link opens at once; on it, only once the rider says yes", () => {
  const off = rig(false, false);
  assert.equal(off.send("https://example.org/#a"), false, "taken: the app does not open it itself");
  assert.deepEqual(off.opened, ["https://example.org/#a"]);
  assert.deepEqual(off.asked, []);
  const no = rig(true, false);
  no.send("https://example.org/#b");
  assert.deepEqual(no.asked, [OPEN_LINK_ASK]);
  assert.deepEqual(no.opened, [], "the ride goes on");
  const yes = rig(true, true);
  yes.send("https://example.org/#c");
  assert.deepEqual(yes.opened, ["https://example.org/#c"]);
  // Not a link: left alone, so nothing is taken.
  assert.equal(yes.send(42), true);
  yes.stop();
  assert.equal(yes.send("https://example.org/#d"), true, "stopped: no longer taken");
  assert.equal(OPEN_LINK_ASK, "Leave your ride to open this link?");
});

test("the phone app hands a link to the site's page when it is open, and opens it itself otherwise", () => {
  const main = readFileSync(fileURLToPath(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/MainActivity.java", import.meta.url)), "utf8");
  assert.match(main, /protected void onNewIntent\(Intent intent\) \{\s*super\.onNewIntent\(intent\);\s*handToPage\(intent\);/);
  assert.match(main, /if \(siteClient == null \|\| !siteClient\.topLevelIsSite\(\)\) \{\s*openShared\(intent\);/);
  assert.ok(main.includes(`new CustomEvent('${OPEN_LINK_EVENT}',{detail:`));
  assert.match(main, /if\(window\.dispatchEvent\(e\)\)location\.assign\(/, "a page that does not take it: opened as before");
  assert.match(main, /String quoted = JSONObject\.quote\(link\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /useEffect\(\(\) => watchOpenLinks\(window, \(\) => onBikeNow\.current, /);
});

test("the map, its overlays and the hidden planner are guarded: an error in one leaves the ride on", () => {
  assert.equal(guardOutcome(true), "leave-out");
  assert.equal(guardOutcome(false), "pass-on", "off the bike: the crash screen, as before");
  // A part left out during the ride is cleared as the ride ends, before it is drawn, so the old error is not thrown then.
  const left = { error: new Error("x"), failed: true, wasOn: true };
  assert.equal(guardForProps(left, true), left, "still riding: still left out");
  assert.deepEqual(guardForProps(left, false), { error: null, failed: false, wasOn: false });
  assert.deepEqual(guardForProps({ error: null, failed: false, wasOn: false }, true), { error: null, failed: false, wasOn: true });
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /<RideGuard on=\{onBike\}>\s*<LiveMap/);
  assert.match(app, /<RideGuard on=\{onBike\}>\s*<RepairStandsOverlay /);
  assert.match(app, /<RideGuard on=\{onBike\}>\s*<aside\s+ref=\{panelRef\}/);
  assert.equal(app.match(/<\/RideGuard>/g)?.length, 3);
  // Ride mode itself is not guarded: a ride that fails shows the crash screen, and Resume after Reload.
  assert.doesNotMatch(app, /<RideGuard[^>]*>\s*<RideMode/);
});
