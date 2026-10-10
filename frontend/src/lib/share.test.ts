// Share (owner, 2026-10-10): the phone's share sheet for Copy link's link. App.tsx is not rendered by a
// test, so its wiring is read as source, as sidebar.test.ts does for Copy link.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { startDials, type Dials } from "./dials.ts";
import { encodePlan } from "./planHash.ts";
import { linkToCopy } from "./sidebar.ts";
import {
  SHARE_FAILED,
  SHARE_LABEL,
  SHARE_NAME,
  SHARE_TITLE,
  canShareLink,
  shareContent,
  shareLink,
  shareSaidFor,
  shareText,
  type ShareContent,
} from "./share.ts";

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const noop = async () => {};

test("Share shows only where the browser has navigator.share and, if it can say, can share a link", () => {
  assert.equal(canShareLink(undefined, "https://x.test/"), false);
  assert.equal(canShareLink({}, "https://x.test/"), false);
  assert.equal(canShareLink({ share: noop }, "https://x.test/"), true);
  assert.equal(canShareLink({ share: noop, canShare: () => true }, "https://x.test/"), true);
  assert.equal(canShareLink({ share: noop, canShare: () => false }, "https://x.test/"), false);
  assert.equal(
    canShareLink({ share: noop, canShare: () => { throw new TypeError("no"); } }, "https://x.test/"),
    false,
  );
  const asked: unknown[] = [];
  canShareLink({ share: noop, canShare: (d) => (asked.push(d), true) }, "https://x.test/#p=1");
  assert.deepEqual(asked, [{ url: "https://x.test/#p=1" }]);
});

test("the shared text is the distance, US first with metric in brackets, and the ride type; nothing else", () => {
  assert.equal(shareText(7563, "Group Ride"), "4.7 mi (7.6 km) bike route. Ride type: Group Ride.");
  const content = shareContent("https://x.test/#p", 7563, "Default");
  assert.deepEqual(Object.keys(content).sort(), ["text", "title", "url"]);
  assert.equal(content.title, SHARE_TITLE);
  assert.equal(SHARE_TITLE, "RouteMaker route");
});

test("the shared URL is Copy link's, at its full precision and without the weight", async () => {
  const points: Array<[number, number]> = [
    [-77.0312345, 38.9012345],
    [-77.0598765, 38.9234567],
  ];
  const dials: Dials = { ...startDials("default"), systemWeightKg: 97.5 };
  const where = { origin: "https://x.test", pathname: "/", search: "" };
  const url = linkToCopy(where, points, "default", dials);
  const sent: ShareContent[] = [];
  const outcome = await shareLink({ share: async (d) => void sent.push(d) }, shareContent(url, 5000, "Default"));
  assert.equal(outcome, "shared");
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, url);
  assert.equal(sent[0].url, `https://x.test/${encodePlan(points, "default", dials)}`);
  assert.doesNotMatch(`${sent[0].url} ${sent[0].text}`, /weight|97\.5|\bkg\b|\blbs?\b/i);
  // App hands share exactly the link Copy link copies.
  assert.match(app, /shareContent\(linkToCopy\(window\.location, points, preset, dials\), shown\.distance_m, presetLabel\(preset\)\)/);
  assert.match(app, /copyText\(linkToCopy\(window\.location, points, preset, dials\), navigator\.clipboard, selectionCopy\)/);
});

test("the rider closing the sheet is silent; any other failure says so and offers Copy link", async () => {
  const content = shareContent("https://x.test/", 1000, "Default");
  const abort = Object.assign(new Error("cancelled"), { name: "AbortError" });
  assert.equal(await shareLink({ share: () => Promise.reject(abort) }, content), "cancelled");
  assert.equal(await shareLink({ share: () => Promise.reject(new DOMException("x", "AbortError")) }, content), "cancelled");
  assert.equal(await shareLink({ share: () => Promise.reject(new DOMException("x", "NotAllowedError")) }, content), "failed");
  assert.equal(await shareLink({ share: () => Promise.reject(null) }, content), "failed");
  assert.equal(await shareLink({}, content), "failed");
  assert.equal(shareSaidFor("shared"), "");
  assert.equal(shareSaidFor("cancelled"), "");
  assert.equal(shareSaidFor("failed"), SHARE_FAILED);
  assert.match(SHARE_FAILED, /Copy link/);
});

test("App shows Share beside Copy link only where it is supported, named Share route, described by the location line", () => {
  assert.equal(SHARE_LABEL, "Share");
  assert.equal(SHARE_NAME, "Share route");
  assert.ok(SHARE_NAME.startsWith(SHARE_LABEL), "the accessible name holds the visible word");
  assert.match(app, /const \[canShare\] = useState\(\(\) => canShareLink\(navigator, window\.location\.href\)\);/);
  const copy = app.indexOf("{COPY_LINK}");
  const share = app.indexOf("{canShare && (");
  assert.ok(copy > 0 && share > copy && share - copy < 200, "right after Copy link");
  assert.match(
    app,
    /\{canShare && \(\s*<button type="button" className="secondary" onClick=\{shareRoute\} aria-label=\{SHARE_NAME\} aria-describedby=\{linkNote \? "link-note" : undefined\}>\s*\{SHARE_LABEL\}/,
  );
  // A failure is said in the polite status Copy link uses, and shown; success and cancel say nothing.
  assert.match(app, /const said = shareSaidFor\(await shareLink\(navigator, content\)\);\s*if \(!said\) return;/);
  assert.match(app, /if \(press === linkPresses\.current\) setLinkSpoken\(said\);/);
});
