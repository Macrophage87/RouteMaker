/** Plan on a phone (P10): the panel is a sheet with Go's handle and sizes; one of each control in Plan. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = read("../App.tsx");
const go = read("../app/Go.tsx");
const css = read("../styles.css");
const sheets = read("../app/Sheets.tsx");

test("Go's handle is one component, and Plan's phone panel uses it with the switch in the handle row", () => {
  assert.match(go, /export function SheetHandle\(/);
  assert.match(go, /<SheetHandle size=\{size\} onSize=\{onSize\} \/>/);
  assert.equal((go.match(/className="go-handle"/g) ?? []).length, 1);
  assert.match(app, /const planSheet = !goMode && narrow;/);
  assert.match(app, /const planSheetSize: GoSheetSize = panelOpen \? planSize : "peek";/);
  assert.match(
    app,
    /<header className="panel-header plan-handle-row">\s*<h1 ref=\{plannerHeadingRef\} tabIndex=\{-1\} className="visually-hidden">\s*\{PLANNER_TITLE\}\s*<\/h1>\s*<SheetHandle size=\{planSheetSize\} onSize=\{sizePlanSheet\} controls="panel-body" expanded=\{panelOpen\} \/>\s*<ModeSwitch /,
  );
  // The peek is the planner hidden (Hide planner's place); a computer keeps its header with the name and the version.
  assert.match(app, /if \(next === "peek"\) \{\s*setPanelOpen\(false\);/);
  assert.match(app, /\{APP_VERSION && !goMode && \(\s*<p className="app-version">/);
});

test("the sizes are Go's half and full, on a phone only; the version is in Settings, About", () => {
  const phone = css.slice(css.indexOf("/* Plan on a phone (P10)"));
  assert.match(phone, /^[^]*?@media \(max-width: 720px\) \{[^]*?\.panel\.plan-sheet\.plan-half \{\s*max-height: 56%;/);
  assert.match(phone, /\.panel\.plan-sheet\.plan-full \{\s*max-height: calc\(100% - 64px\);/);
  assert.match(css, /\.panel\.go-panel\.go-half \{\s*max-height: 56%;/);
  assert.match(css, /\.panel\.go-panel\.go-full \{\s*max-height: calc\(100% - 64px\);/);
  assert.match(sheets, /\{APP_VERSION && <p className="hint settings-version">\{versionSaid\(\)\}<\/p>\}/);
});

test("one of each in Plan: Undo and Redo on the bar, Clear the bar's trash, Route the bar's, Start in the bar and the route row", () => {
  assert.match(app, /data-history="undo" onClick=\{undo\} aria-label=\{t\("Undo"\)\} title=\{t\("Undo"\)\} aria-keyshortcuts="Control\+Z Meta\+Z"/);
  assert.match(app, /historyHere: !narrow && !planFirst,/);
  assert.doesNotMatch(app, /onClear=\{clearPlan\}/);
  assert.match(app, /className="secondary plan-bar-route plan-bar-start" onClick=\{startRideChecked\}/);
  assert.doesNotMatch(read("../RouteDescription.tsx"), /rideAction/);
});
