// UI-CLEANUP step 4: App.tsx split into the planner, route panel and sheet modules with no change in
// behaviour (docs/DEVELOPMENT.md, "The App.tsx split"). The browser suite (scripts/a11y/check.mjs) holds
// the DOM and the focus; these hold the shape the source tests rely on (testSupport/appSource.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { appSource } from "./testSupport/appSource.mjs";

const read = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const app = read("./App.tsx");
const RENDERED = {
  "./app/Planner.tsx": ["PointsSection", "RideSection"],
  "./app/RoutePanel.tsx": ["RouteSection"],
  "./app/Sheets.tsx": ["LayersSheet", "GpxSheet", "SettingsSheet"],
};

test("App renders each split component once, passing its own names through", () => {
  for (const [file, names] of Object.entries(RENDERED)) {
    const source = read(file);
    for (const name of names) {
      const calls = app.match(new RegExp(`<${name}( key="\\w+")?\\n\\s*\\{\\.\\.\\.\\{`, "g")) ?? [];
      assert.equal(calls.length, 1, `${name} is rendered once, with App's names`);
      // A pass-through: the component takes its props under App's names and keeps no state of its own,
      // so the state, the effects and the focus moves stay in App, as they were.
      const body = source.slice(source.indexOf(`export function ${name}(`));
      const own = body.slice(0, body.indexOf("\n}\n"));
      assert.match(own, /^export function \w+\(props: \w+Props\) \{\n {2}const \{ [\w, ]+ \} = props;/, name);
      assert.doesNotMatch(own, /\buse(State|Effect|LayoutEffect|Ref|Memo|Callback|Id)\(/, `${name} has no hooks`);
    }
  }
});

test("the planner as one text has every component's JSX back in place and no pass-through left", () => {
  const whole = appSource();
  assert.doesNotMatch(whole, /\{\.\.\.\{/);
  for (const marker of [
    '<section key="points" aria-labelledby="points-heading" className="points-section">',
    '<section key="route" aria-labelledby="route-heading" aria-busy={stale} className={goMode ? "route-section go-route" : "route-section"}>',
    '<RideSettings key="presets"',
    'id="sheet-layers"',
    'id="sheet-gpx"',
    'id="sheet-settings"',
    '<div className="route-actions">',
  ]) {
    assert.equal(whole.split(marker).length - 1, 1, marker);
  }
  // In the order App renders them: the planner's sections, the sheets, then the bar (UI-CLEANUP: Start, GPX,
  // Link and More are in the route summary now, not pinned under the panel).
  const at = (marker: string) => whole.indexOf(marker);
  assert.ok(at('id="sheet-layers"') < at('id="sheet-gpx"') && at('id="sheet-gpx"') < at('id="sheet-settings"'));
  assert.ok(at('id="sheet-settings"') < at("<BottomBar"));
});
