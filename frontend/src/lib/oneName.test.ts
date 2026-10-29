/**
 * One name per thing (the 2026-10-28 audit, P12): Go's Menu is Settings, saved routes are Save & load (the page),
 * My routes (the list) and Load route (the action), each place sheet is named as its chip, "Info" is Details, Tips
 * or Road info, and Broadcast is Share live.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SAVE_LOAD, SHEET_TITLES, BAR_ITEMS } from "./sidebar.ts";
import { ACCOUNT_ROUTES, MY_ROUTES } from "./savedRoutes.ts";
import { LOAD_ROUTE } from "./loadRoute.ts";
import { DETOUR_CHOICES } from "./detourSearch.ts";
import { BROADCAST_ABOUT, BROADCAST_LABEL } from "./share.ts";
import { ROAM_BROADCAST_NAME } from "./roam.ts";
import { infoHeading } from "./roadInfo.ts";
import { statsLine } from "./candidates.ts";
import { ES as es } from "../i18n/es.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

test("P12: Go's Settings is Plan's: the same title and word, its pages above the tabs, and no Plan button", () => {
  const go = src("../app/Go.tsx");
  assert.match(go, /<Icon name="gear" \/>\s*<span className="icon-button-label">\{t\("Settings"\)\}<\/span>/);
  assert.equal(SHEET_TITLES.settings, BAR_ITEMS.find((i) => i.id === "settings")?.label);
  const sheets = src("../app/Sheets.tsx");
  const pages = sheets.slice(sheets.indexOf('<nav className="menu-pages"'), sheets.indexOf("</nav>", sheets.indexOf('<nav className="menu-pages"')));
  assert.ok(pages.length > 0);
  assert.doesNotMatch(pages, /t\("Plan"\)/, "the Go/Plan switch is beside the Settings button");
  assert.match(pages, /t\("Reports"\)[\s\S]*\{SAVE_LOAD\}[\s\S]*t\("Review"\)/);
  assert.doesNotMatch(sheets + src("../App.tsx") + src("./sidebar.ts"), /MENU_TITLE/);
});

test("P12: saved routes: Save & load the page, My routes the list, Load route the action, one title per popup", () => {
  assert.equal(SAVE_LOAD, "Save & load");
  assert.equal(SHEET_TITLES.gpx, "Save & load");
  assert.equal(MY_ROUTES, "My routes");
  assert.equal(LOAD_ROUTE, "Load route");
  // The list's heading is My routes; the saved ones under it are named for where they are, not My routes again.
  const your = src("../YourRoutes.tsx");
  assert.match(your, /<h3 id=\{`\$\{id\}-heading`\}>\{MY_ROUTES\}<\/h3>/);
  assert.match(src("../MyRoutes.tsx"), /<h4 id=\{headingId\}>\{ACCOUNT_ROUTES\}<\/h4>/);
  assert.equal(ACCOUNT_ROUTES, "Saved to your account");
  // Load route's popup has one title, from Plan's bar and Go's More chip alike.
  assert.doesNotMatch(src("../LoadRouteDialog.tsx"), /title\?: string/);
  for (const file of ["../App.tsx", "../app/Go.tsx", "../app/Sheets.tsx", "./sidebar.ts", "../YourRoutes.tsx", "./loadRoute.ts"])
    assert.doesNotMatch(src(file), /t\("(Save and load|Saved routes|Your routes)"\)/, file);
  // Spanish: one short word for the page, and no entry left for the old names.
  assert.equal(es["Save & load"], "Rutas");
  for (const old of ["Save and load", "Saved routes", "Your routes"]) assert.equal(es[old], undefined, old);
});

test("P12: each place sheet is named as its chip: Eat, Repair, Places to see (Go's Sights), in Go, Plan and a ride", () => {
  assert.equal(SHEET_TITLES.food, "Eat");
  assert.equal(SHEET_TITLES.repair, "Repair");
  assert.equal(SHEET_TITLES.places, "Places to see");
  const go = src("../app/Go.tsx");
  assert.doesNotMatch(go, /t\("(Sights|Food)"\)/);
  // Plan's map chips: Find, then Eat (as Go's), Water and Places to see.
  const chips = go.slice(go.indexOf('className="map-chips"'));
  assert.match(chips, /\{t\("Find"\)\}[\s\S]*\{t\("Eat"\)\}[\s\S]*\{t\("Water"\)\}[\s\S]*\{t\("Places to see"\)\}/);
  assert.match(src("../app/PlacesSheets.tsx"), /<SheetFrame id="sheet-places" title=\{SHEET_TITLES\.places\}/);
  // A ride's Detour says Eat as the chips do.
  assert.deepEqual(DETOUR_CHOICES.map((c) => c.label), ["Water", "Restroom", "Eat", "Repair"]);
});

test("P12: Info was three things: Details (the route), Tips (Plan's how-to), Road info (the road panel)", () => {
  assert.match(src("../app/RoutePanel.tsx"), /route-info-button"[^\n]*\n\s*<Icon name="info" \/>\s*\{\/\*[^]*?\*\/\}\s*<span>\{t\("Details"\)\}<\/span>/);
  assert.match(src("../app/Planner.tsx"), /tips-toggle"[^\n]*\n\s*<Icon name="info" \/>\s*<span>\{t\("Tips"\)\}<\/span>/);
  assert.equal(infoHeading({ kind: "error" } as never), "Road info");
  for (const file of ["../app/RoutePanel.tsx", "../app/Planner.tsx"]) assert.doesNotMatch(src(file), /t\("Info"\)/, file);
  assert.equal(es.Info, undefined);
});

test("P12: Broadcast is Share live everywhere, its name starting with the word shown, and needs no account", () => {
  assert.equal(BROADCAST_LABEL, "Share live");
  assert.equal(ROAM_BROADCAST_NAME, "Share live");
  assert.match(src("../RideMode.tsx"), /export const RIDE_BROADCAST_NAME = t\("Share live"\);/);
  assert.match(BROADCAST_ABOUT, /No account needed\.$/);
  for (const file of ["./share.ts", "./sharedRoutes.ts", "./roam.ts", "./broadcastQr.ts", "./rideGroup.ts", "../RideMode.tsx", "../RoamMode.tsx"])
    assert.doesNotMatch(src(file), /t\("[^"]*\bBroadcast/i, file);
});

test("P12: the calm ways are paths and protected lanes, in the route options as in Go's stress line", () => {
  const line = statsLine({ overTargetM: null, lts4M: 0, lts3M: 0, red: 0, orange: 0, trailM: 1609, climbM: 0, effortM: null } as never);
  assert.match(line, /on paths and protected lanes$/);
  assert.doesNotMatch(src("./candidates.ts"), /trails and protected lanes/);
});
