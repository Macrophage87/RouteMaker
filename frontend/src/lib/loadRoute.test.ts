import { test } from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { LOAD_ROUTE, archivedLink, gpxRideTypes, gpxStartRide, keptLine, loadRows, searchText, withGpxChoice, withTag } from "./loadRoute.ts";
import { matching } from "./routeSearch.ts";
import type { KeptRoute } from "./offlineRoutes.ts";
import type { SavedSummary } from "./savedRoutes.ts";

const saved: SavedSummary = { id: 7, name: "Dupont to Glen Echo", source: "plan", distance_m: 16093, preset: "default", created_at: "2026-10-15T12:00:00Z", updated_at: "2026-10-15T12:00:00Z" };
const kept = { id: "#p=x", plan: "#p=x", title: "Union Station loop", distanceM: 8047, savedAt: 0, lastRide: false } as unknown as KeptRoute;

test("Load route's rows: saved routes first, then the ones kept on this device, each a name and one short line", () => {
  const rows = loadRows([saved], [kept]);
  assert.deepEqual(
    rows.map((r) => [r.kind, r.name]),
    [
      ["saved", "Dupont to Glen Echo"],
      ["kept", "Union Station loop"],
    ],
  );
  assert.match(rows[0].detail, /^10(\.0)? mi .* · Saved Oct 15, 2026$/);
  assert.match(keptLine(kept), / · On this device$/);
  assert.match(keptLine({ ...kept, lastRide: true }), / · Last ride, on this device$/);
  assert.deepEqual(loadRows([], []), []);
});

test("Open GPX file offers every ride type but the transit ones, starting on the page's own", () => {
  const ids = gpxRideTypes().map((r) => r.id);
  assert.ok(ids.includes("default"));
  assert.ok(!ids.includes("bike-transit") && !ids.includes("bikeshare-transit"));
  assert.equal(gpxStartRide("trailmaxxing"), "trailmaxxing");
  assert.equal(gpxStartRide("bike-transit"), "default");
});

test("a file opens on the ride type chosen (its own sliders kept for the same one), followed as chosen", () => {
  const file = { preset: "default" as const, dials: { loop: true }, name: "a.gpx" };
  assert.deepEqual(withGpxChoice(file, { preset: "default", exact: true }), { ...file, exact: true });
  assert.deepEqual(withGpxChoice(file, { preset: "trailmaxxing", exact: false }), { ...file, preset: "trailmaxxing", dials: undefined, exact: false });
  assert.deepEqual(withGpxChoice({ preset: null, name: "b.gpx" }, { preset: "novice", exact: false }), { preset: "novice", name: "b.gpx", dials: undefined, exact: false });
});

test("Go: Load route sits behind More and opens Load route's popup, one name for both (P12: it was Saved routes)", () => {
  const go = readFileSync(new URL("../app/Go.tsx", import.meta.url), "utf8");
  const row = go.slice(go.indexOf('aria-label={t("Places")}'), go.indexOf('aria-label={t("More places")}'));
  assert.ok(!row.includes("LOAD_ROUTE"), "the main row stays as it is: one more control goes behind More");
  const more = go.slice(go.indexOf('aria-label={t("More places")}'), go.indexOf("go-home-sheet"));
  assert.match(more, /aria-haspopup="dialog" onClick=\{places\.onSavedRoutes\}>\s*<Icon name="routes" size=\{18\} \/>\s*\{LOAD_ROUTE\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /onSavedRoutes: \(\) => setLoadOpen\("go"\)/);
  // The one popup with one title, from Plan's bar and Go's chip alike, and a route picked in it opens there (openSaved, openKept).
  assert.match(app, /open=\{loadOpen === "plan" \? barLoad : loadOpen === "go" && mode === "go" && !riding\}\s*onClose=/);
  assert.match(app, /<Icon name="file" size=\{20\} \/>\s*\{LOAD_ROUTE\}/);
  assert.match(readFileSync(new URL("../LoadRouteDialog.tsx", import.meta.url), "utf8"), /<h2 id=\{headingId\}>\{archivedView \? LOAD_ARCHIVED_TITLE : LOAD_ROUTE\}<\/h2>/);
  assert.equal(LOAD_ROUTE, "Load route");
  assert.doesNotMatch(go + app, /Saved routes/);
});

// ---- Tags and archive (the owner, 2026-11-07: "Put an 'archive' button on the view") ----

test("Load route lists the routes not archived, and Archived lists the archived alone, with what replaced one", () => {
  const base = { source: "plan" as const, distance_m: 1609, preset: "default", created_at: "2026-11-01T12:00:00Z", updated_at: "2026-11-01T12:00:00Z" };
  const rows3 = [
    { ...base, id: 2, name: "Commute 2", tags: ["Commute"] },
    { ...base, id: 1, name: "Commute", tags: ["Commute", "Trail"], archived_at: "2026-11-06T12:00:00Z", replaced_by: 2 },
    { ...base, id: 3, name: "Loop", tags: ["Loop"] },
  ];
  const live = loadRows(rows3, [kept]);
  assert.deepEqual(live.map((r) => r.name), ["Commute 2", "Loop", "Union Station loop"]);
  const archived = loadRows(rows3, [kept], true);
  assert.deepEqual(archived.map((r) => r.name), ["Commute"]);
  assert.ok(archived[0].kind === "saved" && archived[0].archived && archived[0].replacedBy === "Commute 2");
  // A tag chip keeps that tag's routes (not the kept ones, which have none); the search finds tags too.
  assert.deepEqual(withTag(live, "commute").map((r) => r.name), ["Commute 2"]);
  assert.equal(withTag(live, null).length, 3);
  assert.deepEqual(matching(live, "loop", searchText).map((r) => r.name), ["Loop", "Union Station loop"]);
  assert.deepEqual(matching(live, "commute", searchText).map((r) => r.name), ["Commute 2"]);
  assert.equal(archivedLink(6), "Archived (6)");
});

test("drafts are rows among the saved routes, the one last opened or made on top (the owner, 2026-11-09)", () => {
  const older: SavedSummary = { ...saved, id: 8, name: "Opened today", created_at: "2026-10-01T12:00:00Z", opened_at: "2026-11-09T09:00:00Z" };
  const draft = { id: "a".repeat(32), name: "Sandwich loop", source: "plan" as const, distance_m: 8047, preset: "default", created_at: "2026-11-08T12:00:00Z", expires_at: "2026-11-15T12:00:00Z" };
  const now = Date.parse("2026-11-09T12:00:00Z");
  const rows = loadRows([saved, older], [kept], false, [draft], now);
  assert.deepEqual(
    rows.map((r) => [r.kind, r.name]),
    [
      ["saved", "Opened today"],
      ["draft", "Sandwich loop"],
      ["saved", "Dupont to Glen Echo"],
      ["kept", "Union Station loop"],
    ],
  );
  assert.match(rows[1].detail, / · Draft, 6 days left$/);
  // The archived list holds no drafts.
  assert.deepEqual(loadRows([saved], [], true, [draft], now), []);
  // A tag leaves drafts out, as it does kept routes; the search finds them by name.
  assert.deepEqual(withTag(rows, "x"), []);
  assert.equal(searchText(rows[1]), "Sandwich loop");
});
