// Share the identical route (v0.7.0; the owner, 2026-10-15 23:19 UTC): the Share link names the exact line shown,
// kept on the server; opening it shows that line unchanged, with the closure check; the sheet carries the GPX file
// Download GPX saves, where the browser can share files; a line not kept leaves the inputs-only link, said.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse } from "./api.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { gpxSave, planSave } from "./savedRoutes.ts";
import { shareContent, withGpxFile, type ShareNavigator } from "./share.ts";
import {
  SHARED_GONE,
  SHARED_INPUTS_ONLY,
  SHARED_MAX_BYTES,
  SHARED_OPENED,
  SHARED_REVOKED,
  gpxShareFile,
  keepSaid,
  listSharedLinks,
  newSharedId,
  previewImageOk,
  publicAnswer,
  readShared,
  regenerateSharedLink,
  revokeSharedLink,
  sharedBody,
  sharedIdFrom,
  storeShared,
  withSharedId,
} from "./sharedRoutes.ts";
import { appSource } from "../testSupport/appSource.mjs";

const app = appSource();
const ID = "0123456789abcdef0123456789abcdef";
const POINTS: LonLat[] = [
  [-77.0312345, 38.9012345],
  [-77.0598765, 38.9234567],
];
const ROUTE = {
  geometry: {
    type: "LineString",
    coordinates: [
      [-77.0312345, 38.9012345],
      [-77.04, 38.91],
      [-77.0598765, 38.9234567],
    ],
  },
  distance_m: 3210.5,
  candidates: [{}],
  avoid_alternate: {},
  effort_m: 3500,
  dials: { stress: 50, hills: 0, when: "now", carrying: null, system_weight_kg: 97 },
} as unknown as RouteResponse;

test("the id is 128 random bits as 32 hex characters, from the browser's random source", () => {
  const id = newSharedId();
  assert.match(id, /^[0-9a-f]{32}$/);
  assert.notEqual(newSharedId(), id);
  assert.equal(
    newSharedId((bytes) => bytes.fill(255)),
    "f".repeat(32),
  );
});

test("the link keeps its plan and adds the line's id; an older link or a bad id names none", () => {
  const hash = encodePlan(POINTS, "default", startDials("default"));
  const plain = `https://x.test/?palette=cool${hash}`;
  const link = withSharedId(plain, ID);
  // The path names the line for a preview fetcher (which never sends the fragment); the fragment names it too.
  assert.equal(link, `https://x.test/s/${ID}${hash}&route=${ID}`);
  assert.equal(sharedIdFrom(new URL(link).hash), ID);
  // The plan is the same with or without the id: a link whose line has gone plans it again.
  assert.deepEqual(decodePlan(new URL(link).hash), decodePlan(new URL(plain).hash));
  assert.equal(withSharedId("https://x.test/", ID), `https://x.test/s/${ID}#route=${ID}`);
  // Sent on from /s/<id> as /?route=<id>: read from the query too.
  assert.equal(sharedIdFrom("", `?route=${ID}`), ID);
  assert.equal(sharedIdFrom("#p=1", "?route=nope"), null);
  // Opened by the installed app's worker at its own path.
  assert.equal(sharedIdFrom("#p=1", "", `/s/${ID}`), ID);
  assert.equal(sharedIdFrom("", "", "/s/nope"), null);
  // A link made before the preview path (`/#...&route=<id>`) still opens its line.
  assert.equal(sharedIdFrom(`#p=1&preset=default&route=${ID}`, "", "/"), ID);
  assert.equal(sharedIdFrom(new URL(plain).hash), null);
  for (const bad of ["abc", "G".repeat(32), "0".repeat(31), "0".repeat(33), `${ID.slice(0, 31)}%`]) assert.equal(sharedIdFrom(`#p=1&route=${bad}`), null);
});

