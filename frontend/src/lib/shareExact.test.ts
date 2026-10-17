// v0.9.0, "share the exact route" (Stephen 2026-10-17: "For sharing, especially in a mass or group ride, it's
// essential that everyone's on the same map ... It should be the same GPX identical file"): an opened file is shared
// and saved with the route shown for it, and opens as that line, in its mode, ride type and sliders.
import { test } from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import type { RouteResponse } from "./api.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { asKept, rideAfterImport } from "./gpxEdit.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import { keptPlanKey } from "./offlineRoutes.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { gpxSave, planSave } from "./savedRoutes.ts";
import { sharedBody, storeShared } from "./sharedRoutes.ts";

const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");

const FILE_POINTS: LonLat[] = [
  [-77.0365, 38.8977],
  [-77.03, 38.9],
];
const TRACK: Array<[number, number, number]> = [
  [-77.0365, 38.8977, 12],
  [-77.033, 38.899, 13],
  [-77.03, 38.9, 14],
];

function file(changes: Partial<ImportedPlan> = {}): ImportedPlan {
  return {
    points: FILE_POINTS.map((p) => [...p] as LonLat),
    preset: null,
    pointNames: ["Lincoln Memorial", undefined],
    source: "track",
    reference: TRACK.map(([lon, lat]) => [lon, lat] as LonLat),
    referenceM: 600,
    notes: [],
    verbatim: { text: "<gpx/>", track: TRACK },
    ...changes,
  };
}

function followed(exactly: boolean): RouteResponse {
  return {
    distance_m: 640,
    geometry: { type: "LineString", coordinates: TRACK.map(([lon, lat]) => [lon, lat]) },
    follows_file: true,
    follows_exactly: exactly,
    candidates: [{}],
    avoid_alternate: {},
    closure_through: {},
  } as unknown as RouteResponse;
}

test("a file's save keeps the route shown for it, without the other candidates; with none shown, none", () => {
  const dials = startDials("mass-ride", null);
  const save = gpxSave("Parade", "<gpx/>", TRACK, FILE_POINTS, "mass-ride", dials, followed(true));
  assert.equal(save.source, "gpx");
  assert.equal(save.gpx, "<gpx/>");
  assert.equal(save.answer?.follows_exactly, true);
  assert.equal(save.answer?.candidates, null);
  assert.equal(save.answer?.closure_through, null);
  assert.deepEqual(save.line, TRACK);
  assert.equal("answer" in gpxSave("Parade", "<gpx/>", TRACK, FILE_POINTS, "mass-ride", dials), false);
  // The shared body carries it, as a planned route's does.
  const shared = sharedBody("0".repeat(32), save);
  assert.equal(shared?.body.answer?.follows_exactly, true);
  assert.equal(shared?.body.gpx, "<gpx/>");
  // A planned route's save is unchanged.
  assert.equal(planSave("A to B", followed(false), FILE_POINTS, "default", startDials("default", null)).answer?.candidates, null);
});

test("a kept file opens on its kept plan: points, ride type, sliders, and Follow exactly as it was", () => {
  const dials = { ...startDials("mass-ride", null), stress: 1 };
  const at = decodePlan(encodePlan(FILE_POINTS, "mass-ride", dials));
  const opened = asKept(file(), at, followed(true));
  assert.equal(opened.exact, true);
  assert.equal(opened.preset, "mass-ride");
  assert.deepEqual(opened.points, FILE_POINTS);
  // The file's own names stay where the points are the file's own.
  assert.deepEqual(opened.pointNames, ["Lincoln Memorial", undefined]);
  // By the rules: not exact.
  assert.equal(asKept(file(), at, followed(false)).exact, false);
  // Fitted points (not the file's): its names, index for index, would name the wrong points, so they go.
  const fitted = decodePlan(encodePlan([FILE_POINTS[0], [-77.033, 38.899], FILE_POINTS[1]], "mass-ride", dials));
  const moved = asKept(file(), fitted, followed(false));
  assert.equal(moved.points.length, 3);
  assert.equal(moved.pointNames, undefined);
  // Without a kept route (a link or save from before), the file opens as it always did.
  assert.deepEqual(asKept(file(), at, null), file());
  assert.deepEqual(asKept(file(), null, followed(true)), file());
});

test("the kept line answers the plan the file opens on, whatever ride the opener had before", () => {
  const dials = { ...startDials("group-ride", null), stress: 1 };
  const at = decodePlan(encodePlan(FILE_POINTS, "group-ride", dials));
  const opened = asKept(file(), at, followed(true));
  const before = { preset: "default" as const, dials: { ...startDials("default", null), when: "2026-10-18T09:00" } };
  const ride = rideAfterImport(opened, before);
  assert.equal(keptPlanKey(opened.points, ride.preset, ride.dials), keptPlanKey(at.points, at.preset, at.dials));
});

test("App: Share, Copy link and Save route send a file with its settled route; the link opens it unchanged", () => {
  // Only the route of the mode asked for: just after the switch, the other mode's route is not shared or saved.
  assert.match(app, /shown && !stale && routedPoints === points && \(!shown\.follows_file \|\| \(shown\.follows_exactly === true\) === \(importBase\.current\?\.exact === true && mode === "plan"\)\)/);
  const exact = app.slice(app.indexOf("const shareExact = () => {"), app.indexOf("\n  };\n", app.indexOf("const shareExact = () => {")));
  // A new line (the other mode) is a new link, not the first one handed out again.
  assert.match(exact, /of: settled \?\? verbatim,/);
  assert.match(exact, /verbatim\.track, points, preset, dials, settled\)/);
  assert.match(app, /verbatim\.track, points, preset, dials, fileShown\(\)\)/);
  const open = app.slice(app.indexOf("const openSaved = ("), app.indexOf("const exportSaved = "));
  assert.match(open, /savedShown\.current = \{ key: keptPlanKey\(at\.points, at\.preset, at\.dials\), answer \};/);
  assert.match(open, /openImportedChecked\(asKept\(\{ \.\.\.outcome\.plan, name: saved\.name \}, at, answer\)\);/);
  // The importBase starts in the kept mode; switching it plans the file again rather than replaying the kept line.
  assert.match(app, /importBase\.current = \{ imported, points, preset, exact: imported\.exact === true \};/);
  assert.match(app, /exact: on, unfollowed: false \};\s*\/\/[^\n]*\n\s*savedShown\.current = null;/);
});

test("a line the server does not answer for is given up on, so Share and Copy link can say it was not kept", async () => {
  const never = ((_url: string, init?: RequestInit) =>
    new Promise<Response>((_done, fail) => init?.signal?.addEventListener("abort", () => fail(new DOMException("x", "AbortError"))))) as typeof fetch;
  assert.equal(await storeShared("https://x.test", "{}", never, 20), false);
  const kept = (async () => new Response("{}", { status: 201 })) as typeof fetch;
  assert.equal(await storeShared("https://x.test", "{}", kept, 20), true);
  // Copy link says "Link copied." at once; a line not kept is said after, on its own.
  const copy = app.slice(app.indexOf("const copyLink = async () => {"), app.indexOf("\n  };\n", app.indexOf("const copyLink = async () => {")));
  assert.ok(copy.indexOf("setLinkSaid(linkSaidFor(done))") < copy.indexOf("await kept"));
});
