import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { versionSaid, versionShort } from "./appVersion.ts";

const here = new URL(".", import.meta.url);

test("Help says RouteMaker version N; under the heading, which said RouteMaker, it is Version N", () => {
  assert.equal(versionSaid("0.10.1"), "RouteMaker version 0.10.1");
  assert.equal(versionSaid(""), "");
  assert.equal(versionShort("0.10.1"), "Version 0.10.1");
  assert.equal(versionShort(""), "");
});

test("the build puts package.json's version in, and the page shows it by the heading and in Help", () => {
  const config = readFileSync(new URL("../../vite.config.ts", here), "utf8");
  assert.match(config, /"import\.meta\.env\.VITE_APP_VERSION": JSON\.stringify\(appVersion\)/);
  // The tab's title is index.html's, with the version added: the two must name the same <title>, or nothing is added.
  assert.match(config, /html\.replace\("<title>RouteMaker<\/title>"/);
  assert.match(readFileSync(new URL("../../index.html", here), "utf8"), /<title>RouteMaker<\/title>/);
  const pkg = JSON.parse(readFileSync(new URL("../../package.json", here), "utf8"));
  assert.match(pkg.version, /^\d+\.\d+\.\d+$/);
  const app = readFileSync(new URL("../App.tsx", here), "utf8");
  // Out of the heading, so the Plan button's focus on it says "RouteMaker" only; seen as v0.10.1, heard once in full.
  assert.match(app, /<div className="panel-title">\s*<h1 [^>]*>\s*\{PLANNER_TITLE\}\s*<\/h1>\s*\{APP_VERSION && !goMode && \(\s*<p className="app-version">\s*<span aria-hidden="true">v\{APP_VERSION\}<\/span>\s*<span className="visually-hidden">\{versionShort\(\)\}<\/span>/);
  const info = readFileSync(new URL("./mapInfo.ts", here), "utf8");
  assert.match(info, /versionSaid\(\)/);
});

test("the name is never squeezed: the switch and Hide planner wrap under it as one row (phone, large text, 2026-10-25)", () => {
  const app = readFileSync(new URL("../App.tsx", here), "utf8");
  assert.match(app, /<div className="panel-actions">\s*\{!goMode && <ModeSwitch [^\n]*\/>\}\s*<button\s+type="button"\s+hidden=\{goMode\}\s+className="panel-toggle"/);
  const css = readFileSync(new URL("../styles.css", here), "utf8");
  assert.match(css, /\.panel-header \{\s*display: flex;\s*flex-wrap: wrap;/);
  assert.match(css, /\.panel-title \{[^}]*flex: 0 0 auto;/);
  assert.doesNotMatch(css.match(/\.panel-title \{[^}]*\}/)![0], /min-width: 0/);
});