test("the shared line is the saved one, verbatim; never the weight, the effort weighed with it or the candidates", () => {
  const save = planSave("Union Station to Capitol Hill", ROUTE, POINTS, "default", startDials("default"));
  const made = sharedBody(ID, save)!;
  assert.equal(made.body.id, ID);
  assert.deepEqual(made.body.line, ROUTE.geometry.coordinates);
  assert.deepEqual(made.body.inputs.points, POINTS);
  assert.equal(made.body.answer?.dials?.system_weight_kg, null);
  assert.equal(made.body.answer?.effort_m, null);
  assert.equal(made.body.answer?.candidates, null);
  assert.doesNotMatch(made.json, /"system_weight_kg":97|"effort_m":3500/);
  assert.deepEqual(JSON.parse(made.json), made.body);
  // An answer weighed with no weight keeps its effort.
  const light = { ...ROUTE, dials: { ...ROUTE.dials!, system_weight_kg: null } } as RouteResponse;
  assert.equal(publicAnswer(light).effort_m, 3500);
  // An opened GPX file: its own text and track, byte for byte.
  const gpx = gpxSave("Ride", "<gpx/>", [[-77.03, 38.9, 12.5], [-77.04, 38.91, 13]], POINTS, "default", startDials("default"));
  const file = sharedBody(ID, gpx)!;
  assert.equal(file.body.gpx, "<gpx/>");
  assert.deepEqual(file.body.line, [[-77.03, 38.9, 12.5], [-77.04, 38.91, 13]]);
});

test("a line over 2 MB is not sent: the link is the inputs only", () => {
  assert.equal(SHARED_MAX_BYTES, 2 * 1024 * 1024);
  const big = gpxSave("Big", "x".repeat(SHARED_MAX_BYTES), [[-77.03, 38.9], [-77.04, 38.91]], POINTS, "default", startDials("default"));
  assert.equal(sharedBody(ID, big), null);
  assert.match(SHARED_INPUTS_ONLY, /plans the route again/);
});

test("storing: the JSON is posted to /api/shared-routes; kept only on 201", async () => {
  const sent: Array<{ url: string; init: RequestInit }> = [];
  const ok = (async (url: string, init: RequestInit) => {
    sent.push({ url, init });
    return new Response("{}", { status: 201 });
  }) as unknown as typeof fetch;
  assert.equal(await storeShared("https://x.test", '{"id":"x"}', ok), true);
  assert.equal(sent[0].url, "https://x.test/api/shared-routes");
  assert.equal(sent[0].init.method, "POST");
  assert.equal(sent[0].init.body, '{"id":"x"}');
  assert.equal((sent[0].init.headers as Record<string, string>)["Content-Type"], "application/json");
  const refused = (async () => new Response("{}", { status: 429 })) as unknown as typeof fetch;
  assert.equal(await storeShared("https://x.test", "{}", refused), false);
  const down = (async () => {
    throw new TypeError("offline");
  }) as unknown as typeof fetch;
  assert.equal(await storeShared("https://x.test", "{}", down), false);
});

