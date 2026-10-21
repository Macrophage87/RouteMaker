import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { tabTitle, versionSaid } from "./appVersion.ts";

const here = new URL(".", import.meta.url);

test("the version reads as RouteMaker version N, and the tab names it", () => {
  assert.equal(versionSaid("0.10.1"), "RouteMaker version 0.10.1");
  assert.equal(versionSaid(""), "");
  assert.equal(tabTitle("0.10.1"), "RouteMaker 0.10.1");
  assert.equal(tabTitle(""), "RouteMaker");
});

test("the build puts package.json's version in, and the page shows it by the heading and in Help", () => {
  const config = readFileSync(new URL("../../vite.config.ts", here), "utf8");
  assert.match(config, /"import\.meta\.env\.VITE_APP_VERSION": JSON\.stringify\(appVersion\)/);
  assert.match(config, /<title>RouteMaker<\/title>/);
  const pkg = JSON.parse(readFileSync(new URL("../../package.json", here), "utf8"));
  assert.match(pkg.version, /^\d+\.\d+\.\d+$/);
  const app = readFileSync(new URL("../App.tsx", here), "utf8");
  // Out of the heading, so the Plan button's focus on it says "RouteMaker" only; seen as v0.10.1, heard once in full.
  assert.match(app, /<div className="panel-title">\s*<h1 [^>]*>\s*\{PLANNER_TITLE\}\s*<\/h1>\s*\{APP_VERSION && !goMode && \(\s*<p className="app-version">\s*<span aria-hidden="true">v\{APP_VERSION\}<\/span>\s*<span className="visually-hidden">\{versionSaid\(\)\}<\/span>/);
  const info = readFileSync(new URL("./mapInfo.ts", here), "utf8");
  assert.match(info, /versionSaid\(\)/);
});