test("reading: the line as kept, or null (not kept, another id, the wrong shape, offline, too slow)", async () => {
  const kept = { id: ID, name: "Ride", source: "plan", distance_m: 1, line: [[-77, 38.9], [-77.1, 38.8]], inputs: { hash: "#p=1", points: [], preset: "default", dials: {} }, answer: null, gpx: "" };
  const answer = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
  assert.deepEqual(await readShared("https://x.test", ID, answer(200, kept)), kept);
  assert.equal(await readShared("https://x.test", ID, answer(404, { error: "gone" })), null);
  assert.equal(await readShared("https://x.test", ID, answer(200, { ...kept, id: "f".repeat(32) })), null);
  assert.equal(await readShared("https://x.test", ID, answer(200, { ...kept, line: [] })), null);
  const down = (async () => {
    throw new TypeError("offline");
  }) as unknown as typeof fetch;
  assert.equal(await readShared("https://x.test", ID, down), null);
  const slow = ((_url: string, init: RequestInit) =>
    new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError"))))) as unknown as typeof fetch;
  assert.equal(await readShared("https://x.test", ID, slow, 10), null);
  assert.match(SHARED_GONE, /planned again/);
  assert.equal(SHARED_OPENED("Ride"), 'Opened "Ride", as it was shared.');
});

test("the sheet carries the GPX file only where the browser says it can share it", () => {
  const file = gpxShareFile("<gpx/>", "Ride.gpx")!;
  assert.equal(file.name, "Ride.gpx");
  assert.equal(file.type, "application/gpx+xml");
  const content = shareContent("https://x.test/#p", 1000, "Default");
  const yes: ShareNavigator = { share: async () => {}, canShare: (d) => Array.isArray(d.files) };
  assert.deepEqual(withGpxFile(yes, content, file).files, [file]);
  const no: ShareNavigator = { share: async () => {}, canShare: () => false };
  assert.equal(withGpxFile(no, content, file), content);
  assert.equal(withGpxFile({ share: async () => {} }, content, file), content, "a browser that cannot say is not given it");
  const throwing: ShareNavigator = {
    canShare: () => {
      throw new TypeError("x");
    },
  };
  assert.equal(withGpxFile(throwing, content, file), content);
  assert.equal(withGpxFile(yes, content, null), content);
});

test("App: Share keeps the exact line and attaches the file Download GPX saves; no new control", () => {
  const exact = app.slice(app.indexOf("const shareExact = () => {"), app.indexOf("const shareRoute = async (ride = false): Promise<boolean> => {"));
  // The same verbatim file and the same route file as Download GPX (downloadRoute, GpxPanel's downloadGpx).
  assert.match(exact, /file: verbatimDownload\(verbatim, importEdited, imported\?\.name\)/);
  assert.match(app, /const file = verbatim \? verbatimDownload\(verbatim, importEdited, imported\?\.name\) : null;/);
  assert.match(exact, /file: routeGpxFile\(shown, routedPoints, routedLoop, federalRoute\)/);
  assert.match(app, /downloadGpx\(route, at, routedLoop, federalRoute\)/);
  const panel = readFileSync(new URL("../GpxPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /export function downloadGpx\([^)]*\): void \{\s*const file = routeGpxFile\(route, routedPoints, loop, federal\);/);
  // The saved route's own bodies: the shared line is what Save route keeps.
  assert.match(exact, /save: gpxSave\(/);
  assert.match(exact, /save: planSave\(name, shown, routedPoints, preset, dials\)/);
  // Only a settled route: while a re-plan is pending the link stays the inputs only.
  assert.match(exact, /if \(!shown \|\| stale \|\| routedPoints !== points\) return null;/);
  const share = app.slice(app.indexOf("const shareRoute = async (ride = false): Promise<boolean> => {"), app.indexOf("\n  };\n", app.indexOf("const shareRoute = async (ride = false): Promise<boolean> => {")));
  assert.match(share, /const content = withGpxFile\(navigator, shareContent\(link, distanceM, presetSaid\(preset\)\), file\);/);
  // The link is made in sharedLinkNow, which Share as image's QR code uses too (lib/shareCard.ts).
  assert.match(share, /const now = sharedLinkNow\(\);\s*const \{ kept, exact \} = now;/);
  const linkNow = app.slice(app.indexOf("const sharedLinkNow = () => {"), app.indexOf("\n  };\n", app.indexOf("const sharedLinkNow = () => {")));
  assert.match(linkNow, /kept = before\?\.kept \?\? storeShared\(origin, body!\.json\);/);
  assert.match(linkNow, /const body = before \? null : sharedBody\(id, exact\.save, shareKeep, previewImageOk\(exact\.save\.line, exact\.save\.inputs\.points, myGo\.home, me\.signed_in\)\);/);
  assert.match(share, /said = SHARED_INPUTS_ONLY;/);
  // The QR code's link: only once its exact line is kept; one not kept is tried again under a new id.
  const qr = app.slice(app.indexOf("const shareCardLink = async ()"), app.indexOf("\n  };\n", app.indexOf("const shareCardLink = async ()")));
  assert.match(qr, /const \{ link, kept \} = sharedLinkNow\(\);\s*if \(!kept\) return null;\s*if \(await kept\) return link;\s*if \(sharedLine\.current\?\.kept === kept\) sharedLine\.current = null;\s*return null;/);
  // Share route and Share ride (the owner, 2026-10-18: "There should be the option for sharing the route or sharing
  // a ride"), the one link.
  assert.equal((app.match(/onClick=\{\(\) => shareRoute\((false|true)\)\}/g) ?? []).length, 2);
});

test("App: a shared link's line opens as a saved route does, before the link's first plan is answered", () => {
  assert.match(app, /const SHARED_ID = sharedIdFrom\(window\.location\.hash, window\.location\.search, window\.location\.pathname\);/);
  const send = app.slice(app.indexOf("send: async (plan) => {"), app.indexOf("const saved = savedShown.current;"));
  assert.match(send, /if \(SHARED_WAIT\) await SHARED_WAIT;/);
  const open = app.slice(app.indexOf("void readShared(origin, SHARED_ID)"), app.indexOf("sharedArrived();"));
  assert.match(open, /openSaved\(shared, SHARED_OPENED\(shared\.name\)\);/);
  assert.match(open, /setSharedNote\(SHARED_GONE\);/);
  // openSaved runs the closure check on the line as kept, and keeps the inputs for Update route.
  const opened = app.slice(app.indexOf("const openSaved = ("), app.indexOf("const exportSaved = "));
  assert.match(opened, /void checkThen\("open", saved\.line, false, \(\) => \{\}\);/);
  assert.match(opened, /differsTooMuch\(saved\.distance_m, today\.route\.distance_m\)/);
  // Start ride checks the line about to be ridden.
  // Review F1: through a callback that carries on the voice the press unlocked.
  assert.match(app, /void checkThen\("ride", shown\.geometry\.coordinates, false, \(\) => \{\s*window\.clearTimeout\(slow\);\s*startRide\(false\);/);
});

test("a shared line is kept a year by default; permanently or until a date if the sharer picks (owner, 2026-10-16)", async () => {
  const keepMod = await import("./sharedRoutes.ts");
  const { keepFields, dayFromToday, SHARE_KEEP_DEFAULT, SHARE_KEEP_OPTIONS } = keepMod;
  const now = new Date(2026, 9, 16, 21, 30);
  assert.equal(dayFromToday(1, now), "2026-10-17");
  assert.equal(dayFromToday(30, now), "2026-11-15");
  assert.deepEqual(keepFields(SHARE_KEEP_DEFAULT, now), { keep: "year" });
  assert.deepEqual(keepFields({ keep: "forever", deleteAfter: "" }, now), { keep: "forever" });
  assert.deepEqual(keepFields({ keep: "until", deleteAfter: "2026-11-15" }, now), { keep: "until", delete_after: "2026-11-15" });
  // No date from tomorrow on: the default year, never a refused share.
  for (const bad of ["", "2026-10-16", "2026-10-01", "next week"]) assert.deepEqual(keepFields({ keep: "until", deleteAfter: bad }, now), { keep: "year" });
  assert.deepEqual(SHARE_KEEP_OPTIONS.map(([choice]) => choice), ["year", "forever", "until"]);
  // The body carries it; the default is the first option.
  const save = planSave("A", ROUTE, POINTS, "default", startDials("default"));
  assert.equal(keepMod.sharedBody("0".repeat(32), save)!.body.keep, "year");
  assert.equal(keepMod.sharedBody("0".repeat(32), save, { keep: "until", deleteAfter: "2999-01-01" })!.body.delete_after, "2999-01-01");
});

test("the keeping is chosen under Share in the Files sheet only; a different keeping is a new line", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /\{canShare && ready && onShareKeep && <ShareKeepField value=\{shareKeep\} onChange=\{onShareKeep\} \/>\}/);
  assert.equal(panel.match(/<ShareKeepField /g)?.length, 1, "one place: under Share, in the Files sheet");
  assert.match(panel, /value\.keep === "until" && \(/);
  assert.match(app, /sharedLine\.current\?\.of === exact\.of && sharedLine\.current\.keep === keep/);
  assert.match(app, /sharedBody\(id, exact\.save, shareKeep, /);
});

test("a link its owner turned off: read as revoked, said plainly, and its plan is not planned", async () => {
  const gone = (async () => new Response(JSON.stringify({ error: SHARED_REVOKED, code: "revoked" }), { status: 410 })) as unknown as typeof fetch;
  assert.equal(await readShared("https://x.test", ID, gone), "revoked");
  assert.equal(SHARED_REVOKED, "This link was turned off by its owner.");
  const open = app.slice(app.indexOf("void readShared(origin, SHARED_ID)"), app.indexOf("sharedArrived();"));
  assert.match(open, /if \(shared === "revoked"\) \{\s*sharedRevoked = true;/);
  const send = app.slice(app.indexOf("send: async (plan) => {"), app.indexOf("const saved = savedShown.current;"));
  assert.match(send, /if \(sharedRevoked && \(revokedPlan \?\?= sentPlanKey\(plan\.points, plan\.preset, plan\.dials\)\) === sentPlanKey\(plan\.points, plan\.preset, plan\.dials\)\)/);
  assert.match(send, /return \{ ok: false, error: SHARED_REVOKED_ERROR \};/);
  // A link with no plan: shown as a plan's error is, and said.
  assert.match(open, /if \(decodePlan\(window\.location\.hash\)\.points\.length < 2\) \{\s*setStatus\(\{ kind: "error", error: SHARED_REVOKED_ERROR \}\);\s*announce\(SHARED_REVOKED\);/);
  // The address becomes the page's own once the id is read, so a later Copy link is not the old shared one.
  assert.match(app, /query\.delete\("route"\);\s*window\.history\.replaceState\(window\.history\.state, "", `\/\$\{query\.size \? `\?\$\{query\}` : ""\}\$\{window\.location\.hash\}`\);/);
});

test("signed out, a route from the device's Home has no preview image; signed in the server hides Home itself", () => {
  const home = { point: POINTS[0], label: "Home" };
  const line = [POINTS[0], POINTS[1]];
  assert.equal(previewImageOk(line, POINTS, home, false), false);
  assert.equal(previewImageOk(line, POINTS, home, true), true);
  assert.equal(previewImageOk(line, POINTS, null, false), true);
  // Only passing by: an image.
  const far = { point: [-77.2, 38.99] as LonLat, label: "Home" };
  assert.equal(previewImageOk(line, POINTS, far, false), true);
  const save = planSave("A", ROUTE, POINTS, "default", startDials("default"));
  assert.equal(sharedBody(ID, save, undefined, false)!.body.preview_image, false);
  // Always said: the server takes a share that does not say as no image.
  assert.equal(sharedBody(ID, save)!.body.preview_image, true);
});

test("the owner's links: listed, turned off and replaced with the CSRF token, in Plan's My routes only", async () => {
  const sent: Array<{ url: string; init?: RequestInit }> = [];
  const link = { id: ID, name: "Ride", source: "plan", distance_m: 1609.344, created_at: "", keep: "year", delete_after: null, link: `https://x.test/s/${ID}#route=${ID}` };
  const answer = (status: number, body: unknown) =>
    (async (url: string, init?: RequestInit) => {
      sent.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    }) as unknown as typeof fetch;
  assert.deepEqual(await listSharedLinks("https://x.test", answer(200, { links: [link] })), [link]);
  assert.equal(sent[0].url, "https://x.test/api/me/shared-routes");
  assert.equal(await listSharedLinks("https://x.test", answer(401, {})), null);
  assert.equal(await revokeSharedLink("https://x.test", ID, answer(200, {}), "csrftoken=t0k"), true);
  assert.equal(sent.at(-1)!.url, `https://x.test/api/me/shared-routes/${ID}/revoke`);
  assert.equal((sent.at(-1)!.init!.headers as Record<string, string>)["X-CSRFToken"], "t0k");
  assert.equal(await revokeSharedLink("https://x.test", ID, answer(404, {}), ""), false);
  assert.deepEqual(await regenerateSharedLink("https://x.test", ID, answer(201, link), "csrftoken=t0k"), link);
  assert.equal(sent.at(-1)!.url, `https://x.test/api/me/shared-routes/${ID}/regenerate`);
  assert.equal(await regenerateSharedLink("https://x.test", ID, answer(404, {}), ""), null);
  assert.equal(keepSaid({ keep: "year", delete_after: null }), "kept 1 year after last opened");
  assert.equal(keepSaid({ keep: "forever", delete_after: null }), "kept permanently");
  assert.equal(keepSaid({ keep: "until", delete_after: "2027-01-01" }), "kept until 2027-01-01");
  // Plan only; Turn off takes a second press, as Delete does; each button names its route.
  const appFile = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(appFile, /sharedLinks: mode === "plan", onSharedChange: forgetSharedLine/);
  // After Turn off or New link, Share forgets the id it gave, so it never hands out a dead link.
  assert.match(appFile, /const forgetSharedLine = \(\) => \{\s*sharedLine\.current = null;\s*\};/);
  const mine = readFileSync(new URL("../MyRoutes.tsx", import.meta.url), "utf8");
  assert.match(mine, /\{sharedLinks && <SharedLinks version=\{version\} announce=\{announce\} onChange=\{onSharedChange\} \/>\}/);
  assert.match(mine, /if \(turningOff !== l\.id\) \{\s*setTurningOff\(l\.id\);\s*return;/);
  assert.match(mine, /if \(ok\) onChange\(\);/);
  assert.match(mine, /return;\s*\}\s*onChange\(\);\s*const copied/);
  assert.match(mine, /aria-label=\{`\$\{NEW_LINK\} for \$\{l\.name\}`\}/);
});
